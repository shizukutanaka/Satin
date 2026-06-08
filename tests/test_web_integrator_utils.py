"""
Tests for pure utility methods in web_integrator.py.

WebIntegrator.__init__ creates a cache directory and a requests.Session
(if requests is installed).  To avoid file-system side-effects we
construct only the methods we want to test by calling them on a
lightweight instance built with __new__ + manual attribute setup.

Run: python -m unittest tests.test_web_integrator_utils -v
"""
import os
import sys
import types
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from web_integrator import WebIntegrator  # noqa: E402


def _make_integrator() -> WebIntegrator:
    """Return a WebIntegrator instance without running __init__."""
    wi = object.__new__(WebIntegrator)
    wi.user_agent = "TestAgent/1.0"
    # Provide a minimal logger stub so methods that call self.logger don't fail
    log = types.SimpleNamespace(
        info=lambda *a, **kw: None,
        debug=lambda *a, **kw: None,
        warning=lambda *a, **kw: None,
        error=lambda *a, **kw: None,
    )
    wi.logger = log
    return wi


class NormalizeUrlTests(unittest.TestCase):
    def setUp(self):
        self.wi = _make_integrator()

    def test_fragment_stripped(self):
        result = self.wi.normalize_url("https://example.com/page#section")
        self.assertNotIn("#", result)

    def test_query_params_sorted(self):
        result = self.wi.normalize_url("https://example.com/page?b=2&a=1")
        self.assertIn("a=1", result)
        self.assertIn("b=2", result)
        # 'a' must come before 'b' in the query string
        self.assertLess(result.index("a="), result.index("b="))

    def test_trailing_slash_stripped(self):
        result = self.wi.normalize_url("https://example.com/page/")
        self.assertFalse(result.rstrip("?#").endswith("/"))

    def test_host_lowercased(self):
        result = self.wi.normalize_url("https://EXAMPLE.COM/path")
        self.assertIn("example.com", result)

    def test_url_without_scheme_gets_https(self):
        # When no scheme is present, normalize_url should default to https
        # (current implementation: 'https' if not parsed.scheme)
        result = self.wi.normalize_url("example.com/path")
        self.assertTrue(result.startswith("https"))

    def test_idempotent(self):
        url = "https://example.com/path?a=1&b=2"
        once = self.wi.normalize_url(url)
        twice = self.wi.normalize_url(once)
        self.assertEqual(once, twice)

    def test_same_url_different_param_order_normalizes_equal(self):
        u1 = self.wi.normalize_url("https://example.com/?z=3&a=1")
        u2 = self.wi.normalize_url("https://example.com/?a=1&z=3")
        self.assertEqual(u1, u2)


class GenerateUrlHashTests(unittest.TestCase):
    def setUp(self):
        self.wi = _make_integrator()

    def test_same_url_same_hash(self):
        h1 = self.wi.generate_url_hash("https://example.com/page")
        h2 = self.wi.generate_url_hash("https://example.com/page")
        self.assertEqual(h1, h2)

    def test_different_urls_different_hash(self):
        h1 = self.wi.generate_url_hash("https://example.com/a")
        h2 = self.wi.generate_url_hash("https://example.com/b")
        self.assertNotEqual(h1, h2)

    def test_hash_length(self):
        h = self.wi.generate_url_hash("https://example.com")
        self.assertEqual(len(h), 16)


if __name__ == "__main__":
    unittest.main()
