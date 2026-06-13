"""
Unit tests for async_integrator — AsyncRetryConfig.calculate_delay and
TokenBucketRateLimiter (the non-network parts that are pure computation).
"""
import asyncio
import os
import sys
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from async_integrator import AsyncRetryConfig, TokenBucketRateLimiter  # noqa: E402


class AsyncRetryConfigTests(unittest.TestCase):
    def test_attempt_zero_returns_initial_delay(self):
        cfg = AsyncRetryConfig(initial_delay=1.0, max_delay=60.0, jitter=False)
        self.assertAlmostEqual(cfg.calculate_delay(0), 1.0)

    def test_exponential_growth(self):
        cfg = AsyncRetryConfig(initial_delay=1.0, max_delay=60.0,
                               exponential_base=2.0, jitter=False)
        self.assertAlmostEqual(cfg.calculate_delay(1), 2.0)
        self.assertAlmostEqual(cfg.calculate_delay(2), 4.0)

    def test_capped_at_max_delay(self):
        cfg = AsyncRetryConfig(initial_delay=1.0, max_delay=10.0,
                               exponential_base=2.0, jitter=False)
        self.assertLessEqual(cfg.calculate_delay(10), 10.0)

    def test_jitter_stays_within_bounds(self):
        cfg = AsyncRetryConfig(initial_delay=1.0, max_delay=60.0, jitter=True)
        for _ in range(20):
            d = cfg.calculate_delay(0)
            self.assertGreaterEqual(d, 0.8)
            self.assertLessEqual(d, 1.2)

    def test_no_jitter(self):
        cfg = AsyncRetryConfig(initial_delay=2.0, max_delay=60.0,
                               exponential_base=3.0, jitter=False)
        self.assertAlmostEqual(cfg.calculate_delay(2), 18.0)

    def test_default_max_retries(self):
        cfg = AsyncRetryConfig()
        self.assertEqual(cfg.max_retries, 3)


class TokenBucketRateLimiterTests(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    def test_acquire_when_full_succeeds_quickly(self):
        limiter = TokenBucketRateLimiter(rate_per_second=100.0, burst_size=20)
        # Should not block since bucket starts full
        self._run(limiter.acquire(1))  # no exception = pass

    def test_acquire_decrements_tokens(self):
        limiter = TokenBucketRateLimiter(rate_per_second=100.0, burst_size=5)
        self._run(limiter.acquire(3))
        self.assertLessEqual(limiter.tokens, 3.0)  # at most 2 remaining (slight refill ok)

    def test_multiple_acquires_succeed_within_burst(self):
        limiter = TokenBucketRateLimiter(rate_per_second=100.0, burst_size=10)
        for _ in range(3):
            self._run(limiter.acquire(1))


if __name__ == "__main__":
    unittest.main()
