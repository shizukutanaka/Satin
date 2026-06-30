"""
Unit tests for content_aggregator — relevance scoring and data model.

ContentAggregator.calculate_relevance_score is pure computation:
no network calls, no external deps.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from content_aggregator import (  # noqa: E402
    ContentAggregator,
    ContentType,
    UnifiedContent,
    _to_naive,
)


def _make_content(
    title="Test",
    description="",
    keywords=None,
    content_type=ContentType.VIDEO,
    published_date=None,
    content_data=None,
):
    return UnifiedContent(
        content_id="test_id",
        content_type=content_type,
        title=title,
        description=description,
        url="https://example.com",
        source="test",
        authors=[],
        published_date=published_date,
        keywords=keywords or [],
        content_data=content_data or {},
    )


def _make_aggregator():
    """Create ContentAggregator with all external dependencies mocked out."""
    with mock.patch("content_aggregator.YouTubeIntegrator"), \
         mock.patch("content_aggregator.PaperIntegrator"), \
         mock.patch("content_aggregator.WebIntegrator"), \
         mock.patch("content_aggregator.CacheManager"), \
         mock.patch("content_aggregator.LoggingManager"):
        agg = ContentAggregator.__new__(ContentAggregator)
        # Attach stub integrators so the constructor doesn't fail on directories
        agg.youtube = mock.MagicMock()
        agg.paper = mock.MagicMock()
        agg.web = mock.MagicMock()
    return agg


class RelevanceScoreTests(unittest.TestCase):
    def setUp(self):
        self._agg = _make_aggregator()

    def test_perfect_keyword_match_high_score(self):
        content = _make_content(title="machine learning basics", keywords=["ml"])
        score = self._agg.calculate_relevance_score(content, "machine learning")
        self.assertGreater(score, 50.0)

    def test_no_keyword_match_lower_score(self):
        content = _make_content(title="cooking recipes", keywords=["food"])
        score = self._agg.calculate_relevance_score(content, "machine learning")
        self.assertLessEqual(score, 20.0)

    def test_empty_query_gives_low_score(self):
        content = _make_content(title="anything")
        score = self._agg.calculate_relevance_score(content, "")
        self.assertGreaterEqual(score, 0.0)

    def test_score_bounded_0_to_100(self):
        content = _make_content(
            title="python python python",
            description="python python",
            keywords=["python"],
            content_data={"view_count": 10_000_000},
            published_date=datetime.now() - timedelta(days=1),
        )
        score = self._agg.calculate_relevance_score(content, "python")
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_popularity_boosts_video_score(self):
        high_views = _make_content(
            title="test", content_data={"view_count": 1_000_000}
        )
        low_views = _make_content(title="test", content_data={"view_count": 1})
        score_high = self._agg.calculate_relevance_score(high_views, "test")
        score_low = self._agg.calculate_relevance_score(low_views, "test")
        self.assertGreater(score_high, score_low)

    def test_recency_boosts_score(self):
        recent = _make_content(
            title="test",
            published_date=datetime.now() - timedelta(days=30),
        )
        old = _make_content(
            title="test",
            published_date=datetime.now() - timedelta(days=800),
        )
        score_recent = self._agg.calculate_relevance_score(recent, "test")
        score_old = self._agg.calculate_relevance_score(old, "test")
        self.assertGreater(score_recent, score_old)

    def test_future_date_does_not_outrank_today(self):
        # Regression: a future published_date made age_days negative, pushing
        # freshness above its 0-10 cap and unfairly boosting future content.
        future = _make_content(
            title="test", published_date=datetime.now() + timedelta(days=400)
        )
        today = _make_content(
            title="test", published_date=datetime.now()
        )
        score_future = self._agg.calculate_relevance_score(future, "test")
        score_today = self._agg.calculate_relevance_score(today, "test")
        self.assertLessEqual(score_future, score_today)

    def test_future_date_score_stays_bounded(self):
        future = _make_content(
            title="machine learning",
            published_date=datetime.now() + timedelta(days=5000),
        )
        score = self._agg.calculate_relevance_score(future, "machine learning")
        self.assertLessEqual(score, 100.0)

    def test_boost_recent_false_ignores_date(self):
        recent = _make_content(
            title="test", published_date=datetime.now() - timedelta(days=1)
        )
        old = _make_content(
            title="test", published_date=datetime.now() - timedelta(days=800)
        )
        score_r = self._agg.calculate_relevance_score(recent, "test", boost_recent=False)
        score_o = self._agg.calculate_relevance_score(old, "test", boost_recent=False)
        self.assertAlmostEqual(score_r, score_o, places=2)

    def test_paper_citation_counted(self):
        cited = _make_content(
            title="test",
            content_type=ContentType.PAPER,
            content_data={"citations": 1000},
        )
        uncited = _make_content(
            title="test",
            content_type=ContentType.PAPER,
            content_data={"citations": 0},
        )
        self.assertGreater(
            self._agg.calculate_relevance_score(cited, "test"),
            self._agg.calculate_relevance_score(uncited, "test"),
        )

    def test_keywords_in_list_contribute_to_score(self):
        with_kw = _make_content(title="intro", keywords=["neural", "network"])
        without_kw = _make_content(title="intro", keywords=[])
        score_with = self._agg.calculate_relevance_score(with_kw, "neural network")
        score_without = self._agg.calculate_relevance_score(without_kw, "neural network")
        self.assertGreater(score_with, score_without)

    def test_returns_float(self):
        content = _make_content(title="test")
        score = self._agg.calculate_relevance_score(content, "test")
        self.assertIsInstance(score, float)

    def test_null_view_count_does_not_crash(self):
        # Regression: content_data.get('view_count', 0) returns None when the key
        # is present but null; max(1, None) then raises TypeError.
        content = _make_content(
            title="test",
            content_type=ContentType.VIDEO,
            content_data={"view_count": None},
        )
        score = self._agg.calculate_relevance_score(content, "test")
        self.assertIsInstance(score, float)
        self.assertGreaterEqual(score, 0.0)

    def test_null_citations_does_not_crash(self):
        # Regression: content_data.get('citations', 0) returns None when the key
        # is present but null; max(1, None) then raises TypeError.
        content = _make_content(
            title="test",
            content_type=ContentType.PAPER,
            content_data={"citations": None},
        )
        score = self._agg.calculate_relevance_score(content, "test")
        self.assertIsInstance(score, float)
        self.assertGreaterEqual(score, 0.0)


class TimezoneAwarenessTests(unittest.TestCase):
    """Regression: YouTube Data API yields tz-aware published dates while
    yt-dlp/papers/web yield naive ones. Mixing them crashed relevance scoring
    (datetime.now() - aware -> TypeError) and date-range analysis (min/max of
    mixed naive+aware -> TypeError), silently dropping all YouTube results."""

    def setUp(self):
        self._agg = _make_aggregator()

    def test_to_naive_strips_tzinfo(self):
        aware = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        out = _to_naive(aware)
        self.assertIsNone(out.tzinfo)

    def test_to_naive_passes_through_naive(self):
        naive = datetime(2024, 1, 1, 12, 0)
        self.assertIs(_to_naive(naive), naive)

    def test_to_naive_handles_none(self):
        self.assertIsNone(_to_naive(None))

    def test_to_naive_converts_offset_to_utc(self):
        # +09:00 09:00 == 00:00 UTC
        from datetime import timezone as _tz
        jst = datetime(2024, 1, 1, 9, 0, tzinfo=_tz(timedelta(hours=9)))
        out = _to_naive(jst)
        self.assertEqual((out.hour, out.tzinfo), (0, None))

    def test_relevance_score_with_aware_published_date(self):
        # An aware published_date (as produced by the YouTube API path) must not
        # raise TypeError against the naive datetime.now() in the freshness calc.
        content = _make_content(
            title="test",
            content_type=ContentType.VIDEO,
            published_date=datetime.now(timezone.utc) - timedelta(days=10),
        )
        # _make_content stores it raw; simulate the convert-funnel normalization.
        content.published_date = _to_naive(content.published_date)
        score = self._agg.calculate_relevance_score(content, "test")
        self.assertIsInstance(score, float)

    def test_convert_youtube_normalizes_aware_date(self):
        video = mock.MagicMock()
        video.video_id = "abc"
        video.title = "t"
        video.description = "d"
        video.channel_title = "c"
        video.published_at = datetime(2024, 6, 1, tzinfo=timezone.utc)
        video.tags = []
        video.to_dict.return_value = {}
        unified = self._agg._convert_youtube_to_unified(video)
        self.assertIsNone(unified.published_date.tzinfo)

    def test_analyze_trends_with_mixed_awareness_does_not_crash(self):
        # After the funnel, all published_date are naive — min/max must work.
        naive_item = _make_content(
            published_date=datetime(2023, 1, 1), content_type=ContentType.PAPER)
        aware_item = _make_content(
            content_type=ContentType.VIDEO,
            published_date=_to_naive(datetime(2024, 1, 1, tzinfo=timezone.utc)))
        analysis = self._agg.analyze_content_trends([naive_item, aware_item])
        self.assertIn("date_range", analysis)
        self.assertIn("earliest", analysis["date_range"])


class WebSourcePreservationTests(unittest.TestCase):
    """Regression: sources=[s for s in sources if s != 'web'] unconditionally
    removed 'web' from AggregationResult.sources even when the caller requested it."""

    def setUp(self):
        self._agg = _make_aggregator()
        # Stub the search helpers so they return empty results quickly
        self._agg._search_youtube = mock.MagicMock(return_value=(True, [], None))
        self._agg._search_arxiv = mock.MagicMock(return_value=(True, [], None))
        self._agg._search_scholar = mock.MagicMock(return_value=(True, [], None))
        self._agg.logger = mock.MagicMock()

    def test_web_source_preserved_in_result(self):
        result = self._agg.search_all_sources(
            query="test", sources=["youtube", "web"], max_results_per_source=1
        )
        self.assertIn("web", result.sources,
                      "AggregationResult.sources must include 'web' when caller requested it")

    def test_non_web_sources_still_present(self):
        result = self._agg.search_all_sources(
            query="test", sources=["youtube", "arxiv", "web"], max_results_per_source=1
        )
        for s in ("youtube", "arxiv", "web"):
            self.assertIn(s, result.sources)


class KnowledgeBaseMutationTests(unittest.TestCase):
    """Regression: create_knowledge_base mutated content_data on shared
    UnifiedContent objects from the AggregationResult, corrupting the source
    data for any caller holding a reference to result.contents."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        self._agg = _make_aggregator()
        self._agg.logger = mock.MagicMock()
        self._tmpdir = tempfile.mkdtemp()
        self._agg.output_dir = Path(self._tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_create_knowledge_base_does_not_mutate_source_content(self):
        from content_aggregator import AggregationResult

        orig = _make_content(
            content_type=ContentType.VIDEO,
            content_data={"view_count": 100},
        )
        result = AggregationResult(
            query="test",
            sources=["youtube"],
            total_results=1,
            contents=[orig],
            aggregation_time=datetime.now(),
            metadata={},
        )
        self._agg.search_all_sources = mock.MagicMock(return_value=result)
        self._agg.youtube.get_transcript = mock.MagicMock(return_value="transcript text")

        self._agg.create_knowledge_base(
            "test", sources=["youtube"], include_transcripts=True, include_full_text=False
        )

        self.assertNotIn(
            "transcript", orig.content_data,
            "create_knowledge_base must not mutate the original UnifiedContent objects",
        )
        self.assertEqual(orig.content_data.get("view_count"), 100,
                         "original content_data values must be unchanged")


class FreshnessScoreMonotonicityTests(unittest.TestCase):
    """Regression: freshness_score was non-monotonic at the 365-day boundary.

    The first formula (age_days <= 365) evaluated to 0 at exactly 365 days,
    while the second formula (365 < age_days <= 730) evaluates to ~5 at 366 days.
    A 1-year-1-day-old item therefore outscored a 1-year-old item in freshness —
    older content ranked *higher* than newer content.

    Fix: change the first segment from ``10*(1 - age/365)`` (10→0) to
    ``5 + 5*(1 - age/365)`` (10→5) so both segments meet continuously at
    age_days=365 → freshness_score=5.
    """

    def setUp(self):
        self._agg = _make_aggregator()

    def _score_for_age(self, age_days):
        """Return relevance_score for content of given age with no keywords or views.

        Popularity and keyword components are constant across all calls, so
        comparing scores from this helper directly measures the freshness ordering.
        """
        pub = datetime.now() - timedelta(days=age_days)
        content = _make_content(title="test", published_date=pub,
                                content_type=ContentType.VIDEO)
        return self._agg.calculate_relevance_score(content, "", boost_recent=True)

    def test_monotonically_decreasing_at_365_day_boundary(self):
        """Score must decrease (or stay equal) as age grows across the 365-day boundary."""
        s364 = self._score_for_age(364)
        s365 = self._score_for_age(365)
        s366 = self._score_for_age(366)
        self.assertGreaterEqual(
            s364, s365,
            f"364-day score ({s364:.4f}) must be >= 365-day ({s365:.4f})",
        )
        self.assertGreaterEqual(
            s365, s366,
            f"365-day score ({s365:.4f}) must be >= 366-day ({s366:.4f})",
        )

    def test_older_content_never_scores_higher_than_newer(self):
        """Full range: older content must never score above newer content."""
        ages = [0, 100, 200, 300, 365, 366, 400, 500, 600, 700, 730]
        scores = [self._score_for_age(a) for a in ages]
        for i in range(len(scores) - 1):
            self.assertGreaterEqual(
                scores[i], scores[i + 1],
                f"Age {ages[i]} days ({scores[i]:.4f}) must score >= "
                f"age {ages[i + 1]} days ({scores[i + 1]:.4f})",
            )

    def test_new_content_scores_higher_than_two_year_old(self):
        """Brand-new content must strictly outrank 2-year-old content."""
        self.assertGreater(self._score_for_age(0), self._score_for_age(730))

    def test_one_year_old_scores_higher_than_two_year_old(self):
        """1-year-old content must score strictly above 2-year-old content."""
        self.assertGreater(self._score_for_age(365), self._score_for_age(730))

    def test_content_older_than_two_years_scores_same_as_two_year_old(self):
        """Content >2 years old gets no freshness bonus — scores equal to 730-day content."""
        self.assertAlmostEqual(
            self._score_for_age(730), self._score_for_age(1000), places=2,
            msg="Content older than 2 years must score the same as 2-year-old content",
        )


if __name__ == "__main__":
    unittest.main()
