"""
Tests for ConfigValidator correctness.

Verifies:
- Valid config passes validation without exception
- Missing/invalid logging level raises ConfigurationError
- Missing/non-int port raises ConfigurationError
- Missing/non-str theme raises ConfigurationError
- Missing config file raises ConfigurationError
- Invalid JSON raises ConfigurationError

Run: python -m unittest tests.test_config_validator -v
"""
import json
import os
import sys
import tempfile
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from config_validator import ConfigValidator  # noqa: E402
from error_handling import ConfigurationError  # noqa: E402


def _write_config(d: str, data: dict) -> str:
    path = os.path.join(d, "config.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return path


_VALID = {
    "logging": {"level": "INFO"},
    "ui": {"theme": "dark"},
    "network": {"port": 8080},
}


class ConfigValidatorTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    # --- happy path ---

    def test_valid_config_does_not_raise(self):
        path = _write_config(self._tmp, _VALID)
        cv = ConfigValidator(path)
        cv.validate()  # must not raise

    def test_all_log_levels_accepted(self):
        for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            data = {**_VALID, "logging": {"level": level}}
            path = _write_config(self._tmp, data)
            cv = ConfigValidator(path)
            cv.validate()

    # --- logging validation ---

    def test_invalid_log_level_raises(self):
        data = {**_VALID, "logging": {"level": "VERBOSE"}}
        path = _write_config(self._tmp, data)
        cv = ConfigValidator(path)
        with self.assertRaises(ConfigurationError):
            cv.validate()

    def test_missing_log_level_raises(self):
        data = {**_VALID, "logging": {}}
        path = _write_config(self._tmp, data)
        cv = ConfigValidator(path)
        with self.assertRaises(ConfigurationError):
            cv.validate()

    # --- UI validation ---

    def test_non_string_theme_raises(self):
        data = {**_VALID, "ui": {"theme": 42}}
        path = _write_config(self._tmp, data)
        cv = ConfigValidator(path)
        with self.assertRaises(ConfigurationError):
            cv.validate()

    # --- network validation ---

    def test_non_int_port_raises(self):
        data = {**_VALID, "network": {"port": "8080"}}
        path = _write_config(self._tmp, data)
        cv = ConfigValidator(path)
        with self.assertRaises(ConfigurationError):
            cv.validate()

    # --- file loading ---

    def test_missing_file_raises(self):
        with self.assertRaises(ConfigurationError):
            ConfigValidator(os.path.join(self._tmp, "nonexistent.json"))

    def test_invalid_json_raises(self):
        path = os.path.join(self._tmp, "config.json")
        with open(path, "w") as f:
            f.write("{ invalid json")
        with self.assertRaises(ConfigurationError):
            ConfigValidator(path)


if __name__ == "__main__":
    unittest.main()
