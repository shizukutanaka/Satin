"""
Regression tests for config/__init__.py ConfigManager.

Previously _load_defaults / reload / start_watching were declared in __init__
but not implemented, causing AttributeError on instantiation.
"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from config import ConfigManager, ConfigSource, ConfigValue  # noqa: E402


class InstantiationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_mgr(self):
        mgr = ConfigManager(self._tmp)
        # Stop background watcher immediately after creation
        mgr._running = False
        return mgr

    def test_instantiation_does_not_raise(self):
        """ConfigManager() must not raise AttributeError (missing method regression)."""
        mgr = self._make_mgr()
        self.assertIsNotNone(mgr)

    def test_is_running_after_start_watching(self):
        mgr = ConfigManager(self._tmp)
        self.assertTrue(mgr._running)
        mgr._running = False  # stop the watcher thread
        if mgr._file_watcher:
            mgr._file_watcher.join(timeout=2.0)

    def test_reload_reads_config_file(self):
        config_file = Path(self._tmp) / "config.json"
        config_file.write_text(json.dumps({"foo": "bar"}), encoding="utf-8")
        mgr = self._make_mgr()
        mgr.reload()
        self.assertIn("foo", mgr._config)
        self.assertEqual(mgr._config["foo"].value, "bar")

    def test_load_defaults_reads_defaults_file(self):
        defaults_file = Path(self._tmp) / "defaults.json"
        defaults_file.write_text(json.dumps({"default_key": 42}), encoding="utf-8")
        mgr = self._make_mgr()
        mgr._load_defaults()
        self.assertIn("default_key", mgr._defaults)
        self.assertEqual(mgr._defaults["default_key"], 42)

    def test_notify_listeners_called_on_reload_change(self):
        config_file = Path(self._tmp) / "config.json"
        config_file.write_text(json.dumps({"x": 1}), encoding="utf-8")
        mgr = self._make_mgr()
        mgr.reload()

        changes = []
        mgr._listeners["x"] = [lambda k, old, new: changes.append((old, new))]

        config_file.write_text(json.dumps({"x": 2}), encoding="utf-8")
        mgr.reload()
        self.assertEqual(changes, [(1, 2)])

    def test_reload_with_missing_config_file_does_not_crash(self):
        mgr = self._make_mgr()
        # No config.json exists — should not raise
        mgr.reload()


if __name__ == "__main__":
    unittest.main()
