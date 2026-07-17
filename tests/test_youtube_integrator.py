"""
Unit tests for youtube_integrator — pure-logic helpers (no external network).

Tests cover:
  - extract_video_id  (URL parsing)
  - extract_playlist_id
  - extract_channel_id
  - _parse_duration   (ISO 8601 → seconds, including the P1DT... fix)
  - _check_rate_limit / get_quota_status
  - YouTubeVideo.to_dict / from_dict  (serialisation round-trip)
"""
import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

# Stub optional heavy dependencies before import so the module loads cleanly.
import types
for _dep in ("youtube_transcript_api", "yt_dlp", "googleapiclient",
             "googleapiclient.discovery", "googleapiclient.errors"):
    if _dep not in sys.modules:
        sys.modules[_dep] = types.ModuleType(_dep)

from youtube_integrator import (  # noqa: E402
    YouTubeVideo,
    YouTubeChannel,
    YouTubePlaylist,
    YouTubeIntegrator,
)


def _make_integrator(**kwargs):
    """Create a YouTubeIntegrator without hitting filesystem or network."""
    with patch("youtube_integrator.Path.mkdir"), \
         patch("youtube_integrator.LoggingManager") as mock_lm, \
         patch("youtube_integrator.CacheManager") as mock_cm:
        mock_lm.get_logger.return_value = MagicMock()
        mock_cm.return_value = MagicMock()
        return YouTubeIntegrator(**kwargs)


# ---------------------------------------------------------------------------
# YouTubeVideo serialisation
# ---------------------------------------------------------------------------

class YouTubeVideoSerialiseTests(unittest.TestCase):
    def _make(self):
        return YouTubeVideo(
            video_id="dQw4w9WgXcY",
            title="Test",
            description="desc",
            channel_title="Channel",
            channel_id="UC123",
            published_at=datetime(2024, 1, 15, 10, 30, 0),
            duration=3600,
            view_count=1000,
            like_count=100,
            comment_count=50,
            tags=["music", "pop"],
            category_id="10",
            thumbnail_url="https://example.com/thumb.jpg",
        )

    def test_to_dict_published_at_is_string(self):
        v = self._make()
        d = v.to_dict()
        self.assertIsInstance(d["published_at"], str)

    def test_to_dict_contains_all_fields(self):
        v = self._make()
        d = v.to_dict()
        self.assertIn("video_id", d)
        self.assertIn("title", d)
        self.assertIn("duration", d)

    def test_from_dict_restores_datetime(self):
        v = self._make()
        d = v.to_dict()
        v2 = YouTubeVideo.from_dict(d)
        self.assertIsInstance(v2.published_at, datetime)

    def test_round_trip_preserves_values(self):
        v = self._make()
        v2 = YouTubeVideo.from_dict(v.to_dict())
        self.assertEqual(v2.video_id, v.video_id)
        self.assertEqual(v2.title, v.title)
        self.assertEqual(v2.duration, v.duration)
        self.assertEqual(v2.published_at, v.published_at)

    def test_from_dict_with_datetime_object_passthrough(self):
        """If published_at is already a datetime (not a string), it stays."""
        v = self._make()
        d = v.to_dict()
        d["published_at"] = v.published_at  # datetime, not str
        v2 = YouTubeVideo.from_dict(d)
        self.assertEqual(v2.published_at, v.published_at)


# ---------------------------------------------------------------------------
# extract_video_id
# ---------------------------------------------------------------------------

class ExtractVideoIdTests(unittest.TestCase):
    def setUp(self):
        self.yi = _make_integrator()

    def test_standard_watch_url(self):
        self.assertEqual(
            self.yi.extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcY"),
            "dQw4w9WgXcY"
        )

    def test_short_url(self):
        self.assertEqual(
            self.yi.extract_video_id("https://youtu.be/dQw4w9WgXcY"),
            "dQw4w9WgXcY"
        )

    def test_embed_url(self):
        self.assertEqual(
            self.yi.extract_video_id("https://www.youtube.com/embed/dQw4w9WgXcY"),
            "dQw4w9WgXcY"
        )

    def test_mobile_url(self):
        self.assertEqual(
            self.yi.extract_video_id("https://m.youtube.com/watch?v=dQw4w9WgXcY"),
            "dQw4w9WgXcY"
        )

    def test_url_with_extra_params(self):
        self.assertEqual(
            self.yi.extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcY&t=120"),
            "dQw4w9WgXcY"
        )

    def test_direct_video_id(self):
        self.assertEqual(
            self.yi.extract_video_id("dQw4w9WgXcY"),
            "dQw4w9WgXcY"
        )

    def test_shorts_url(self):
        """YouTube Shorts URLs must extract the video ID."""
        self.assertEqual(
            self.yi.extract_video_id("https://www.youtube.com/shorts/dQw4w9WgXcY"),
            "dQw4w9WgXcY"
        )

    def test_invalid_url_returns_none(self):
        self.assertIsNone(self.yi.extract_video_id("https://example.com/not-youtube"))

    def test_empty_string_returns_none(self):
        self.assertIsNone(self.yi.extract_video_id(""))

    def test_playlist_url_returns_none(self):
        # Playlist-only URL has no video ID
        self.assertIsNone(
            self.yi.extract_video_id("https://www.youtube.com/playlist?list=PLxxxxxxxx")
        )

    def test_short_id_not_mistaken(self):
        """10-char string must not be treated as a video ID (IDs are 11 chars)."""
        self.assertIsNone(self.yi.extract_video_id("dQw4w9WgXc"))  # 10 chars


# ---------------------------------------------------------------------------
# extract_playlist_id
# ---------------------------------------------------------------------------

class ExtractPlaylistIdTests(unittest.TestCase):
    def setUp(self):
        self.yi = _make_integrator()

    def test_playlist_url(self):
        result = self.yi.extract_playlist_id(
            "https://www.youtube.com/playlist?list=PL1234567890abcdefgh"
        )
        self.assertEqual(result, "PL1234567890abcdefgh")

    def test_watch_url_with_list(self):
        result = self.yi.extract_playlist_id(
            "https://www.youtube.com/watch?v=dQw4w9WgXcY&list=PLxxxxxxxx"
        )
        self.assertEqual(result, "PLxxxxxxxx")

    def test_no_list_returns_none(self):
        self.assertIsNone(
            self.yi.extract_playlist_id("https://www.youtube.com/watch?v=dQw4w9WgXcY")
        )

    def test_empty_string_returns_none(self):
        self.assertIsNone(self.yi.extract_playlist_id(""))


# ---------------------------------------------------------------------------
# extract_channel_id
# ---------------------------------------------------------------------------

class ExtractChannelIdTests(unittest.TestCase):
    def setUp(self):
        self.yi = _make_integrator()

    def test_channel_url(self):
        result = self.yi.extract_channel_id(
            "https://www.youtube.com/channel/UCxxxxxxxxxxxxxxxxxxxxxx"
        )
        self.assertEqual(result, "UCxxxxxxxxxxxxxxxxxxxxxx")

    def test_handle_url(self):
        result = self.yi.extract_channel_id("https://www.youtube.com/@channelname")
        self.assertEqual(result, "channelname")

    def test_handle_with_dot(self):
        result = self.yi.extract_channel_id("https://www.youtube.com/@channel.name")
        self.assertEqual(result, "channel.name")

    def test_no_channel_returns_none(self):
        self.assertIsNone(
            self.yi.extract_channel_id("https://www.youtube.com/watch?v=dQw4w9WgXcY")
        )

    def test_empty_string_returns_none(self):
        self.assertIsNone(self.yi.extract_channel_id(""))


# ---------------------------------------------------------------------------
# _parse_duration — ISO 8601
# ---------------------------------------------------------------------------

class ParseDurationTests(unittest.TestCase):
    def setUp(self):
        self.yi = _make_integrator()

    def test_hours_minutes_seconds(self):
        self.assertEqual(self.yi._parse_duration("PT1H2M3S"), 3723)

    def test_minutes_seconds(self):
        self.assertEqual(self.yi._parse_duration("PT5M30S"), 330)

    def test_seconds_only(self):
        self.assertEqual(self.yi._parse_duration("PT30S"), 30)

    def test_hours_only(self):
        self.assertEqual(self.yi._parse_duration("PT1H"), 3600)

    def test_minutes_only(self):
        self.assertEqual(self.yi._parse_duration("PT2M"), 120)

    def test_zero_duration(self):
        self.assertEqual(self.yi._parse_duration("PT0S"), 0)

    def test_empty_pt_returns_zero(self):
        self.assertEqual(self.yi._parse_duration("PT"), 0)

    def test_invalid_string_returns_zero(self):
        self.assertEqual(self.yi._parse_duration("INVALID"), 0)

    def test_days_component_regression(self):
        """P1DT2H format (videos >24h) must not return 0.

        The old pattern r'PT...' required 'PT' at the start and silently
        returned 0 for any duration with a day component (P1DT...).
        Fixed by handling the optional day group: P(?:Nd)?T...
        """
        # 1 day + 2 hours = 93600 seconds
        self.assertEqual(self.yi._parse_duration("P1DT2H"), 93600)

    def test_days_hours_minutes_seconds(self):
        # 1 day + 0 hours + 30 min + 0 sec = 88200 s
        self.assertEqual(self.yi._parse_duration("P1DT0H30M0S"), 88200)

    def test_days_only_no_time(self):
        # P1D (no T component) — not a real YouTube format but robust handling
        # re.match(r'P(?:(\d+)D)?T...') will fail for 'P1D' (no T) → returns 0
        # This is acceptable: YouTube always includes T.
        self.assertEqual(self.yi._parse_duration("P1D"), 0)

    def test_large_duration(self):
        # 99H59M59S
        self.assertEqual(self.yi._parse_duration("PT99H59M59S"),
                         99 * 3600 + 59 * 60 + 59)


# ---------------------------------------------------------------------------
# _check_rate_limit / get_quota_status
# ---------------------------------------------------------------------------

class RateLimitTests(unittest.TestCase):
    def setUp(self):
        self.yi = _make_integrator(rate_limit_per_day=10)

    def test_first_call_within_limit(self):
        self.assertTrue(self.yi._check_rate_limit(1))
        self.assertEqual(self.yi.quota_usage, 1)

    def test_accumulates_quota(self):
        self.yi._check_rate_limit(3)
        self.yi._check_rate_limit(4)
        self.assertEqual(self.yi.quota_usage, 7)

    def test_exceeds_limit_returns_false(self):
        self.yi._check_rate_limit(9)
        # 9 used, limit 10 → need 2 more would exceed
        result = self.yi._check_rate_limit(2)
        self.assertFalse(result)
        # usage must NOT have been incremented
        self.assertEqual(self.yi.quota_usage, 9)

    def test_exactly_at_limit_returns_false(self):
        self.yi._check_rate_limit(10)
        # exactly at limit, any more should be false
        result = self.yi._check_rate_limit(1)
        self.assertFalse(result)

    def test_quota_resets_after_day(self):
        self.yi._check_rate_limit(8)
        # Force the reset time into the past
        self.yi.request_reset_time = datetime.now() - timedelta(seconds=1)
        # Next call should reset usage
        result = self.yi._check_rate_limit(1)
        self.assertTrue(result)
        self.assertEqual(self.yi.quota_usage, 1)

    def test_get_quota_status_remaining(self):
        self.yi._check_rate_limit(3)
        s = self.yi.get_quota_status()
        self.assertEqual(s["used"], 3)
        self.assertEqual(s["remaining"], 7)
        self.assertEqual(s["limit"], 10)

    def test_get_quota_status_reset_in_non_negative(self):
        s = self.yi.get_quota_status()
        self.assertGreaterEqual(s["reset_in_seconds"], 0)

    def test_get_quota_status_includes_reset_time(self):
        s = self.yi.get_quota_status()
        self.assertIn("reset_time", s)
        self.assertIsInstance(s["reset_time"], str)


class BatchGetVideosOrderTests(unittest.TestCase):
    """Regression: batch_get_videos appended cached videos AFTER freshly-fetched
    ones, scrambling the caller-supplied order.

    Root cause: uncached videos were appended inside the try block, then
    ``videos.extend(cached_videos)`` ran after it, so the output was always
    [uncached..., cached...] instead of the original input order.

    Fix: collect both cached and fetched results into a {vid_id: video} dict
    for each batch, then append in the original input order.
    """

    def _make_video(self, vid_id):
        return YouTubeVideo(
            video_id=vid_id,
            title=f"Title {vid_id}",
            description="",
            channel_title="Ch",
            channel_id="UC0",
            published_at=datetime(2024, 1, 1),
            duration=60,
            view_count=0,
            like_count=0,
            comment_count=0,
            tags=[],
            category_id="1",
            thumbnail_url="",
        )

    def _make_integrator_with_service(self):
        yi = _make_integrator()
        yi.youtube_service = MagicMock()
        yi._check_rate_limit = MagicMock(return_value=True)
        yi.logger = MagicMock()
        return yi

    def test_cached_then_uncached_then_cached_preserves_order(self):
        """[A(cached), B(uncached), C(cached)] must return [A, B, C]."""
        yi = self._make_integrator_with_service()

        vid_a = self._make_video("A")
        vid_b = self._make_video("B")
        vid_c = self._make_video("C")

        def fake_cache_get(key):
            if "A_" in key or key.endswith("A_False"):
                return vid_a.to_dict()
            if "C_" in key or key.endswith("C_False"):
                return vid_c.to_dict()
            return None

        yi.cache_manager.get.side_effect = fake_cache_get
        yi.cache_manager.set = MagicMock()

        # Simulate batch API returning only B
        mock_item_b = {"id": "B", "snippet": {}, "contentDetails": {}, "statistics": {}}
        yi.youtube_service.videos.return_value.list.return_value.execute.return_value = {
            "items": [mock_item_b]
        }
        yi._parse_video_item = MagicMock(return_value=vid_b)

        result = yi.batch_get_videos(["A", "B", "C"])

        ids = [v.video_id for v in result]
        self.assertEqual(ids, ["A", "B", "C"],
            f"Order must match input ['A','B','C'], got {ids} "
            f"(old bug: uncached B came first → ['B','A','C'])")

    def test_all_cached_preserves_order(self):
        """All-cached batch must also preserve the original order."""
        yi = self._make_integrator_with_service()

        vids = {vid_id: self._make_video(vid_id) for vid_id in ["X", "Y", "Z"]}

        def fake_cache_get(key):
            for vid_id, vid in vids.items():
                if f"_{vid_id}_" in key or key.endswith(f"_{vid_id}_False"):
                    return vid.to_dict()
            return None

        yi.cache_manager.get.side_effect = fake_cache_get
        yi._check_rate_limit = MagicMock(return_value=False)

        result = yi.batch_get_videos(["X", "Y", "Z"])
        ids = [v.video_id for v in result]
        self.assertEqual(ids, ["X", "Y", "Z"],
            f"All-cached order must be ['X','Y','Z'], got {ids}")

    def test_no_cache_hits_order_still_correct(self):
        """No-cache path: returned order must match the API response order mapped
        back to the input order — not the API response order."""
        yi = self._make_integrator_with_service()

        vid_p = self._make_video("P")
        vid_q = self._make_video("Q")

        yi.cache_manager.get.return_value = None

        parse_calls = []

        def fake_parse(item):
            vid_id = item.get("id")
            parse_calls.append(vid_id)
            return self._make_video(vid_id)

        yi._parse_video_item = fake_parse
        yi.youtube_service.videos.return_value.list.return_value.execute.return_value = {
            "items": [{"id": "Q"}, {"id": "P"}]  # reversed from input
        }
        yi.cache_manager.set = MagicMock()

        result = yi.batch_get_videos(["P", "Q"])
        ids = [v.video_id for v in result]
        self.assertEqual(ids, ["P", "Q"],
            f"Output must follow input order ['P','Q'], got {ids} "
            f"(API returned Q before P but input order must be preserved)")


if __name__ == "__main__":
    unittest.main()
