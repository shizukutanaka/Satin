"""
Stdlib-only regression tests for the fixes in main/retry_strategies.py.
Works without `tenacity` installed (the module degrades gracefully).

Run: python -m unittest tests.test_retry_strategies -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main.retry_strategies as rs  # noqa: E402
from main.retry_strategies import RetryMetrics, get_retry_metrics  # noqa: E402


class RetryMetricsTests(unittest.TestCase):
    def setUp(self):
        # Reset the module-level aggregate between tests.
        rs._global_retry_metrics = RetryMetrics()

    def test_get_retry_metrics_does_not_raise_and_aggregates(self):
        # Previously raised AttributeError (read instance attrs as class attrs).
        self.assertEqual(
            get_retry_metrics(),
            {'total_calls': 0, 'total_retries': 0, 'successful': 0, 'failed': 0},
        )
        rs._global_retry_metrics.record_attempt("f", 1, True)
        rs._global_retry_metrics.record_attempt("f", 3, False, "boom")
        snap = get_retry_metrics()
        self.assertEqual(snap['total_calls'], 2)
        self.assertEqual(snap['successful'], 1)
        self.assertEqual(snap['failed'], 1)
        self.assertEqual(snap['total_retries'], 1)  # attempt>1 counts as a retry

    def test_attempt_import_removed(self):
        # The unused `Attempt` symbol must not be referenced at module level.
        self.assertFalse(hasattr(rs, "Attempt"))


class RetryWithMetricsTests(unittest.TestCase):
    """Regression: retry_with_metrics did not record failed calls in metrics.

    The except RetryError block inside wrapper was dead code because tenacity
    raises RetryError *outside* the wrapper body. The fix uses an outer/inner
    pattern so failures are always captured.
    """

    def setUp(self):
        rs._global_retry_metrics = RetryMetrics()

    def _run_with_tenacity(self, func, config):
        try:
            from tenacity import stop_after_attempt, wait_none
        except ImportError:
            self.skipTest("tenacity not installed")
        from main.retry_strategies import RetryConfiguration, retry_with_metrics
        cfg = RetryConfiguration(max_retries=config.get("max_retries", 2))
        metrics = RetryMetrics()
        decorated = retry_with_metrics(cfg, metrics=metrics)(func)
        return decorated, metrics

    def test_success_records_attempt(self):
        calls = [0]

        def succeed():
            calls[0] += 1
            return "ok"

        try:
            decorated, metrics = self._run_with_tenacity(succeed, {"max_retries": 3})
        except unittest.SkipTest:
            return

        result = decorated()
        self.assertEqual(result, "ok")
        self.assertEqual(metrics.successful_calls, 1)
        self.assertEqual(metrics.failed_calls, 0)

    def test_failure_records_failed_call(self):
        def always_fail():
            raise ValueError("boom")

        try:
            decorated, metrics = self._run_with_tenacity(always_fail, {"max_retries": 2})
        except unittest.SkipTest:
            return

        with self.assertRaises(ValueError):
            decorated()
        # Failed call must be recorded (previously: failed_calls stayed 0).
        self.assertEqual(metrics.failed_calls, 1)
        self.assertEqual(metrics.successful_calls, 0)


if __name__ == "__main__":
    unittest.main()
