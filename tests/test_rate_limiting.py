"""
Stdlib-only regression tests for the Tier-1 fixes in main/advanced_rate_limiting.py.

Run: python -m unittest tests.test_rate_limiting -v
"""
import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main.advanced_rate_limiting import (  # noqa: E402
    TokenBucketLimiter, LeakyBucketLimiter, SlidingWindowLimiter, AdaptiveRateLimiter,
)


class RateLimiterValidationTests(unittest.TestCase):
    def test_zero_rate_rejected_no_divzero(self):
        # Previously refill_rate=0 / leak_rate=0 crashed later with ZeroDivisionError.
        with self.assertRaises(ValueError):
            TokenBucketLimiter(capacity=10, refill_rate=0)
        with self.assertRaises(ValueError):
            LeakyBucketLimiter(leak_rate=0)
        with self.assertRaises(ValueError):
            SlidingWindowLimiter(max_requests=5, window_seconds=0)

    def test_token_bucket_basic_acquire(self):
        async def scenario():
            tb = TokenBucketLimiter(capacity=2, refill_rate=1)
            self.assertTrue(await tb.acquire(1))
            self.assertTrue(await tb.acquire(1))
            status = await tb.check_rate_limit(1)
            self.assertFalse(status.allowed)  # bucket drained
        asyncio.run(scenario())

    def test_adaptive_keeps_same_limiter_object(self):
        async def scenario():
            arl = AdaptiveRateLimiter(initial_rate=10.0)
            before = arl.limiter
            await arl.record_failure()  # triggers a back-off rate update
            after = arl.limiter
            self.assertIs(before, after)  # object is mutated, not replaced
            self.assertAlmostEqual(after.refill_rate, arl.current_rate)
        asyncio.run(scenario())

    def test_update_rate_mutates_in_place(self):
        async def scenario():
            tb = TokenBucketLimiter(capacity=20, refill_rate=10)
            await tb.update_rate(5, capacity=10)
            self.assertEqual(tb.refill_rate, 5)
            self.assertEqual(tb.capacity, 10)
            self.assertLessEqual(tb.tokens, 10)
            with self.assertRaises(ValueError):
                await tb.update_rate(0)
        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
