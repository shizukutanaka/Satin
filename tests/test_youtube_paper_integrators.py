"""
Stdlib-only tests for main/youtube_integrator.py and main/paper_integrator.py.

Only pure-Python logic is exercised (URL parsing, dataclass round-trips, quota
tracking, no-dep guards). Network/API calls are not made.

Run: python -m unittest tests.test_youtube_paper_integrators -v
"""
import os
import sys
import unittest
from datetime import datetime

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from youtube_integrator import (  # noqa: E402
    YouTubeIntegrator, YouTubeVideo, YouTubeChannel, YouTubePlaylist,
    TRANSCRIPT_AVAILABLE, YT_DLP_AVAILABLE, YOUTUBE_API_AVAILABLE,
)
from paper_integrator import AcademicPaper, PaperIntegrator  # noqa: E402


# ---------------------------------------------------------------------------
# YouTubeVideo dataclass
# ---------------------------------------------------------------------------

def _make_video(**overrides):
    defaults = dict(
        video_id="dQw4w9WgXcQ",
        title="Test Video",
        description="A test video",
        channel_title="Test Channel",
        channel_id="UC_test",
        published_at=datetime(2024, 1, 15, 10, 0, 0),
        duration=212,
        view_count=1_000_000,
        like_count=50_000,
        comment_count=3_000,
        tags=["music", "test"],
        category_id="10",
        thumbnail_url="https://i.ytimg.com/vi/dQw4w9WgXcQ/default.jpg",
    )
    defaults.update(overrides)
    return YouTubeVideo(**defaults)


class YouTubeVideoTests(unittest.TestCase):
    def test_to_dict_has_video_id(self):
        v = _make_video()
        d = v.to_dict()
        self.assertEqual(d["video_id"], "dQw4w9WgXcQ")

    def test_to_dict_published_at_is_iso_string(self):
        v = _make_video()
        d = v.to_dict()
        self.assertIsInstance(d["published_at"], str)
        self.assertIn("2024", d["published_at"])

    def test_from_dict_round_trip(self):
        original = _make_video()
        d = original.to_dict()
        restored = YouTubeVideo.from_dict(d)
        self.assertEqual(restored.video_id, original.video_id)
        self.assertIsInstance(restored.published_at, datetime)

    def test_from_dict_restores_published_at_datetime(self):
        v = _make_video()
        d = v.to_dict()
        restored = YouTubeVideo.from_dict(d)
        self.assertEqual(restored.published_at.year, 2024)

    def test_default_transcript_is_none(self):
        v = _make_video()
        self.assertIsNone(v.transcript)

    def test_default_language_is_ja(self):
        v = _make_video()
        self.assertEqual(v.language, "ja")


# ---------------------------------------------------------------------------
# YouTubeIntegrator — extract_* helpers (no API needed)
# ---------------------------------------------------------------------------

class YouTubeIntegratorExtractTests(unittest.TestCase):
    def setUp(self):
        self.yt = YouTubeIntegrator()  # no api_key → no API init

    def tearDown(self):
        # Shut down internal CacheManager to avoid ResourceWarning
        try:
            self.yt.cache_manager.shutdown(wait=False)
        except Exception:
            pass

    # video ID extraction
    def test_extract_video_id_watch_url(self):
        vid = self.yt.extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertEqual(vid, "dQw4w9WgXcQ")

    def test_extract_video_id_youtu_be(self):
        vid = self.yt.extract_video_id("https://youtu.be/dQw4w9WgXcQ")
        self.assertEqual(vid, "dQw4w9WgXcQ")

    def test_extract_video_id_embed(self):
        vid = self.yt.extract_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ")
        self.assertEqual(vid, "dQw4w9WgXcQ")

    def test_extract_video_id_direct_id(self):
        vid = self.yt.extract_video_id("dQw4w9WgXcQ")
        self.assertEqual(vid, "dQw4w9WgXcQ")

    def test_extract_video_id_invalid_returns_none(self):
        vid = self.yt.extract_video_id("https://www.google.com")
        self.assertIsNone(vid)

    def test_extract_video_id_mobile_url(self):
        vid = self.yt.extract_video_id("https://m.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertEqual(vid, "dQw4w9WgXcQ")

    # playlist ID extraction
    def test_extract_playlist_id(self):
        pid = self.yt.extract_playlist_id(
            "https://www.youtube.com/playlist?list=PLtest123"
        )
        self.assertEqual(pid, "PLtest123")

    def test_extract_playlist_id_in_watch_url(self):
        pid = self.yt.extract_playlist_id(
            "https://www.youtube.com/watch?v=abc&list=PLtest456"
        )
        self.assertEqual(pid, "PLtest456")

    def test_extract_playlist_id_no_list_returns_none(self):
        pid = self.yt.extract_playlist_id("https://www.youtube.com/watch?v=abc")
        self.assertIsNone(pid)

    # channel ID extraction
    def test_extract_channel_id_channel_url(self):
        cid = self.yt.extract_channel_id(
            "https://www.youtube.com/channel/UCtest123"
        )
        self.assertEqual(cid, "UCtest123")

    def test_extract_channel_id_at_handle(self):
        cid = self.yt.extract_channel_id("https://www.youtube.com/@TestUser")
        self.assertEqual(cid, "TestUser")

    def test_extract_channel_id_no_match_returns_none(self):
        cid = self.yt.extract_channel_id("https://www.google.com")
        self.assertIsNone(cid)


class YouTubeIntegratorQuotaTests(unittest.TestCase):
    def setUp(self):
        self.yt = YouTubeIntegrator(rate_limit_per_day=100)

    def tearDown(self):
        try:
            self.yt.cache_manager.shutdown(wait=False)
        except Exception:
            pass

    def test_get_quota_status_has_expected_keys(self):
        status = self.yt.get_quota_status()
        for key in ("used", "limit", "remaining", "reset_in_seconds"):
            self.assertIn(key, status)

    def test_initial_quota_used_is_zero(self):
        status = self.yt.get_quota_status()
        self.assertEqual(status["used"], 0)

    def test_rate_limit_check_returns_true_within_limit(self):
        result = self.yt._check_rate_limit(quota_cost=1)
        self.assertTrue(result)
        self.assertEqual(self.yt.quota_usage, 1)

    def test_rate_limit_check_returns_false_when_exceeded(self):
        self.yt.quota_usage = 100  # exhaust limit
        result = self.yt._check_rate_limit(quota_cost=1)
        self.assertFalse(result)

    def test_backend_flags_are_bool(self):
        self.assertIsInstance(TRANSCRIPT_AVAILABLE, bool)
        self.assertIsInstance(YT_DLP_AVAILABLE, bool)
        self.assertIsInstance(YOUTUBE_API_AVAILABLE, bool)


# ---------------------------------------------------------------------------
# AcademicPaper dataclass
# ---------------------------------------------------------------------------

class AcademicPaperTests(unittest.TestCase):
    def _make_paper(self):
        return AcademicPaper(
            paper_id="arxiv:2401.00001",
            title="Test Paper",
            abstract="An abstract.",
            authors=["Alice", "Bob"],
            published_date=datetime(2024, 1, 1),
            url="https://arxiv.org/abs/2401.00001",
            source="arxiv",
        )

    def test_to_dict_has_expected_keys(self):
        paper = self._make_paper()
        d = paper.to_dict()
        for key in ("paper_id", "title", "abstract", "authors", "source"):
            self.assertIn(key, d)

    def test_to_dict_published_date_is_iso_string(self):
        paper = self._make_paper()
        d = paper.to_dict()
        self.assertIsInstance(d["published_date"], str)
        self.assertIn("2024", d["published_date"])

    def test_default_citations_zero(self):
        paper = self._make_paper()
        self.assertEqual(paper.citations, 0)

    def test_default_keywords_empty_list(self):
        paper = self._make_paper()
        self.assertEqual(paper.keywords, [])

    def test_source_stored(self):
        paper = self._make_paper()
        self.assertEqual(paper.source, "arxiv")


class PaperIntegratorNoDepTests(unittest.TestCase):
    def test_search_arxiv_without_dep_returns_empty(self):
        from paper_integrator import _arxiv_lib
        if _arxiv_lib is not None:
            self.skipTest("arxiv installed — no-dep path not taken")
        pi = PaperIntegrator()
        result = pi.search_arxiv("machine learning")
        self.assertEqual(result, [])

    def test_instantiation_does_not_raise(self):
        pi = PaperIntegrator()
        self.assertIsNotNone(pi)


if __name__ == "__main__":
    unittest.main()
