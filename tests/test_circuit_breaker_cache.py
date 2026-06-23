"""
Stdlib-only tests for main/circuit_breaker_cache.py.

Run: python -m unittest tests.test_circuit_breaker_cache -v
"""
import os
import sys
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from circuit_breaker_cache import (  # noqa: E402
    CircuitBreaker, CircuitBreakerConfig, CircuitBreakerMetrics,
    CircuitState, BulkheadPolicy, DistributedCache, DistributedCacheConfig,
    CacheInvalidationStrategy, ResilientService, CircuitBreakerOpenError,
)


class CircuitBreakerMetricsTests(unittest.TestCase):
    def test_initial_state(self):
        m = CircuitBreakerMetrics()
        self.assertEqual(m.total_calls, 0)
        self.assertEqual(m.failed_calls, 0)
        self.assertEqual(m.get_failure_rate(), 0.0)

    def test_failure_rate_computed(self):
        m = CircuitBreakerMetrics(total_calls=4, failed_calls=1)
        self.assertAlmostEqual(m.get_failure_rate(), 25.0)

    def test_to_dict_has_expected_keys(self):
        m = CircuitBreakerMetrics()
        d = m.to_dict()
        for key in ("total_calls", "failed_calls", "failure_rate"):
            self.assertIn(key, d)


class CircuitBreakerTests(unittest.IsolatedAsyncioTestCase):
    async def test_closed_state_initial(self):
        cb = CircuitBreaker("test")
        self.assertEqual(cb.get_state(), CircuitState.CLOSED.value)

    async def test_successful_call_returns_result(self):
        cb = CircuitBreaker("test")
        result = await cb.call(lambda: 42)
        self.assertEqual(result, 42)

    async def test_successful_call_increments_success(self):
        cb = CircuitBreaker("test")
        await cb.call(lambda: 1)
        self.assertEqual(cb.metrics.successful_calls, 1)

    async def test_failed_call_increments_failure(self):
        cb = CircuitBreaker("test", CircuitBreakerConfig(failure_threshold=10))

        async def fail():
            raise ValueError("boom")

        with self.assertRaises(ValueError):
            await cb.call(fail)
        self.assertEqual(cb.metrics.failed_calls, 1)

    async def test_failures_open_circuit(self):
        cb = CircuitBreaker("test", CircuitBreakerConfig(failure_threshold=2))

        async def fail():
            raise RuntimeError("err")

        for _ in range(2):
            try:
                await cb.call(fail)
            except RuntimeError:
                pass

        self.assertEqual(cb.get_state(), CircuitState.OPEN.value)

    async def test_open_circuit_uses_fallback(self):
        cb = CircuitBreaker("test", CircuitBreakerConfig(failure_threshold=1))

        async def fail():
            raise RuntimeError("err")

        async def fb():
            return "fallback"

        try:
            await cb.call(fail)
        except RuntimeError:
            pass

        result = await cb.call(fail, fallback=fb)
        self.assertEqual(result, "fallback")

    async def test_open_circuit_raises_without_fallback(self):
        cb = CircuitBreaker("test", CircuitBreakerConfig(failure_threshold=1))

        async def fail():
            raise RuntimeError("err")

        try:
            await cb.call(fail)
        except RuntimeError:
            pass

        with self.assertRaises(CircuitBreakerOpenError):
            await cb.call(fail)

    async def test_open_circuit_error_is_exception_subclass(self):
        # Backward compat: callers using `except Exception` still catch it.
        self.assertTrue(issubclass(CircuitBreakerOpenError, Exception))

    async def test_get_metrics_returns_dict(self):
        cb = CircuitBreaker("test")
        metrics = cb.get_metrics()
        self.assertIsInstance(metrics, dict)

    async def test_async_func_supported(self):
        cb = CircuitBreaker("test")

        async def async_double(x):
            return x * 2

        result = await cb.call(async_double, 5)
        self.assertEqual(result, 10)


class BulkheadPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_call_returns_result(self):
        bh = BulkheadPolicy(max_concurrent_calls=2)
        result = await bh.call(lambda: "ok")
        self.assertEqual(result, "ok")

    async def test_get_status_has_expected_keys(self):
        bh = BulkheadPolicy(max_concurrent_calls=5)
        status = bh.get_status()
        for key in ("active_calls", "max_concurrent_calls", "rejected_calls", "utilization"):
            self.assertIn(key, status)

    async def test_zero_active_calls_at_rest(self):
        bh = BulkheadPolicy(max_concurrent_calls=3)
        await bh.call(lambda: None)
        self.assertEqual(bh.get_status()["active_calls"], 0)

    async def test_async_func_supported(self):
        bh = BulkheadPolicy()

        async def async_fn():
            return 99

        result = await bh.call(async_fn)
        self.assertEqual(result, 99)


class DistributedCacheTests(unittest.IsolatedAsyncioTestCase):
    def _make_cache(self, ttl=60):
        return DistributedCache(DistributedCacheConfig(ttl_seconds=ttl))

    async def test_set_and_get_returns_value(self):
        cache = self._make_cache()
        await cache.set("key1", "hello")
        result = await cache.get("key1")
        self.assertEqual(result, "hello")

    async def test_get_missing_returns_none(self):
        cache = self._make_cache()
        result = await cache.get("nonexistent")
        self.assertIsNone(result)

    async def test_ttl_expiry_returns_none(self):
        import time
        cache = self._make_cache(ttl=0)
        await cache.set("k", "v")
        time.sleep(0.01)
        result = await cache.get("k")
        self.assertIsNone(result)

    async def test_set_with_tags(self):
        cache = self._make_cache()
        await cache.set("k1", "v1", tags=["group1"])
        await cache.set("k2", "v2", tags=["group1"])
        count = await cache.invalidate_by_tag("group1")
        self.assertEqual(count, 2)
        self.assertIsNone(await cache.get("k1"))
        self.assertIsNone(await cache.get("k2"))

    async def test_invalidate_by_tag_unknown_tag_returns_zero(self):
        cache = self._make_cache()
        count = await cache.invalidate_by_tag("nonexistent")
        self.assertEqual(count, 0)

    async def test_invalidate_by_pattern(self):
        cache = self._make_cache()
        await cache.set("user:1", "alice")
        await cache.set("user:2", "bob")
        await cache.set("product:1", "widget")
        count = await cache.invalidate_by_pattern(r"user:")
        self.assertEqual(count, 2)
        self.assertIsNone(await cache.get("user:1"))
        self.assertIsNotNone(await cache.get("product:1"))

    async def test_get_stats_returns_dict(self):
        cache = self._make_cache()
        stats = cache.get_stats()
        for key in ("cached_items", "cache_hit_rate", "backend"):
            self.assertIn(key, stats)

    async def test_get_stats_cached_items_count(self):
        cache = self._make_cache()
        await cache.set("a", 1)
        await cache.set("b", 2)
        stats = cache.get_stats()
        self.assertEqual(stats["cached_items"], 2)


class DistributedCacheConfigTests(unittest.TestCase):
    def test_defaults(self):
        cfg = DistributedCacheConfig()
        self.assertEqual(cfg.backend, "memory")
        self.assertEqual(cfg.ttl_seconds, 3600)

    def test_custom_backend(self):
        cfg = DistributedCacheConfig(backend="redis", ttl_seconds=300)
        self.assertEqual(cfg.backend, "redis")
        self.assertEqual(cfg.ttl_seconds, 300)


class CacheInvalidationStrategyTests(unittest.TestCase):
    def test_enum_values_exist(self):
        self.assertEqual(CacheInvalidationStrategy.TTL.value, "ttl")
        self.assertEqual(CacheInvalidationStrategy.LRU.value, "lru")


class ResilientServiceTests(unittest.TestCase):
    def test_get_status_has_expected_keys(self):
        svc = ResilientService("test_svc")
        status = svc.get_status()
        for key in ("name", "circuit_breaker", "bulkhead", "cache"):
            self.assertIn(key, status)

    def test_name_stored(self):
        svc = ResilientService("my_service")
        self.assertEqual(svc.name, "my_service")

    def test_circuit_breaker_created(self):
        svc = ResilientService("svc")
        self.assertIsInstance(svc.circuit_breaker, CircuitBreaker)

    def test_cache_created(self):
        svc = ResilientService("svc")
        self.assertIsInstance(svc.cache, DistributedCache)

    def test_bulkhead_created(self):
        svc = ResilientService("svc")
        self.assertIsInstance(svc.bulkhead, BulkheadPolicy)


class ResilientServiceCallTests(unittest.IsolatedAsyncioTestCase):
    """Regression: the lambda wrapper returned an unawaited coroutine object."""

    async def test_call_returns_actual_result_not_coroutine(self):
        """call() must return the function's value, not a coroutine object."""
        import inspect
        svc = ResilientService("test_call")

        async def my_func():
            return 42

        result = await svc.call(my_func)
        self.assertEqual(result, 42)
        self.assertFalse(inspect.iscoroutine(result), "result must not be an unawaited coroutine")

    async def test_call_sync_func_returns_result(self):
        svc = ResilientService("test_sync")
        result = await svc.call(lambda: "hello")
        self.assertEqual(result, "hello")

    async def test_call_with_cache_hit_returns_cached_value(self):
        svc = ResilientService("test_cache")
        await svc.cache.set("ck", "cached_val")
        result = await svc.call(lambda: "live_val", cache_key="ck")
        self.assertEqual(result, "cached_val")

    async def test_call_stores_result_in_cache(self):
        svc = ResilientService("test_store")

        async def produce():
            return "produced"

        result = await svc.call(produce, cache_key="k1")
        self.assertEqual(result, "produced")
        cached = await svc.cache.get("k1")
        self.assertEqual(cached, "produced")


class ResilientServicePositionalArgsTests(unittest.IsolatedAsyncioTestCase):
    """Regression: *args appeared after cache_key/fallback defaults, so positional
    call args were absorbed by those parameters instead of being forwarded to func."""

    async def test_positional_args_forwarded_to_func(self):
        svc = ResilientService("args_fwd")

        async def add(a, b):
            return a + b

        result = await svc.call(add, 3, 4)
        self.assertEqual(result, 7, "positional args must reach the function, not cache_key/fallback")

    async def test_cache_key_still_works_as_keyword(self):
        svc = ResilientService("args_kw")
        await svc.cache.set("kw_key", "cached")
        result = await svc.call(lambda: "live", cache_key="kw_key")
        self.assertEqual(result, "cached")


class OpenCircuitCacheBypassTests(unittest.IsolatedAsyncioTestCase):
    """Regression: when circuit is OPEN, ResilientService.call used to return
    a stale cached value instead of raising CircuitBreakerOpenError."""

    async def test_open_circuit_bypasses_stale_cache(self):
        svc = ResilientService(
            "stale_bypass",
            circuit_breaker_config=CircuitBreakerConfig(failure_threshold=1),
        )

        async def always_fail():
            raise RuntimeError("downstream down")

        # Open the circuit via a call WITHOUT a cache_key so cache doesn't
        # intercept and mask the failure before it reaches the breaker.
        with self.assertRaises(RuntimeError):
            await svc.call(always_fail)

        # Pre-warm cache with a stale value after the circuit is already OPEN
        await svc.cache.set("stale_key", "stale_value")

        # Circuit is OPEN; must raise, not serve stale_value from cache
        with self.assertRaises(CircuitBreakerOpenError):
            await svc.call(always_fail, cache_key="stale_key")

    async def test_closed_circuit_still_uses_cache(self):
        """Sanity: cache hit must still work when circuit is CLOSED."""
        svc = ResilientService("closed_cache")
        await svc.cache.set("good_key", "cached_val")
        result = await svc.call(lambda: "live", cache_key="good_key")
        self.assertEqual(result, "cached_val")

    async def test_last_failure_time_set_inside_lock(self):
        """Regression: last_failure_time was written outside the lock, creating
        a TOCTOU race with _should_attempt_reset. Verify the attribute is set."""
        cb = CircuitBreaker("lft_test", CircuitBreakerConfig(failure_threshold=5))

        async def fail():
            raise ValueError("err")

        try:
            await cb.call(fail)
        except ValueError:
            pass

        self.assertIsNotNone(cb.last_failure_time)


if __name__ == "__main__":
    unittest.main()
