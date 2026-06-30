"""
Regression tests for optimize.PerformanceMonitor correctness bugs.

Bug 1: async_record_metric held self._lock and called _cleanup_metrics
  which also tried async with self._lock → asyncio.Lock is non-reentrant
  → permanent deadlock.

Bug 2: calculate_confidence_interval called np.mean/std/sqrt without
  guarding against np=None → AttributeError when numpy is absent.

Run: python -m unittest tests.test_optimize -v
"""
import asyncio
import os
import sys
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from optimize import PerformanceMonitor  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class AsyncRecordMetricDeadlockTest(unittest.TestCase):
    """Regression: async_record_metric must not deadlock on cleanup trigger."""

    def test_no_deadlock_when_cleanup_fires(self):
        """Record enough metrics to trigger cleanup without hanging."""
        pm = PerformanceMonitor()
        # Force cleanup to trigger on the very next record by moving
        # _last_cleanup far into the past.
        pm._last_cleanup = 0  # epoch → always older than interval

        async def scenario():
            # This must complete; if there's a deadlock it times out.
            await asyncio.wait_for(
                pm.async_record_metric("test_metric", 1.0),
                timeout=2.0
            )

        run(scenario())  # AssertionError if TimeoutError is raised

    def test_repeated_records_without_deadlock(self):
        """Multiple records with cleanup threshold crossed each time."""
        pm = PerformanceMonitor()
        pm._last_cleanup = 0

        async def scenario():
            for i in range(5):
                pm._last_cleanup = 0  # re-arm cleanup each iteration
                await asyncio.wait_for(
                    pm.async_record_metric("load", float(i)),
                    timeout=2.0
                )

        run(scenario())


class ConfidenceIntervalWithoutNumpyTest(unittest.TestCase):
    """Regression: calculate_confidence_interval must work when np is None.

    Metrics are stored as flat lists of floats by record_metric(); the method
    previously assumed a dict-of-dicts structure (self.metrics[resource]['history'])
    which raised TypeError on production data.
    """

    def _make_pm_with_history(self, values):
        pm = PerformanceMonitor()
        # Flat list of floats — matches what record_metric() produces.
        pm.metrics["cpu"] = list(values)
        return pm

    def test_returns_tuple_without_numpy(self):
        import optimize as opt_mod
        original_np = opt_mod.np
        try:
            opt_mod.np = None  # simulate missing numpy
            pm = self._make_pm_with_history([70.0, 75.0, 80.0, 85.0, 90.0])
            lower, upper = run(pm.calculate_confidence_interval("cpu"))
            self.assertIsInstance(lower, float)
            self.assertIsInstance(upper, float)
            self.assertLess(lower, upper)
        finally:
            opt_mod.np = original_np

    def test_missing_resource_returns_zero_tuple(self):
        pm = PerformanceMonitor()
        result = run(pm.calculate_confidence_interval("nonexistent"))
        self.assertEqual(result, (0, 0))

    def test_empty_history_returns_zero_tuple(self):
        pm = PerformanceMonitor()
        pm.metrics["cpu"] = []  # flat empty list (matches record_metric storage)
        result = run(pm.calculate_confidence_interval("cpu"))
        self.assertEqual(result, (0, 0))

    def test_interval_contains_mean(self):
        """The computed interval must bracket the sample mean."""
        values = [50.0, 60.0, 70.0, 80.0, 90.0]
        pm = self._make_pm_with_history(values)
        lower, upper = run(pm.calculate_confidence_interval("cpu"))
        mean = sum(values) / len(values)
        self.assertLessEqual(lower, mean)
        self.assertGreaterEqual(upper, mean)

    def test_via_record_metric_does_not_raise(self):
        """Regression: calling calculate_confidence_interval after record_metric
        used to raise TypeError because self.metrics[resource] is a flat list
        but the method tried self.metrics[resource]['history']."""
        pm = PerformanceMonitor()
        for v in [10.0, 20.0, 30.0, 40.0, 50.0]:
            pm.record_metric("cpu", v)
        lower, upper = run(pm.calculate_confidence_interval("cpu"))
        self.assertIsInstance(lower, float)
        self.assertIsInstance(upper, float)


class RecordMetricSyncTest(unittest.TestCase):
    def test_record_metric_stores_values(self):
        pm = PerformanceMonitor()
        pm.record_metric("latency", 0.5)
        pm.record_metric("latency", 1.0)
        self.assertIn("latency", pm.metrics)
        self.assertEqual(pm.metrics["latency"], [0.5, 1.0])

    def test_get_metrics_summary(self):
        pm = PerformanceMonitor()
        for v in [1.0, 2.0, 3.0, 4.0, 5.0]:
            pm.record_metric("timing", v)
        m = pm.get_metrics()
        self.assertEqual(m["timing"]["count"], 5)
        self.assertAlmostEqual(m["timing"]["avg"], 3.0)
        self.assertEqual(m["timing"]["min"], 1.0)
        self.assertEqual(m["timing"]["max"], 5.0)


class PercentileEdgeCaseTests(unittest.TestCase):
    """Regression: _calculate_percentile(values, 100) raised IndexError."""

    def setUp(self):
        self.pm = PerformanceMonitor()

    def test_percentile_100_does_not_raise(self):
        """percentile=100 used to yield index == len → IndexError."""
        result = self.pm._calculate_percentile([1, 2, 3, 4, 5], 100)
        self.assertEqual(result, 5)

    def test_percentile_0_returns_minimum(self):
        result = self.pm._calculate_percentile([3, 1, 4, 1, 5], 0)
        self.assertEqual(result, 1)

    def test_percentile_empty_returns_zero(self):
        self.assertEqual(self.pm._calculate_percentile([], 95), 0)

    def test_percentile_single_element(self):
        self.assertEqual(self.pm._calculate_percentile([42.0], 99), 42.0)


class CacheResultCompressionTests(unittest.TestCase):
    """Regression: cache_result with compression=True returned compressed bytes
    on the first (non-cached) call while subsequent cache-hit calls returned the
    original (decompressed) value — inconsistent behavior.

    Fix: always return the original result; only the cached copy is compressed.
    """

    def setUp(self):
        from optimize import cache_result
        self._cache_result = cache_result

    def test_first_call_returns_original_not_bytes(self):
        """First call must NOT return raw compressed bytes."""
        call_count = [0]

        @self._cache_result(ttl=60, compression=True)
        def expensive(x):
            call_count[0] += 1
            return {"value": x, "computed": True}

        result = expensive(42)
        self.assertIsInstance(result, dict,
            "First call with compression=True must return the original dict, "
            "not compressed bytes (the old bug returned bytes on first call).")
        self.assertEqual(result["value"], 42)
        self.assertEqual(call_count[0], 1)

    def test_second_call_also_returns_original(self):
        """Both first and second calls must return the same value type."""
        @self._cache_result(ttl=60, compression=True)
        def compute(x):
            return [x, x * 2]

        first = compute(7)
        second = compute(7)
        self.assertEqual(first, [7, 14])
        self.assertEqual(second, [7, 14],
            "Cache-hit call (2nd) must return the original list, not bytes.")
        self.assertIsInstance(second, list)

    def test_compression_false_still_returns_original(self):
        """With compression=False the decorator must also return the original."""
        @self._cache_result(ttl=60, compression=False)
        def compute(x):
            return {"key": x}

        self.assertEqual(compute(5), {"key": 5})
        self.assertEqual(compute(5), {"key": 5})

    def test_async_first_call_returns_original_not_bytes(self):
        """Async wrapper: first call must return original, not compressed bytes."""
        @self._cache_result(ttl=60, compression=True)
        async def async_compute(x):
            return {"async": True, "x": x}

        result = asyncio.run(async_compute(99))
        self.assertIsInstance(result, dict,
            "Async first call with compression=True must return original dict.")
        self.assertEqual(result["x"], 99)

    def test_async_second_call_returns_original(self):
        """Async wrapper: cache-hit call must also return the original value."""
        @self._cache_result(ttl=60, compression=True)
        async def async_compute(x):
            return [x, x + 1]

        async def scenario():
            first = await async_compute(3)
            second = await async_compute(3)
            return first, second

        first, second = asyncio.run(scenario())
        self.assertEqual(first, [3, 4])
        self.assertEqual(second, [3, 4])

    def test_underlying_function_called_only_once_within_ttl(self):
        """Cache must still suppress repeated function calls (basic TTL check)."""
        call_count = [0]

        @self._cache_result(ttl=60, compression=True)
        def work(x):
            call_count[0] += 1
            return x * 10

        work(5)
        work(5)
        work(5)
        self.assertEqual(call_count[0], 1,
            "Function should only be invoked once within TTL.")


if __name__ == "__main__":
    unittest.main()
