"""
Stdlib-only regression tests for the fixes in main/utils_config.py.

Run: python -m unittest tests.test_utils_config -v
"""
import os
import sys
import tempfile
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import utils_config as uc  # noqa: E402


class UpdateConfigTests(unittest.TestCase):
    def setUp(self):
        # Seed a valid full config so get_config() returns it without file I/O.
        uc._config_instance = {
            "version": "1.0.0",
            "settings": {"log_level": "INFO"},
            "plugins": [],
        }

    def tearDown(self):
        uc._config_instance = None

    def test_partial_update_succeeds(self):
        # Previously failed: validated the partial dict (missing version) instead
        # of the merged result.
        ok = uc.update_config({"settings": {"log_level": "DEBUG"}}, save_to_file=False)
        self.assertTrue(ok)
        self.assertEqual(uc._config_instance["settings"]["log_level"], "DEBUG")
        self.assertEqual(uc._config_instance["version"], "1.0.0")  # preserved

    def test_update_that_makes_config_invalid_is_rejected(self):
        ok = uc.update_config({"settings": {"log_level": "BOGUS"}}, save_to_file=False)
        self.assertFalse(ok)  # merged log_level not in allowed set
        # original value unchanged
        self.assertEqual(uc._config_instance["settings"]["log_level"], "INFO")


class OptionalYamlTests(unittest.TestCase):
    def test_yaml_is_optional_symbol(self):
        self.assertTrue(hasattr(uc, "yaml"))

    def test_load_yaml_without_pyyaml_returns_empty(self):
        original = uc.yaml
        uc.yaml = None  # simulate PyYAML not installed
        try:
            fd, path = tempfile.mkstemp(suffix=".yaml")
            os.write(fd, b"version: '1.0.0'\n")
            os.close(fd)
            result = uc.load_config(path)
            self.assertEqual(result, {})  # graceful, no crash
        finally:
            uc.yaml = original
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
