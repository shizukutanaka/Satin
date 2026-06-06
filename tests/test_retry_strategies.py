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


if __name__ == "__main__":
    unittest.main()
