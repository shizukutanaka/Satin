"""
Regression tests: cached data-model deserialization must restore datetime
fields, not leave them as ISO strings.

Bug: to_dict() serialized datetime -> ISO string, but the cache-read path did
WebPage(**cached) / YouTubeVideo(**cached), so a cache hit produced objects
whose date fields were strings. Consumers calling e.g. .year then raised
AttributeError/TypeError. from_dict() now round-trips them back to datetime.

Run: python -m unittest tests.test_cache_datetime_roundtrip -v
"""
import os
import sys
import unittest
from datetime import datetime

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from web_integrator import WebPage  # noqa: E402
from youtube_integrator import YouTubeVideo  # noqa: E402


class WebPageRoundTripTests(unittest.TestCase):
    def _make(self):
        return WebPage(
            url="https://example.com",
            title="t", content="c", html="<p>", extracted_text="c",
            published_date=datetime(2024, 1, 2, 3, 4, 5),
            fetch_time=datetime(2024, 6, 7, 8, 9, 10),
        )

    def test_fetch_time_restored_to_datetime(self):
        page = WebPage.from_dict(self._make().to_dict())
        self.assertIsInstance(page.fetch_time, datetime)
        self.assertEqual(page.fetch_time.year, 2024)

    def test_published_date_restored_to_datetime(self):
        page = WebPage.from_dict(self._make().to_dict())
        self.assertIsInstance(page.published_date, datetime)
        # The whole point: .year must not raise.
        self.assertEqual(page.published_date.year, 2024)

    def test_roundtrip_value_equality(self):
        original = self._make()
        restored = WebPage.from_dict(original.to_dict())
        self.assertEqual(restored.published_date, original.published_date)
        self.assertEqual(restored.fetch_time, original.fetch_time)

    def test_none_published_date_preserved(self):
        page = WebPage(url="u", title="t", content="c", html="h",
                       extracted_text="c", published_date=None)
        restored = WebPage.from_dict(page.to_dict())
        self.assertIsNone(restored.published_date)


class YouTubeVideoRoundTripTests(unittest.TestCase):
    def _make(self):
        return YouTubeVideo(
            video_id="abc", title="t", description="d",
            channel_title="ct", channel_id="cid",
            published_at=datetime(2023, 5, 6, 7, 8, 9),
            duration=120, view_count=1, like_count=2, comment_count=3,
            tags=["a"], category_id="22", thumbnail_url="http://x/y.jpg",
        )

    def test_published_at_restored_to_datetime(self):
        video = YouTubeVideo.from_dict(self._make().to_dict())
        self.assertIsInstance(video.published_at, datetime)
        self.assertEqual(video.published_at.year, 2023)

    def test_roundtrip_value_equality(self):
        original = self._make()
        restored = YouTubeVideo.from_dict(original.to_dict())
        self.assertEqual(restored.published_at, original.published_at)
        self.assertEqual(restored.video_id, original.video_id)
        self.assertEqual(restored.tags, original.tags)


if __name__ == "__main__":
    unittest.main()
