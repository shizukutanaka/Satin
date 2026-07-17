"""
Stdlib-only regression tests for the Tier-1 fixes in main/circuit_breaker_cache.py.

Run: python -m unittest tests.test_circuit_breaker -v
"""
import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main.circuit_breaker_cache import (  # noqa: E402
    CircuitBreaker, CircuitBreakerConfig, CircuitState, CircuitBreakerOpenError,
)


async def _fail():
    raise RuntimeError("boom")


async def _ok():
    return "ok"


class CircuitBreakerTests(unittest.TestCase):
    def test_opens_after_threshold_then_recovers_with_clean_counts(self):
        async def scenario():
            cfg = CircuitBreakerConfig()
            cfg.failure_threshold = 3
            cfg.success_threshold = 2
            cfg.timeout_seconds = 0  # allow immediate half-open
            cb = CircuitBreaker("t", cfg)

            # 3 failures -> OPEN
            for _ in range(3):
                with self.assertRaises(RuntimeError):
                    await cb.call(_fail)
            self.assertEqual(cb.state, CircuitState.OPEN)

            # next call probes (timeout=0 -> HALF_OPEN); failure_count reset on entry
            with self.assertRaises(RuntimeError):
                await cb.call(_fail)  # half-open probe fails -> back to OPEN
            self.assertEqual(cb.state, CircuitState.OPEN)

            # recover: success_threshold successes -> CLOSED with counts cleared
            await cb.call(_ok)
            await cb.call(_ok)
            self.assertEqual(cb.state, CircuitState.CLOSED)
            self.assertEqual(cb.failure_count, 0)
            self.assertEqual(cb.success_count, 0)
        asyncio.run(scenario())

    def test_half_open_failure_resets_success_count(self):
        async def scenario():
            cfg = CircuitBreakerConfig()
            cfg.failure_threshold = 1
            cfg.success_threshold = 3
            cfg.timeout_seconds = 0
            cb = CircuitBreaker("t2", cfg)

            with self.assertRaises(RuntimeError):
                await cb.call(_fail)  # -> OPEN
            await cb.call(_ok)        # half-open probe success (success_count=1)
            self.assertEqual(cb.state, CircuitState.HALF_OPEN)
            self.assertEqual(cb.success_count, 1)
            with self.assertRaises(RuntimeError):
                await cb.call(_fail)  # half-open failure -> OPEN, success_count reset
            self.assertEqual(cb.state, CircuitState.OPEN)
            self.assertEqual(cb.success_count, 0)
        asyncio.run(scenario())

    def test_closed_stays_closed_below_threshold(self):
        async def scenario():
            cfg = CircuitBreakerConfig()
            cfg.failure_threshold = 5
            cb = CircuitBreaker("t3", cfg)
            with self.assertRaises(RuntimeError):
                await cb.call(_fail)
            await cb.call(_ok)  # success resets failure_count in CLOSED
            self.assertEqual(cb.failure_count, 0)
            self.assertEqual(cb.state, CircuitState.CLOSED)
        asyncio.run(scenario())


class FallbackTests(unittest.TestCase):
    def _tripped(self):
        cfg = CircuitBreakerConfig()
        cfg.failure_threshold = 2
        cfg.timeout_seconds = 999.0  # won't expire in test
        cb = CircuitBreaker("fb", cfg)
        for _ in range(2):
            try:
                asyncio.run(cb.call(_fail))
            except Exception:
                pass
        return cb

    def test_open_circuit_uses_fallback(self):
        cb = self._tripped()
        result = asyncio.run(cb.call(_ok, fallback=lambda: "fallback"))
        self.assertEqual(result, "fallback")

    def test_open_circuit_raises_without_fallback(self):
        cb = self._tripped()
        with self.assertRaises(CircuitBreakerOpenError) as ctx:
            asyncio.run(cb.call(_ok))
        self.assertIn("OPEN", str(ctx.exception))

    def test_rejected_increments_metrics(self):
        cb = self._tripped()
        before = cb.metrics.rejected_calls
        try:
            asyncio.run(cb.call(_ok))
        except Exception:
            pass
        self.assertGreater(cb.metrics.rejected_calls, before)


class MetricsTests(unittest.TestCase):
    def test_successful_call_updates_metrics(self):
        cb = CircuitBreaker("m", CircuitBreakerConfig())
        asyncio.run(cb.call(_ok))
        m = cb.get_metrics()
        self.assertEqual(m["total_calls"], 1)
        self.assertEqual(m["successful_calls"], 1)
        self.assertEqual(m["failed_calls"], 0)

    def test_failed_call_updates_metrics(self):
        cb = CircuitBreaker("m2", CircuitBreakerConfig())
        try:
            asyncio.run(cb.call(_fail))
        except Exception:
            pass
        m = cb.get_metrics()
        self.assertEqual(m["total_calls"], 1)
        self.assertEqual(m["failed_calls"], 1)

    def test_metrics_dict_keys(self):
        cb = CircuitBreaker("m3", CircuitBreakerConfig())
        m = cb.get_metrics()
        for key in ("total_calls", "successful_calls", "failed_calls", "rejected_calls"):
            self.assertIn(key, m)

    def test_initial_state_is_closed(self):
        cb = CircuitBreaker("init", CircuitBreakerConfig())
        self.assertEqual(cb.get_state(), CircuitState.CLOSED.value)

    def test_sync_callable_is_supported(self):
        cb = CircuitBreaker("sync", CircuitBreakerConfig())
        result = asyncio.run(cb.call(lambda: "sync_result"))
        self.assertEqual(result, "sync_result")


if __name__ == "__main__":
    unittest.main()
