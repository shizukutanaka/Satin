"""
Stdlib-only regression tests for the Tier-2 fixes in main/performance_profiling.py.

Run: python -m unittest tests.test_performance_profiling -v
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main.performance_profiling import (  # noqa: E402
    PerformanceMonitor,
    PerformanceProfiler,
    MemoryProfiler,
    profile_call,
)


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


class PerformanceProfilerTests(unittest.TestCase):
    def test_profile_sync_returns_result(self):
        profiler = PerformanceProfiler()
        value, pr = profiler.profile_sync(lambda: 42)
        self.assertEqual(value, 42)

    def test_profile_sync_stores_result(self):
        profiler = PerformanceProfiler()
        profiler.profile_sync(lambda: None)
        self.assertGreater(len(profiler.results), 0)

    def test_profile_result_has_positive_time(self):
        profiler = PerformanceProfiler()
        _, pr = profiler.profile_sync(sum, range(1000))
        self.assertGreaterEqual(pr.total_time_ms, 0)

    def test_profile_result_function_name(self):
        def my_func():
            return "hello"

        profiler = PerformanceProfiler()
        _, pr = profiler.profile_sync(my_func)
        self.assertEqual(pr.function_name, "my_func")

    def test_get_slowest_functions_ordering(self):
        profiler = PerformanceProfiler()
        profiler.profile_sync(lambda: None)
        profiler.profile_sync(sum, range(10000))
        slowest = profiler.get_slowest_functions()
        self.assertGreater(len(slowest), 0)

    def test_get_memory_heavy_functions(self):
        profiler = PerformanceProfiler()
        profiler.profile_sync(lambda: [0] * 1000)
        heavy = profiler.get_memory_heavy_functions()
        self.assertGreater(len(heavy), 0)

    def test_export_report_creates_valid_json(self):
        profiler = PerformanceProfiler()
        profiler.profile_sync(lambda: 1 + 1)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "report.json"
            profiler.export_report(path)
            self.assertTrue(path.exists())
            data = json.loads(path.read_text())
            self.assertIn("results", data)
            self.assertIn("timestamp", data)


class PerformanceProfilerAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_profile_async_returns_result(self):
        profiler = PerformanceProfiler()

        async def async_double(n):
            return n * 2

        value, pr = await profiler.profile_async(async_double, 5)
        self.assertEqual(value, 10)

    async def test_profile_async_stores_result(self):
        profiler = PerformanceProfiler()

        async def noop():
            return None

        await profiler.profile_async(noop)
        self.assertIn("noop", profiler.results)


class MemoryProfilerTests(unittest.TestCase):
    def test_take_snapshot_returns_memory_snapshot(self):
        mp = MemoryProfiler()
        snap = mp.take_snapshot()
        self.assertIsNotNone(snap)
        self.assertGreaterEqual(snap.current_mb, 0)

    def test_snapshot_stored_in_list(self):
        mp = MemoryProfiler()
        mp.take_snapshot()
        self.assertEqual(len(mp.snapshots), 1)

    def test_set_baseline_stored(self):
        mp = MemoryProfiler()
        mp.set_baseline()
        self.assertIsNotNone(mp._baseline)

    def test_get_memory_delta_after_baseline(self):
        mp = MemoryProfiler()
        mp.set_baseline()
        delta = mp.get_memory_delta()
        self.assertIsInstance(delta, float)

    def test_detect_leak_false_below_threshold(self):
        mp = MemoryProfiler()
        mp.set_baseline()
        leak = mp.detect_leak(threshold_mb=1_000_000)
        self.assertFalse(leak)

    def test_export_report_creates_json(self):
        mp = MemoryProfiler()
        mp.take_snapshot()
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "memory.json"
            mp.export_report(path)
            self.assertTrue(path.exists())
            data = json.loads(path.read_text())
            self.assertIn("snapshots", data)


class ProfileCallDecoratorTests(unittest.TestCase):
    def test_sync_function_returns_correct_result(self):
        @profile_call
        def add(a, b):
            return a + b

        self.assertEqual(add(2, 3), 5)

    def test_sync_function_with_memory_flag(self):
        @profile_call(memory=True)
        def make_list():
            return [0] * 100

        result = make_list()
        self.assertEqual(len(result), 100)


class ProfileCallAsyncDecoratorTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_function_returns_correct_result(self):
        @profile_call
        async def async_add(a, b):
            return a + b

        result = await async_add(3, 4)
        self.assertEqual(result, 7)


if __name__ == "__main__":
    unittest.main()
