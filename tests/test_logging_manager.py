"""
Stdlib-only regression test for the missing-import fix in main/logging_manager.py.

`threading` and `time` were used in __init__/_compress_old_logs but never
imported, so LoggingManager() crashed with NameError whenever it was configured
(config/plugins/logging_manager.json exists).

Run: python -m unittest tests.test_logging_manager -v
"""
import logging
import os
import sys
import tempfile
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import logging_manager as lm  # noqa: E402


class _FakeConfig:
    def __init__(self, base):
        self.config_path = os.path.join(base, "config.json")

    def get_plugin_config(self, name):
        return {"log_level": "info", "max_bytes": 1024, "backup_count": 2}


class LoggingManagerImportTests(unittest.TestCase):
    def test_threading_and_time_are_imported(self):
        self.assertTrue(hasattr(lm, "threading"))
        self.assertTrue(hasattr(lm, "time"))

    def test_instantiation_when_configured_does_not_raise(self):
        tmp = tempfile.mkdtemp()
        original = lm.get_config_manager
        root = logging.getLogger()
        before = list(root.handlers)
        lm.get_config_manager = lambda: _FakeConfig(tmp)
        try:
            mgr = lm.LoggingManager()  # previously NameError: name 'threading'
            self.assertTrue(mgr.compression_thread.is_alive())
            mgr.stop()
        finally:
            lm.get_config_manager = original
            for h in list(root.handlers):
                if h not in before:
                    root.removeHandler(h)


class LoggingManagerStopTests(unittest.TestCase):
    """Regression: stop() must wake the sleeping thread quickly, not wait 1800s."""

    def _make_mgr(self):
        import tempfile
        tmp = tempfile.mkdtemp()
        original = lm.get_config_manager
        root = logging.getLogger()
        before = list(root.handlers)
        lm.get_config_manager = lambda: _FakeConfig(tmp)
        try:
            mgr = lm.LoggingManager()
        finally:
            lm.get_config_manager = original
            for h in list(root.handlers):
                if h not in before:
                    root.removeHandler(h)
        return mgr

    def test_stop_exits_thread_quickly(self):
        mgr = self._make_mgr()
        self.assertTrue(mgr.compression_thread.is_alive())
        mgr.stop(wait=True)
        # Thread must exit within a second, not wait for the 1800s sleep.
        self.assertFalse(mgr.compression_thread.is_alive(),
                         "compression thread still alive after stop()")

    def test_stop_without_settings_does_not_raise(self):
        """stop() on an unconfigured LoggingManager (no settings) must not raise."""
        original = lm.get_config_manager

        class _NoSettingsConfig:
            config_path = "/tmp/test_config.json"
            def get_plugin_config(self, name): return None

        lm.get_config_manager = lambda: _NoSettingsConfig()
        try:
            mgr = lm.LoggingManager()
        finally:
            lm.get_config_manager = original
        mgr.stop()  # must not raise AttributeError


if __name__ == "__main__":
    unittest.main()
