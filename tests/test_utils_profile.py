"""
Stdlib-only regression tests for main/utils_profile.py.

Run: python -m unittest tests.test_utils_profile -v
"""
import logging
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
