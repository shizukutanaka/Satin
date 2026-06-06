"""
Stdlib-only regression tests for the Tier-2 fixes in main/performance_profiling.py.

Run: python -m unittest tests.test_performance_profiling -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main.performance_profiling import PerformanceMonitor  # noqa: E402


class PerformanceMonitorStatsTests(unittest.TestCase):
    def test_empty_returns_all_keys_no_keyerror(self):
        mon = PerformanceMonitor()
        stats = mon.get_statistics("never_seen")
        # Previously returned {} -> KeyError for callers; now zero-filled.
        self.assertEqual(stats["count"], 0)
        for key in ("mean_ms", "median_ms", "min_ms", "max_ms", "p95_ms", "p99_ms", "stdev_ms"):
            self.assertEqual(stats[key], 0.0)

    def test_median_is_interpolated_for_even_length(self):
        mon = PerformanceMonitor()
        for v in (1.0, 2.0, 3.0, 4.0):
            mon.record_operation("op", v)
        stats = mon.get_statistics("op")
        # Interpolated median of [1,2,3,4] is 2.5 (was 3.0 with values[n//2]).
        self.assertEqual(stats["median_ms"], 2.5)

    def test_percentiles_monotonic_and_bounded(self):
        mon = PerformanceMonitor()
        for v in range(1, 101):  # 1..100
            mon.record_operation("op", float(v))
        stats = mon.get_statistics("op")
        self.assertLessEqual(stats["min_ms"], stats["median_ms"])
        self.assertLessEqual(stats["median_ms"], stats["p95_ms"])
        self.assertLessEqual(stats["p95_ms"], stats["p99_ms"])
        self.assertLessEqual(stats["p99_ms"], stats["max_ms"])
        # p95 of 1..100 (linear interpolation) ~ 95.05
        self.assertAlmostEqual(stats["p95_ms"], 95.05, places=2)

    def test_single_sample(self):
        mon = PerformanceMonitor()
        mon.record_operation("op", 42.0)
        stats = mon.get_statistics("op")
        for key in ("median_ms", "p95_ms", "p99_ms", "min_ms", "max_ms", "mean_ms"):
            self.assertEqual(stats[key], 42.0)


if __name__ == "__main__":
    unittest.main()
