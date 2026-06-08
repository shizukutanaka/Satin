"""
Regression tests for config_version_manager.

Key bugs fixed:
1. Duplicate `if __name__ == "__main__":` block that also passed a dict to
   restore_config_version() instead of a path string.
2. Verify that list_config_versions() returns dicts with a 'path' key (not
   raw strings), so callers that use v['path'] are correct.
3. Verify cleanup_old_versions() enforces MAX_VERSIONS.

Run: python -m unittest tests.test_config_version_manager -v
"""
import json
import os
import sys
import tempfile
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import config_version_manager as cvm  # noqa: E402


class ConfigVersionManagerTests(unittest.TestCase):
    def setUp(self):
        # Run tests in an isolated temporary directory
        self._orig_dir = os.getcwd()
        self._tmp = tempfile.mkdtemp()
        os.chdir(self._tmp)

        # Create a minimal config file
        self.config_path = os.path.join(self._tmp, "config.json")
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump({"key": "value", "version": 1}, f)

        # Reset the versions dir constant to be relative to our tmpdir
        self._orig_versions_dir = cvm.VERSIONS_DIR
        cvm.VERSIONS_DIR = os.path.join(self._tmp, "config_versions")

    def tearDown(self):
        os.chdir(self._orig_dir)
        cvm.VERSIONS_DIR = self._orig_versions_dir
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_save_returns_path_string(self):
        path = cvm.save_config_version(self.config_path)
        self.assertIsInstance(path, str)
        self.assertTrue(os.path.exists(path))

    def test_list_returns_dicts_with_path_key(self):
        cvm.save_config_version(self.config_path)
        versions = cvm.list_config_versions(self.config_path)
        self.assertGreater(len(versions), 0)
        for v in versions:
            self.assertIsInstance(v, dict)
            self.assertIn('path', v)
            self.assertIn('timestamp', v)
            self.assertIn('mod_time', v)
            self.assertIn('size', v)
            # path must be a string, not a dict (was the bug)
            self.assertIsInstance(v['path'], str)

    def test_restore_from_list_path_key(self):
        # Demonstrate that using v['path'] correctly calls restore
        cvm.save_config_version(self.config_path)
        versions = cvm.list_config_versions(self.config_path)
        self.assertGreater(len(versions), 0)
        # Mutate config
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump({"key": "changed"}, f)
        # Restore — must not raise TypeError
        cvm.restore_config_version(versions[0]['path'], self.config_path)
        with open(self.config_path, encoding="utf-8") as f:
            restored = json.load(f)
        self.assertEqual(restored.get("key"), "value")

    def test_cleanup_enforces_max_versions(self):
        orig_max = cvm.MAX_VERSIONS
        cvm.MAX_VERSIONS = 3
        try:
            for _ in range(5):
                cvm.save_config_version(self.config_path)
            versions = cvm.list_config_versions(self.config_path)
            # cleanup_old_versions is called inside save_config_version,
            # so versions count must not exceed MAX_VERSIONS.
            self.assertLessEqual(len(versions), cvm.MAX_VERSIONS)
        finally:
            cvm.MAX_VERSIONS = orig_max

    def test_compare_versions_detects_differences(self):
        # Use distinct descriptions to guarantee unique filenames even within 1 second
        v1 = cvm.save_config_version(self.config_path, description="v1")
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump({"key": "different", "version": 2}, f)
        v2 = cvm.save_config_version(self.config_path, description="v2")
        result = cvm.compare_versions(v1, v2)
        self.assertIn('differences', result)
        self.assertIn('key', result['differences'])
        self.assertEqual(result['differences']['key']['old'], 'value')
        self.assertEqual(result['differences']['key']['new'], 'different')

    def test_no_duplicate_main_block(self):
        """The duplicate __main__ block has been removed."""
        import inspect
        src = inspect.getsource(cvm)
        # Count occurrences of the sentinel string
        count = src.count('if __name__ == "__main__":')
        self.assertLessEqual(count, 1, "Duplicate __main__ block still present")


if __name__ == "__main__":
    unittest.main()
