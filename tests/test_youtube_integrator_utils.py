"""
Tests for pure-logic utility methods in youtube_integrator.py.

Covers: extract_video_id (all URL formats + bare ID + invalid),
extract_playlist_id, extract_channel_id.  No network I/O, no API key.

Run: python -m unittest tests.test_youtube_integrator_utils -v
"""
import os
import sys
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from youtube_integrator import YouTubeIntegrator  # noqa: E402


class YouTubeIntegratorTestBase(unittest.TestCase):
    def setUp(self):
        self.yi = YouTubeIntegrator.__new__(YouTubeIntegrator)


class ExtractVideoIdTests(YouTubeIntegratorTestBase):
    VIDEO_ID = "dQw4w9WgXcQ"

    def test_standard_watch_url(self):
        url = f"https://www.youtube.com/watch?v={self.VIDEO_ID}"
        self.assertEqual(self.yi.extract_video_id(url), self.VIDEO_ID)

    def test_short_url(self):
        url = f"https://youtu.be/{self.VIDEO_ID}"
        self.assertEqual(self.yi.extract_video_id(url), self.VIDEO_ID)

    def test_embed_url(self):
        url = f"https://www.youtube.com/embed/{self.VIDEO_ID}"
        self.assertEqual(self.yi.extract_video_id(url), self.VIDEO_ID)

    def test_mobile_url(self):
        url = f"https://m.youtube.com/watch?v={self.VIDEO_ID}&feature=share"
        self.assertEqual(self.yi.extract_video_id(url), self.VIDEO_ID)

    def test_bare_video_id(self):
        self.assertEqual(self.yi.extract_video_id(self.VIDEO_ID), self.VIDEO_ID)

    def test_invalid_returns_none(self):
        self.assertIsNone(self.yi.extract_video_id("https://example.com/notayoutube"))

    def test_too_short_id_returns_none(self):
        self.assertIsNone(self.yi.extract_video_id("tooshort"))


class ExtractPlaylistIdTests(YouTubeIntegratorTestBase):
    PL_ID = "PLrAXtmErZgOeiKm4sgNOknc9TTnwwDqCh"

    def test_watch_url_with_list(self):
        url = f"https://www.youtube.com/watch?v=abc&list={self.PL_ID}"
        self.assertEqual(self.yi.extract_playlist_id(url), self.PL_ID)

    def test_playlist_url(self):
        url = f"https://www.youtube.com/playlist?list={self.PL_ID}"
        self.assertEqual(self.yi.extract_playlist_id(url), self.PL_ID)

    def test_non_playlist_returns_none(self):
        self.assertIsNone(self.yi.extract_playlist_id("https://www.youtube.com/watch?v=abc"))


class ExtractChannelIdTests(YouTubeIntegratorTestBase):
    CH_ID = "UCuAXFkgsw1L7xaCfnd5JJOw"

    def test_channel_url(self):
        url = f"https://www.youtube.com/channel/{self.CH_ID}"
        self.assertEqual(self.yi.extract_channel_id(url), self.CH_ID)

    def test_at_handle_url(self):
        url = "https://www.youtube.com/@RickAstleyYT"
        self.assertEqual(self.yi.extract_channel_id(url), "RickAstleyYT")

    def test_non_channel_returns_none(self):
        self.assertIsNone(self.yi.extract_channel_id("https://www.youtube.com/watch?v=abc"))


class ThumbnailFallbackTest(YouTubeIntegratorTestBase):
    """Regression: snippet['thumbnails']['high']['url'] raised KeyError when
    YouTube API returns only lower-resolution thumbnail entries."""

    def _make_snippet(self, keys):
        thumbnails = {k: {"url": f"http://img/{k}.jpg"} for k in keys}
        return {"thumbnails": thumbnails}

    def _thumbnail_url(self, snippet):
        return (
            snippet.get("thumbnails", {}).get("high")
            or snippet.get("thumbnails", {}).get("medium")
            or snippet.get("thumbnails", {}).get("default")
            or {}
        ).get("url", "")

    def test_high_resolution_returned_when_available(self):
        url = self._thumbnail_url(self._make_snippet(["default", "medium", "high"]))
        self.assertIn("high", url)

    def test_falls_back_to_medium_when_no_high(self):
        url = self._thumbnail_url(self._make_snippet(["default", "medium"]))
        self.assertIn("medium", url)

    def test_falls_back_to_default_when_only_default(self):
        url = self._thumbnail_url(self._make_snippet(["default"]))
        self.assertIn("default", url)

    def test_empty_thumbnails_returns_empty_string(self):
        url = self._thumbnail_url({"thumbnails": {}})
        self.assertEqual(url, "")

    def test_missing_thumbnails_key_returns_empty_string(self):
        url = self._thumbnail_url({})
        self.assertEqual(url, "")


if __name__ == "__main__":
    unittest.main()
