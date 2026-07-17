"""
Regression test for TokenBucketRateLimiter in async_integrator.py.

The bug: acquire() held self.lock across `await asyncio.sleep(...)`, so a
coroutine waiting for tokens blocked every other coroutine from refilling or
acquiring — fully serializing the limiter. The fix computes wait_time under the
lock but sleeps after releasing it.

Run: python -m unittest tests.test_async_integrator_ratelimiter -v
"""
import asyncio
import inspect
import os
import sys
import time
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import async_integrator as ai  # noqa: E402


class TokenBucketRateLimiterTests(unittest.TestCase):
    def test_concurrent_acquires_not_serialized(self):
        async def run():
            rl = ai.TokenBucketRateLimiter(rate_per_second=20.0, burst_size=4)
            start = time.time()
            # 8 concurrent acquires: 4 from burst, 4 more requiring refill.
            await asyncio.gather(*[rl.acquire() for _ in range(8)])
            return time.time() - start

        elapsed = asyncio.run(run())
        # If the lock were held during sleep, the refills would serialize and
        # take noticeably longer. Concurrent behaviour completes well under 1s.
        self.assertLess(elapsed, 1.0)

    def test_sleep_is_outside_lock(self):
        # Static guard: the `await asyncio.sleep` line must not be indented
        # under the `async with self.lock:` block.
        src = inspect.getsource(ai.TokenBucketRateLimiter.acquire)
        lines = src.splitlines()
        lock_indent = None
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("async with self.lock"):
                lock_indent = len(line) - len(line.lstrip())
            elif "asyncio.sleep" in stripped and lock_indent is not None:
                sleep_indent = len(line) - len(line.lstrip())
                # sleep must be at or shallower than the lock's own indent
                # (i.e. dedented out of the with-block)
                self.assertLessEqual(
                    sleep_indent, lock_indent,
                    "asyncio.sleep is still inside the lock block",
                )

    def test_acquire_consumes_tokens(self):
        async def run():
            rl = ai.TokenBucketRateLimiter(rate_per_second=1000.0, burst_size=10)
            before = rl.tokens
            await rl.acquire(3)
            return before, rl.tokens

        before, after = asyncio.run(run())
        self.assertAlmostEqual(before, 10)
        self.assertLessEqual(after, 7.5)  # ~3 consumed (minor refill tolerance)


if __name__ == "__main__":
    unittest.main()
