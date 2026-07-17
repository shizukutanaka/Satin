"""
Unit tests for schema_validators — the pure-Python validator functions
and fallback model stubs (Pydantic is not required).
"""
import os
import sys
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from schema_validators import (  # noqa: E402
    validate_url,
    validate_api_key,
    validate_positive_number,
    validate_percentage,
    ContentType,
    APIProvider,
    HTTPMethod,
)
import re as _re


class ValidateUrlTests(unittest.TestCase):
    def test_valid_https_url_passes(self):
        url = "https://www.example.com/path"
        self.assertEqual(validate_url(url), url)

    def test_valid_http_url_passes(self):
        url = "http://localhost:8080/api"
        self.assertEqual(validate_url(url), url)

    def test_missing_scheme_raises(self):
        with self.assertRaises(ValueError):
            validate_url("www.example.com/no-scheme")

    def test_missing_netloc_raises(self):
        with self.assertRaises(ValueError):
            validate_url("https://")

    def test_empty_string_raises(self):
        with self.assertRaises(ValueError):
            validate_url("")


class ValidateApiKeyTests(unittest.TestCase):
    def test_valid_key_passes(self):
        key = "A" * 20
        self.assertEqual(validate_api_key(key), key)

    def test_exactly_10_chars_passes(self):
        key = "1234567890"
        self.assertEqual(validate_api_key(key), key)

    def test_too_short_raises(self):
        with self.assertRaises(ValueError):
            validate_api_key("short")

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            validate_api_key("")

    def test_too_long_raises(self):
        with self.assertRaises(ValueError):
            validate_api_key("x" * 501)

    def test_exactly_500_chars_passes(self):
        key = "k" * 500
        self.assertEqual(validate_api_key(key), key)


class ValidatePositiveNumberTests(unittest.TestCase):
    def test_positive_int_passes(self):
        self.assertEqual(validate_positive_number(5), 5)

    def test_positive_float_passes(self):
        self.assertAlmostEqual(validate_positive_number(0.1), 0.1)

    def test_zero_raises(self):
        with self.assertRaises(ValueError):
            validate_positive_number(0)

    def test_negative_raises(self):
        with self.assertRaises(ValueError):
            validate_positive_number(-1)

    def test_large_positive_passes(self):
        self.assertEqual(validate_positive_number(1_000_000), 1_000_000)


class ValidatePercentageTests(unittest.TestCase):
    def test_zero_passes(self):
        self.assertEqual(validate_percentage(0.0), 0.0)

    def test_hundred_passes(self):
        self.assertEqual(validate_percentage(100.0), 100.0)

    def test_midpoint_passes(self):
        self.assertEqual(validate_percentage(50.0), 50.0)

    def test_negative_raises(self):
        with self.assertRaises(ValueError):
            validate_percentage(-0.1)

    def test_over_hundred_raises(self):
        with self.assertRaises(ValueError):
            validate_percentage(100.1)


class EnumTests(unittest.TestCase):
    def test_content_type_values(self):
        self.assertEqual(ContentType.VIDEO, "video")
        self.assertEqual(ContentType.PAPER, "paper")

    def test_http_method_values(self):
        self.assertIn(HTTPMethod.GET, HTTPMethod)
        self.assertIn(HTTPMethod.POST, HTTPMethod)

    def test_api_provider_has_youtube(self):
        names = [e.name for e in APIProvider]
        self.assertTrue(any("YOUTUBE" in n or "youtube" in n.lower() for n in names))


class ValidateUrlErrorMessageTests(unittest.TestCase):
    """Regression: validate_url had a try/except Exception that caught its own
    inner ValueError and re-raised it wrapped in a new message:
      "URL validation failed: Invalid URL format"
    The correct message should be "Invalid URL format" directly.

    Root cause: the bare `except Exception as e` around `urlparse` also
    caught the deliberately-raised ValueError, doubling the error text.
    Fix: remove the try/except (urlparse never raises) and let the
    ValueError propagate directly.
    """

    def test_invalid_url_message_is_not_double_wrapped(self):
        """Error must say 'Invalid URL format', not 'URL validation failed: Invalid URL format'."""
        try:
            validate_url("not-a-url")
        except ValueError as e:
            msg = str(e)
            self.assertNotIn(
                "URL validation failed: Invalid URL format", msg,
                "Old bug: inner ValueError was caught and re-wrapped, producing "
                "'URL validation failed: Invalid URL format'.",
            )
            self.assertIn("Invalid URL format", msg,
                          "Error message must mention the actual problem")
        else:
            self.fail("validate_url('not-a-url') should raise ValueError")

    def test_valid_url_still_passes(self):
        self.assertEqual(validate_url("https://example.com/path"), "https://example.com/path")

    def test_missing_netloc_still_raises(self):
        with self.assertRaises(ValueError):
            validate_url("file://")


class ArxivCategoryRegexTests(unittest.TestCase):
    """Regression: validate_categories used pattern '^[a-z]+(\\.[A-Z]{2})?$' which
    rejects valid hyphenated arXiv physics categories like 'quant-ph', 'hep-ph',
    'gr-qc', 'cond-mat', 'astro-ph'.

    The `[a-z]+` segment does not allow hyphens, so any classic arXiv category
    that uses a hyphen in the archive name fails validation even though these are
    published, well-known identifiers in the arXiv API.

    Fix: expand the pattern to allow hyphens: '^[a-z][a-z0-9-]*(\\.[A-Z]{2})?$'
    """

    def _compile_pattern(self):
        import schema_validators as sv
        import inspect
        src = inspect.getsource(sv.ArxivSearchRequest.validate_categories)
        m = _re.search(r"re\.compile\(r?['\"](.+?)['\"]\)", src)
        if not m:
            self.skipTest("Could not extract regex from source")
        return _re.compile(m.group(1))

    def test_cs_LG_is_valid(self):
        p = self._compile_pattern()
        self.assertTrue(p.match("cs.LG"), "'cs.LG' must match the category pattern")

    def test_stat_ML_is_valid(self):
        p = self._compile_pattern()
        self.assertTrue(p.match("stat.ML"), "'stat.ML' must match the category pattern")

    def test_quant_ph_is_valid(self):
        """quant-ph is a real arXiv archive; old regex rejected it."""
        p = self._compile_pattern()
        self.assertTrue(
            p.match("quant-ph"),
            "'quant-ph' must match; old bug: '[a-z]+' disallows hyphens → "
            "classic physics categories were incorrectly rejected.",
        )

    def test_hep_ph_is_valid(self):
        p = self._compile_pattern()
        self.assertTrue(p.match("hep-ph"), "'hep-ph' must match the category pattern")

    def test_gr_qc_is_valid(self):
        p = self._compile_pattern()
        self.assertTrue(p.match("gr-qc"), "'gr-qc' must match the category pattern")

    def test_plain_digits_only_are_invalid(self):
        p = self._compile_pattern()
        self.assertFalse(p.match("123"), "Purely numeric category must not match")

    def test_empty_string_is_invalid(self):
        p = self._compile_pattern()
        self.assertFalse(bool(p.match("")), "Empty string must not match")


if __name__ == "__main__":
    unittest.main()
