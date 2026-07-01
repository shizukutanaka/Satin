"""
Stdlib-only tests for main/web_integrator.py.

Only pure-Python logic is exercised (URL normalization, hash generation,
WebPage dataclass, search_text_in_page, export_page_data).
No network calls are made.

Run: python -m unittest tests.test_web_integrator -v
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from web_integrator import (  # noqa: E402
    WebIntegrator, WebPage, SitemapEntry,
    REQUESTS_AVAILABLE, BS4_AVAILABLE,
)


def _make_page(**overrides):
    defaults = dict(
        url="https://example.com/page",
        title="Test Page",
        content="Hello world. This is a test page.",
        html="<html><body>Hello world.</body></html>",
        extracted_text="Hello world.",
    )
    defaults.update(overrides)
    return WebPage(**defaults)


# ---------------------------------------------------------------------------
# WebPage dataclass
# ---------------------------------------------------------------------------

class WebPageTests(unittest.TestCase):
    def test_defaults_filled_by_post_init(self):
        page = _make_page()
        self.assertEqual(page.keywords, [])
        self.assertEqual(page.images, [])
        self.assertEqual(page.links, [])
        self.assertEqual(page.metadata, {})
        self.assertIsInstance(page.fetch_time, datetime)

    def test_to_dict_has_expected_keys(self):
        page = _make_page()
        d = page.to_dict()
        for key in ("url", "title", "content", "html", "fetch_time"):
            self.assertIn(key, d)

    def test_to_dict_fetch_time_is_iso_string(self):
        page = _make_page()
        d = page.to_dict()
        self.assertIsInstance(d["fetch_time"], str)

    def test_from_dict_round_trip(self):
        original = _make_page()
        d = original.to_dict()
        restored = WebPage.from_dict(d)
        self.assertEqual(restored.url, original.url)
        self.assertIsInstance(restored.fetch_time, datetime)

    def test_from_dict_restores_published_date(self):
        page = _make_page(published_date=datetime(2024, 6, 1))
        d = page.to_dict()
        restored = WebPage.from_dict(d)
        self.assertIsInstance(restored.published_date, datetime)
        self.assertEqual(restored.published_date.year, 2024)

    def test_from_dict_no_published_date(self):
        page = _make_page()  # published_date=None
        d = page.to_dict()
        restored = WebPage.from_dict(d)
        self.assertIsNone(restored.published_date)

    def test_default_language_is_ja(self):
        page = _make_page()
        self.assertEqual(page.language, "ja")


# ---------------------------------------------------------------------------
# SitemapEntry dataclass
# ---------------------------------------------------------------------------

class SitemapEntryTests(unittest.TestCase):
    def test_url_stored(self):
        entry = SitemapEntry(url="https://example.com/")
        self.assertEqual(entry.url, "https://example.com/")

    def test_optional_fields_default_none(self):
        entry = SitemapEntry(url="https://example.com/")
        self.assertIsNone(entry.lastmod)
        self.assertIsNone(entry.changefreq)
        self.assertIsNone(entry.priority)


# ---------------------------------------------------------------------------
# WebIntegrator utility methods (no network)
# ---------------------------------------------------------------------------

class WebIntegratorHashTests(unittest.TestCase):
    def setUp(self):
        self.wi = WebIntegrator()

    def tearDown(self):
        try:
            self.wi.cache_manager.shutdown(wait=False)
        except Exception:
            pass

    def test_generate_url_hash_returns_string(self):
        h = self.wi.generate_url_hash("https://example.com")
        self.assertIsInstance(h, str)

    def test_generate_url_hash_length_16(self):
        h = self.wi.generate_url_hash("https://example.com")
        self.assertEqual(len(h), 16)

    def test_generate_url_hash_same_url_is_stable(self):
        h1 = self.wi.generate_url_hash("https://example.com/page")
        h2 = self.wi.generate_url_hash("https://example.com/page")
        self.assertEqual(h1, h2)

    def test_generate_url_hash_different_urls_differ(self):
        h1 = self.wi.generate_url_hash("https://example.com/a")
        h2 = self.wi.generate_url_hash("https://example.com/b")
        self.assertNotEqual(h1, h2)


class WebIntegratorNormalizeUrlTests(unittest.TestCase):
    def setUp(self):
        self.wi = WebIntegrator()

    def tearDown(self):
        try:
            self.wi.cache_manager.shutdown(wait=False)
        except Exception:
            pass

    def test_removes_fragment(self):
        url = self.wi.normalize_url("https://example.com/page#section")
        self.assertNotIn("#", url)

    def test_sorts_query_params(self):
        url = self.wi.normalize_url("https://example.com/page?b=2&a=1")
        self.assertIn("a=1", url)
        a_pos = url.index("a=1")
        b_pos = url.index("b=2")
        self.assertLess(a_pos, b_pos)

    def test_trailing_slash_removed(self):
        url = self.wi.normalize_url("https://example.com/page/")
        self.assertFalse(url.endswith("/"))

    def test_host_lowercased(self):
        url = self.wi.normalize_url("https://EXAMPLE.COM/page")
        self.assertIn("example.com", url)

    def test_no_query_stays_clean(self):
        url = self.wi.normalize_url("https://example.com/page")
        self.assertEqual(url, "https://example.com/page")

    def test_root_with_slash_equals_root_without_slash(self):
        """Regression: 'https://example.com/' and 'https://example.com' used to
        normalise to different strings ('https://example.com/' vs 'https://example.com')
        because the root path '/' was special-cased to be kept as-is.

        Fix: strip trailing slashes uniformly, so both inputs yield the same
        normalised URL and batch_fetch_pages de-duplication works correctly.
        """
        a = self.wi.normalize_url("https://example.com")
        b = self.wi.normalize_url("https://example.com/")
        self.assertEqual(a, b,
            "Root URL with and without trailing slash must normalise identically.")

    def test_http_and_https_root_both_normalise_to_https(self):
        """http:// root and https:// root must both normalise to the same string."""
        a = self.wi.normalize_url("http://example.com/")
        b = self.wi.normalize_url("https://example.com")
        self.assertEqual(a, b)

    def test_dedup_works_for_root_with_and_without_slash(self):
        """batch_fetch_pages de-duplication must treat root with/without slash as the same URL."""
        wi = self.wi
        # Feed both forms of the root URL and a known different URL
        # We don't make real requests; just check the de-duplication logic via normalize_url.
        urls = [
            "https://example.com/",
            "https://example.com",   # duplicate of the above after normalisation
            "https://example.com/page",
        ]
        seen: set = set()
        unique: list = []
        for url in urls:
            n = wi.normalize_url(url)
            if n not in seen:
                seen.add(n)
                unique.append(n)
        self.assertEqual(len(unique), 2,
            "The two root URL forms must be treated as one unique URL, "
            "leaving exactly 2 unique URLs total.")


class WebIntegratorSearchTests(unittest.TestCase):
    def setUp(self):
        self.wi = WebIntegrator()

    def tearDown(self):
        try:
            self.wi.cache_manager.shutdown(wait=False)
        except Exception:
            pass

    def test_search_text_finds_match(self):
        page = _make_page(content="Error: database connection failed")
        matches = self.wi.search_text_in_page(page, "Error")
        self.assertGreater(len(matches), 0)

    def test_search_text_case_insensitive_by_default(self):
        page = _make_page(content="Hello World")
        matches = self.wi.search_text_in_page(page, "hello")
        self.assertGreater(len(matches), 0)

    def test_search_text_case_sensitive(self):
        page = _make_page(content="Hello World")
        matches = self.wi.search_text_in_page(page, "hello", case_sensitive=True)
        self.assertEqual(matches, [])

    def test_search_text_no_match_returns_empty(self):
        page = _make_page(content="Hello World")
        matches = self.wi.search_text_in_page(page, "nonexistent_xyz")
        self.assertEqual(matches, [])

    def test_search_text_regex_pattern(self):
        page = _make_page(content="IP: 192.168.1.1 and 10.0.0.1")
        matches = self.wi.search_text_in_page(page, r"\d+\.\d+\.\d+\.\d+")
        self.assertEqual(len(matches), 2)


class WebIntegratorExportTests(unittest.TestCase):
    def setUp(self):
        self.wi = WebIntegrator()
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        try:
            self.wi.cache_manager.shutdown(wait=False)
        except Exception:
            pass
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_export_creates_json_file(self):
        page = _make_page()
        out = os.path.join(self._tmp, "page.json")
        self.wi.export_page_data(page, out)
        self.assertTrue(os.path.exists(out))

    def test_export_json_is_valid(self):
        page = _make_page()
        out = os.path.join(self._tmp, "page.json")
        self.wi.export_page_data(page, out)
        with open(out, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["url"], page.url)

    def test_export_creates_parent_dirs(self):
        page = _make_page()
        out = os.path.join(self._tmp, "sub", "dir", "page.json")
        self.wi.export_page_data(page, out)
        self.assertTrue(os.path.exists(out))


class WebIntegratorFlagsTests(unittest.TestCase):
    def test_backend_flags_are_bool(self):
        self.assertIsInstance(REQUESTS_AVAILABLE, bool)
        self.assertIsInstance(BS4_AVAILABLE, bool)

    def test_user_agent_default_set(self):
        wi = WebIntegrator()
        self.assertIsNotNone(wi.user_agent)
        try:
            wi.cache_manager.shutdown(wait=False)
        except Exception:
            pass

    def test_timeout_stored(self):
        wi = WebIntegrator(timeout=15)
        self.assertEqual(wi.timeout, 15)
        try:
            wi.cache_manager.shutdown(wait=False)
        except Exception:
            pass


class CrawlSiteDedupTests(unittest.TestCase):
    """Regression: crawl_site() tracked `visited` and queued links using raw,
    un-normalized URLs, even though normalize_url() already exists and is used
    by batch_fetch_pages(). A page linking to itself via a trivially different
    URL form (e.g. trailing slash) was fetched twice instead of once.
    """

    def setUp(self):
        self.wi = WebIntegrator()

    def tearDown(self):
        try:
            self.wi.cache_manager.shutdown(wait=False)
        except Exception:
            pass

    def test_trailing_slash_variant_not_fetched_twice(self):
        """A link back to the start URL in a different (but equivalent) form
        must not trigger a second fetch of the same page."""
        from unittest import mock

        fetch_calls = []

        def fake_fetch_page(url, use_cache=True):
            fetch_calls.append(url)
            # The start page links back to itself using the no-trailing-slash form.
            links = ["https://example.com"] if url == "https://example.com/" else []
            return _make_page(url=url, links=links)

        with mock.patch.object(self.wi, "check_robots_txt", return_value=True), \
             mock.patch.object(self.wi, "fetch_page", side_effect=fake_fetch_page), \
             mock.patch("time.sleep", return_value=None):
            pages = self.wi.crawl_site("https://example.com/", max_pages=10, depth_limit=3)

        self.assertEqual(
            len(fetch_calls), 1,
            f"Expected exactly 1 fetch_page call (start URL and its normalized-"
            f"equivalent self-link must dedup), got {len(fetch_calls)}: {fetch_calls}. "
            f"Old bug: crawl_site compared raw URLs, not normalize_url() output.",
        )
        self.assertEqual(len(pages), 1)


class SitemapXmlFallbackTests(unittest.TestCase):
    """Regression: 'xml' or 'html.parser' fallback was unreachable (BS4 objects are truthy).

    Before fix: BeautifulSoup(html, 'xml') or BeautifulSoup(html, 'html.parser')
    After fix:  try/except so html.parser is actually used when lxml raises.
    """

    def setUp(self):
        import web_integrator as _wi_mod
        self._wi_mod = _wi_mod
        self.wi = WebIntegrator()

    def tearDown(self):
        try:
            self.wi.cache_manager.shutdown(wait=False)
        except Exception:
            pass

    def test_html_parser_used_when_xml_parser_raises(self):
        """When the xml parser raises, html.parser fallback must be invoked and used."""
        import unittest.mock as mock
        wi_mod = self._wi_mod

        calls = []

        mock_soup = mock.MagicMock()
        mock_url_tag = mock.MagicMock()
        mock_loc = mock.MagicMock()
        mock_loc.get_text.return_value = "https://example.com/p1"
        mock_url_tag.find.side_effect = lambda tag: mock_loc if tag == 'loc' else None
        mock_soup.find_all.return_value = [mock_url_tag]

        def fake_bs4(html_content, parser):
            calls.append(parser)
            if parser == 'xml':
                raise Exception("FeatureNotFound: lxml not available")
            return mock_soup

        orig_bs4_available = wi_mod.BS4_AVAILABLE
        had_bs4 = hasattr(wi_mod, 'BeautifulSoup')
        orig_bs4 = getattr(wi_mod, 'BeautifulSoup', None)
        try:
            wi_mod.BS4_AVAILABLE = True
            wi_mod.BeautifulSoup = fake_bs4
            self.wi._fetch_html = lambda url: "<sitemap><url><loc>x</loc></url></sitemap>"
            entries = self.wi.fetch_sitemap("https://example.com")
        finally:
            wi_mod.BS4_AVAILABLE = orig_bs4_available
            if had_bs4:
                wi_mod.BeautifulSoup = orig_bs4
            elif hasattr(wi_mod, 'BeautifulSoup'):
                del wi_mod.BeautifulSoup

        # html.parser must have been tried
        self.assertIn('html.parser', calls)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].url, "https://example.com/p1")

    def test_xml_parser_used_when_available(self):
        """When the xml parser succeeds, html.parser must NOT be called."""
        import unittest.mock as mock
        wi_mod = self._wi_mod

        calls = []

        mock_soup = mock.MagicMock()
        mock_url_tag = mock.MagicMock()
        mock_loc = mock.MagicMock()
        mock_loc.get_text.return_value = "https://example.com/ok"
        mock_url_tag.find.side_effect = lambda tag: mock_loc if tag == 'loc' else None
        mock_soup.find_all.return_value = [mock_url_tag]

        def fake_bs4(html_content, parser):
            calls.append(parser)
            return mock_soup  # xml parser succeeds

        orig_bs4_available = wi_mod.BS4_AVAILABLE
        had_bs4 = hasattr(wi_mod, 'BeautifulSoup')
        orig_bs4 = getattr(wi_mod, 'BeautifulSoup', None)
        try:
            wi_mod.BS4_AVAILABLE = True
            wi_mod.BeautifulSoup = fake_bs4
            self.wi._fetch_html = lambda url: "<sitemap><url><loc>x</loc></url></sitemap>"
            entries = self.wi.fetch_sitemap("https://example.com")
        finally:
            wi_mod.BS4_AVAILABLE = orig_bs4_available
            if had_bs4:
                wi_mod.BeautifulSoup = orig_bs4
            elif hasattr(wi_mod, 'BeautifulSoup'):
                del wi_mod.BeautifulSoup

        self.assertIn('xml', calls)
        self.assertNotIn('html.parser', calls)
        self.assertEqual(len(entries), 1)


if __name__ == "__main__":
    unittest.main()
