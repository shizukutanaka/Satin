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


class _FullConfig:
    """Config mock that points log_dir to a temp directory."""
    def __init__(self, base):
        self.config_path = os.path.join(base, "config.json")

    def get_plugin_config(self, name):
        return {"log_level": "debug", "max_bytes": 10485760, "backup_count": 2}


def _make_mgr_with_logs(tmp, log_lines):
    """Create a LoggingManager with sample log files in tmp/logs/."""
    root = logging.getLogger()
    before = list(root.handlers)
    original = lm.get_config_manager
    lm.get_config_manager = lambda: _FullConfig(tmp)
    try:
        mgr = lm.LoggingManager()
    finally:
        lm.get_config_manager = original
        for h in list(root.handlers):
            if h not in before:
                root.removeHandler(h)
    # Write sample log lines into the log dir
    log_file = mgr.log_dir / "test.log"
    with open(log_file, "w", encoding="utf-8") as f:
        for line in log_lines:
            f.write(line + "\n")
    return mgr


class SearchLogsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        sample_lines = [
            "2024-01-15 10:00:00 - myapp - ERROR - Database connection failed",
            "2024-01-15 10:01:00 - myapp - INFO - Server started",
            "2024-01-15 10:02:00 - myapp - WARNING - High memory usage",
            "2024-01-15 10:03:00 - myapp - ERROR - Disk almost full",
        ]
        self._mgr = _make_mgr_with_logs(self._tmp, sample_lines)

    def tearDown(self):
        self._mgr.stop()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_search_keyword_returns_matching_lines(self):
        results = self._mgr.search_logs("ERROR")
        self.assertGreaterEqual(len(results), 2)

    def test_search_returns_list(self):
        results = self._mgr.search_logs("anything")
        self.assertIsInstance(results, list)

    def test_search_no_match_returns_empty(self):
        results = self._mgr.search_logs("quantum_tunneling_xyz")
        self.assertEqual(results, [])

    def test_search_case_insensitive(self):
        results = self._mgr.search_logs("database")
        self.assertGreater(len(results), 0)

    def test_search_with_date_range(self):
        results = self._mgr.search_logs(
            "ERROR",
            start_date="2024-01-15 10:00:00",
            end_date="2024-01-15 10:02:00",
        )
        # Only first two within range match ERROR
        self.assertGreaterEqual(len(results), 1)

    def test_search_result_has_expected_keys(self):
        results = self._mgr.search_logs("ERROR")
        if results:
            self.assertIn("timestamp", results[0])
            self.assertIn("message", results[0])


class AnalyzeLogsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        sample_lines = [
            "2024-01-15 10:00:00 - myapp - ERROR - Something failed",
            "2024-01-15 10:01:00 - myapp - INFO - Startup complete",
            "2024-01-15 10:02:00 - myapp - WARNING - Slow query detected",
            "2024-01-15 10:03:00 - myapp - DEBUG - Entering function",
            "2024-01-15 10:04:00 - myapp - CRITICAL - System overload",
        ]
        self._mgr = _make_mgr_with_logs(self._tmp, sample_lines)

    def tearDown(self):
        self._mgr.stop()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_analyze_returns_dict(self):
        result = self._mgr.analyze_logs()
        self.assertIsInstance(result, dict)

    def test_analyze_has_expected_keys(self):
        result = self._mgr.analyze_logs()
        for key in ("total_logs", "error_count", "warning_count", "info_count"):
            self.assertIn(key, result)

    def test_analyze_counts_errors(self):
        result = self._mgr.analyze_logs()
        self.assertGreaterEqual(result["error_count"], 1)

    def test_analyze_counts_warnings(self):
        result = self._mgr.analyze_logs()
        self.assertGreaterEqual(result["warning_count"], 1)


if __name__ == "__main__":
    unittest.main()
