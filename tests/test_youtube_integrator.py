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


if __name__ == "__main__":
    unittest.main()
