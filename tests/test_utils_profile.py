"""
Stdlib-only regression tests for main/utils_profile.py.

Run: python -m unittest tests.test_utils_profile -v
"""
import logging
import logging.handlers
import os
import sys
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import utils_profile as up  # noqa: E402


class UtilsProfileTests(unittest.TestCase):
    def test_uses_named_logger_not_root(self):
        # Importing a profiling helper must not hijack the root logger.
        self.assertEqual(up.logger.name, "utils_profile")
        self.assertFalse(up.logger.propagate)

    def test_log_file_lives_under_config_logs_not_cwd(self):
        """Regression: the handler used to be `FileHandler('satin_profile.log')`,
        a bare relative path that resolved against the process's cwd — any
        --manage invocation from the repo root littered it there, unbounded
        (no rotation). The path must be repo-root/config/logs/, derived from
        this module's own location, not wherever the process happens to run
        from."""
        handler = up.logger.handlers[0]
        self.assertTrue(os.path.isabs(handler.baseFilename))
        self.assertEqual(os.path.basename(handler.baseFilename), "satin_profile.log")
        self.assertEqual(os.path.basename(os.path.dirname(handler.baseFilename)), "logs")
        self.assertEqual(
            os.path.basename(os.path.dirname(os.path.dirname(handler.baseFilename))),
            "config",
        )

    def test_uses_rotating_file_handler_with_size_cap(self):
        """Regression: a plain FileHandler never rotates and grows forever."""
        handler = up.logger.handlers[0]
        self.assertIsInstance(handler, logging.handlers.RotatingFileHandler)
        self.assertGreater(handler.maxBytes, 0)
        self.assertGreaterEqual(handler.backupCount, 1)

    def test_profile_time_returns_value(self):
        @up.profile_time
        def double(x):
            return x * 2

        self.assertEqual(double(21), 42)

    def test_profile_time_times_even_on_exception(self):
        calls = {"logged": 0}

        class _Counter(logging.Handler):
            def emit(self, record):
                calls["logged"] += 1

        handler = _Counter()
        up.logger.addHandler(handler)
        try:
            @up.profile_time
            def boom():
                raise ValueError("x")

            with self.assertRaises(ValueError):
                boom()
            # The finally-block logged the elapsed time despite the exception.
            self.assertGreaterEqual(calls["logged"], 1)
        finally:
            up.logger.removeHandler(handler)


if __name__ == "__main__":
    unittest.main()
