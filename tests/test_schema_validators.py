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


if __name__ == "__main__":
    unittest.main()
