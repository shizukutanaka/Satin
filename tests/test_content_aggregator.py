"""
Unit tests for content_aggregator — relevance scoring and data model.

ContentAggregator.calculate_relevance_score is pure computation:
no network calls, no external deps.
"""
import math
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


if __name__ == "__main__":
    unittest.main()
