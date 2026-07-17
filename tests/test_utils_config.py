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


class AtomicSaveConfigTests(unittest.TestCase):
    """Regression: save_config wrote config.json in place with open(path,'w'),
    so a crash or a json.dump TypeError mid-write left a truncated/corrupt
    base config. It must write atomically (tmp + os.replace) like the rest of
    the codebase."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._path = os.path.join(self._tmp, "config.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_save_writes_valid_json(self):
        import json
        ok = uc.save_config({"a": 1, "b": [1, 2]}, self._path)
        self.assertTrue(ok)
        with open(self._path) as f:
            self.assertEqual(json.load(f), {"a": 1, "b": [1, 2]})

    def test_failed_serialization_preserves_existing_file(self):
        import json
        # Seed a valid config first.
        uc.save_config({"keep": "me"}, self._path)
        # Now attempt to save a non-serializable object (set) -> json raises.
        ok = uc.save_config({"bad": {1, 2, 3}}, self._path)
        self.assertFalse(ok, "non-serializable save must report failure")
        # The original file must be intact, not truncated/corrupt.
        with open(self._path) as f:
            self.assertEqual(json.load(f), {"keep": "me"})

    def test_no_tmp_file_left_behind_on_failure(self):
        uc.save_config({"keep": "me"}, self._path)
        uc.save_config({"bad": {1, 2, 3}}, self._path)  # fails
        leftovers = [n for n in os.listdir(self._tmp) if n.endswith(".tmp")]
        self.assertEqual(leftovers, [], f"temp files leaked: {leftovers}")

    def test_no_tmp_file_left_behind_on_success(self):
        uc.save_config({"a": 1}, self._path)
        leftovers = [n for n in os.listdir(self._tmp) if n.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_unsupported_extension_rejected(self):
        ok = uc.save_config({"a": 1}, os.path.join(self._tmp, "config.txt"))
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
