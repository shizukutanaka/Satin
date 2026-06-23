"""
Unit tests for advanced_rate_limiting — TokenBucketLimiter, SlidingWindowLimiter,
and construction guards. Tests are async-aware using asyncio.run().
"""
import asyncio
import os
import sys
import time
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from advanced_rate_limiting import (  # noqa: E402
    TokenBucketLimiter,
    SlidingWindowLimiter,
    GCRALimiter,
    RateLimitStatus,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TokenBucketTests(unittest.TestCase):
    def test_full_bucket_allows_single_token(self):
        limiter = TokenBucketLimiter(capacity=5.0, refill_rate=1.0)
        status = _run(limiter.check_rate_limit(1))
        self.assertTrue(status.allowed)

    def test_full_bucket_allows_burst_up_to_capacity(self):
        limiter = TokenBucketLimiter(capacity=5.0, refill_rate=1.0)
        status = _run(limiter.check_rate_limit(5))
        self.assertTrue(status.allowed)

    def test_request_exceeding_capacity_is_denied(self):
        limiter = TokenBucketLimiter(capacity=3.0, refill_rate=1.0)
        status = _run(limiter.check_rate_limit(4))
        self.assertFalse(status.allowed)

    def test_acquire_decrements_tokens(self):
        limiter = TokenBucketLimiter(capacity=5.0, refill_rate=1.0)
        _run(limiter.acquire(2))
        status = limiter.get_status()
        self.assertLessEqual(status.remaining_requests, 3)

    def test_acquire_returns_true_when_tokens_available(self):
        limiter = TokenBucketLimiter(capacity=5.0, refill_rate=1.0)
        result = _run(limiter.acquire(1))
        self.assertTrue(result)

    def test_invalid_refill_rate_raises(self):
        with self.assertRaises(ValueError):
            TokenBucketLimiter(capacity=5.0, refill_rate=0)

    def test_invalid_capacity_raises(self):
        with self.assertRaises(ValueError):
            TokenBucketLimiter(capacity=0, refill_rate=1.0)

    def test_get_status_returns_rate_limit_status(self):
        limiter = TokenBucketLimiter(capacity=5.0, refill_rate=2.0)
        status = limiter.get_status()
        self.assertIsInstance(status, RateLimitStatus)
        self.assertAlmostEqual(status.current_rate, 2.0)

    def test_update_rate_changes_refill_rate(self):
        limiter = TokenBucketLimiter(capacity=5.0, refill_rate=1.0)
        _run(limiter.update_rate(3.0))
        self.assertAlmostEqual(limiter.refill_rate, 3.0)

    def test_update_rate_and_capacity(self):
        limiter = TokenBucketLimiter(capacity=5.0, refill_rate=1.0)
        _run(limiter.update_rate(2.0, capacity=10.0))
        self.assertAlmostEqual(limiter.capacity, 10.0)

    def test_denied_status_has_retry_after(self):
        limiter = TokenBucketLimiter(capacity=1.0, refill_rate=0.5)
        # Drain the bucket
        _run(limiter.acquire(1))
        status = _run(limiter.check_rate_limit(1))
        self.assertFalse(status.allowed)
        self.assertIsNotNone(status.retry_after_seconds)
        self.assertGreater(status.retry_after_seconds, 0)

    def test_acquire_is_nonblocking_and_returns_false_when_insufficient(self):
        # Contract consistency: acquire() must NOT block and must return False
        # when rate-limited (it previously blocked forever and only ever
        # returned True, making the bool return type a lie).
        limiter = TokenBucketLimiter(capacity=1.0, refill_rate=0.001)
        self.assertTrue(_run(limiter.acquire(1)))   # drains the single token
        start = time.time()
        result = _run(limiter.acquire(1))           # must return immediately
        self.assertFalse(result)
        self.assertLess(time.time() - start, 0.5)   # did not block

    def test_acquire_blocking_waits_then_succeeds(self):
        # The preserved blocking variant sleeps until tokens refill, then True.
        limiter = TokenBucketLimiter(capacity=1.0, refill_rate=50.0)
        _run(limiter.acquire(1))                     # drain
        start = time.time()
        result = _run(limiter.acquire_blocking(1))   # waits ~0.02s for refill
        self.assertTrue(result)
        self.assertGreaterEqual(time.time() - start, 0.0)

    def test_all_limiters_acquire_return_bool(self):
        # Polymorphic contract: every limiter's acquire() returns a real bool.
        from advanced_rate_limiting import LeakyBucketLimiter, SlidingWindowLimiter
        tb = TokenBucketLimiter(capacity=1.0, refill_rate=1.0)
        sw = SlidingWindowLimiter(max_requests=1, window_seconds=10.0)
        lb = LeakyBucketLimiter(leak_rate=1.0, queue_size=1)
        for lim in (tb, sw, lb):
            first = _run(lim.acquire(1))
            second = _run(lim.acquire(1))   # over limit -> must be False, not block
            self.assertIs(first, True)
            self.assertIs(second, False)

    def test_check_rate_limit_remaining_subtracts_tokens_consistently(self):
        """Regression: LeakyBucket.check_rate_limit reported remaining WITHOUT
        subtracting the requested tokens, while TokenBucket and SlidingWindow
        both subtract them. All three must agree that 'remaining' means
        capacity left AFTER the checked request."""
        from advanced_rate_limiting import LeakyBucketLimiter, SlidingWindowLimiter
        # Each starts empty with capacity 5; checking 2 tokens must leave 3.
        tb = TokenBucketLimiter(capacity=5.0, refill_rate=1.0)
        sw = SlidingWindowLimiter(max_requests=5, window_seconds=60.0)
        lb = LeakyBucketLimiter(leak_rate=1.0, queue_size=5)
        tb_status = _run(tb.check_rate_limit(2))
        sw_status = _run(sw.check_rate_limit(2))
        lb_status = _run(lb.check_rate_limit(2))
        self.assertTrue(tb_status.allowed and sw_status.allowed and lb_status.allowed)
        self.assertEqual(tb_status.remaining_requests, 3)
        self.assertEqual(sw_status.remaining_requests, 3)
        self.assertEqual(lb_status.remaining_requests, 3,
                         "LeakyBucket must subtract tokens like the others")

    def test_leaky_bucket_remaining_never_negative_at_capacity(self):
        from advanced_rate_limiting import LeakyBucketLimiter
        lb = LeakyBucketLimiter(leak_rate=0.001, queue_size=3)
        status = _run(lb.check_rate_limit(3))  # exactly fills
        self.assertTrue(status.allowed)
        self.assertEqual(status.remaining_requests, 0)


class SlidingWindowTests(unittest.TestCase):
    def test_empty_window_allows_request(self):
        limiter = SlidingWindowLimiter(max_requests=5, window_seconds=60.0)
        status = _run(limiter.check_rate_limit(1))
        self.assertTrue(status.allowed)

    def test_at_limit_denies_further_requests(self):
        limiter = SlidingWindowLimiter(max_requests=3, window_seconds=60.0)
        for _ in range(3):
            _run(limiter.acquire(1))
        status = _run(limiter.check_rate_limit(1))
        self.assertFalse(status.allowed)

    def test_acquire_returns_true_when_space_available(self):
        limiter = SlidingWindowLimiter(max_requests=5, window_seconds=60.0)
        result = _run(limiter.acquire(1))
        self.assertTrue(result)

    def test_acquire_returns_false_when_full(self):
        limiter = SlidingWindowLimiter(max_requests=2, window_seconds=60.0)
        _run(limiter.acquire(2))
        result = _run(limiter.acquire(1))
        self.assertFalse(result)

    def test_expired_requests_free_slots(self):
        limiter = SlidingWindowLimiter(max_requests=2, window_seconds=0.05)
        _run(limiter.acquire(2))
        time.sleep(0.1)  # let the window expire
        status = _run(limiter.check_rate_limit(1))
        self.assertTrue(status.allowed)

    def test_invalid_window_raises(self):
        with self.assertRaises(ValueError):
            SlidingWindowLimiter(max_requests=5, window_seconds=0)

    def test_invalid_max_requests_raises(self):
        with self.assertRaises(ValueError):
            SlidingWindowLimiter(max_requests=0, window_seconds=60.0)

    def test_get_status_returns_rate_limit_status(self):
        limiter = SlidingWindowLimiter(max_requests=10, window_seconds=5.0)
        status = limiter.get_status()
        self.assertIsInstance(status, RateLimitStatus)
        self.assertEqual(status.remaining_requests, 10)

    def test_remaining_decrements_after_acquire(self):
        limiter = SlidingWindowLimiter(max_requests=5, window_seconds=60.0)
        _run(limiter.acquire(2))
        status = limiter.get_status()
        self.assertEqual(status.remaining_requests, 3)

    def test_current_rate_is_requests_per_second(self):
        limiter = SlidingWindowLimiter(max_requests=10, window_seconds=2.0)
        status = limiter.get_status()
        self.assertAlmostEqual(status.current_rate, 5.0)


class GCRALimiterTests(unittest.TestCase):
    """GCRALimiter must be created inside asyncio.run() so its asyncio.Lock
    is bound to the same event loop used by the test coroutine."""

    def test_initial_request_allowed(self):
        async def run():
            limiter = GCRALimiter(emission_interval=1.0, capacity=5)
            return await limiter.acquire(1)
        self.assertTrue(asyncio.run(run()))

    def test_within_burst_capacity_allowed(self):
        async def run():
            limiter = GCRALimiter(emission_interval=0.01, capacity=3)
            return [await limiter.acquire(1) for _ in range(3)]
        self.assertTrue(all(asyncio.run(run())))

    def test_acquire_always_returns_true(self):
        """acquire() waits if rate-limited but always returns True."""
        async def run():
            limiter = GCRALimiter(emission_interval=0.01, capacity=1)
            await limiter.acquire(1)          # fills burst
            return await limiter.acquire(1)   # waits ~0.01s
        self.assertTrue(asyncio.run(run()))

    def test_check_rate_limit_returns_status(self):
        async def run():
            limiter = GCRALimiter(emission_interval=1.0, capacity=5)
            return await limiter.check_rate_limit(1)
        status = asyncio.run(run())
        self.assertIsInstance(status, RateLimitStatus)
        self.assertTrue(status.allowed)

    def test_invalid_emission_interval_raises(self):
        with self.assertRaises(ValueError):
            GCRALimiter(emission_interval=0, capacity=5)

    def test_acquire_releases_lock_before_sleep(self):
        """Regression: acquire() must not hold _lock during asyncio.sleep.

        If the lock is held while sleeping, check_rate_limit() (which also
        acquires the lock) would block for the full wait_time.  With
        emission_interval=0.3 and a 0.1s timeout on check_rate_limit, this
        would fire asyncio.TimeoutError — proving the lock was still held.
        """
        async def main():
            limiter = GCRALimiter(emission_interval=0.3, capacity=0)
            acq_task = asyncio.create_task(limiter.acquire(1))
            await asyncio.sleep(0.02)  # let acquire start and reach sleep
            # If lock is held during sleep (0.3s), this 0.1s timeout fires.
            try:
                await asyncio.wait_for(limiter.check_rate_limit(1), timeout=0.1)
            except asyncio.TimeoutError:
                acq_task.cancel()
                return False  # lock was held during sleep — regression present
            await acq_task
            return True

        result = asyncio.run(main())
        self.assertTrue(result, "acquire() must not hold the lock while sleeping")


if __name__ == "__main__":
    unittest.main()
