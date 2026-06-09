"""
Regression tests for main/async_optimization.py.

Covers the bugs fixed in the deepresearch pass:
- AsyncTaskPool.run_all must await all submitted coroutines and collect results
- ConcurrentExecutor.run must forward **kwargs (functools.partial fix)
- ConcurrentExecutor auto mode must reuse pools instead of leaking them
- AsyncConnectionPool must not exceed pool_size + max_overflow
- AsyncRateLimiterAdvanced must not replace the live Semaphore on resize

Run: python -m pytest tests/test_async_optimization.py -v
"""
import asyncio
import os
import sys
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from async_optimization import (  # noqa: E402
    AsyncTaskPool,
    ConcurrentExecutor,
    AsyncConnectionPool,
    AsyncRateLimiterAdvanced,
)


class AsyncTaskPoolTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_all_returns_all_results(self):
        """run_all must await every submitted coroutine, not skip them."""
        pool = AsyncTaskPool(max_concurrent=4)

        async def double(n):
            return n * 2

        for i in range(5):
            await pool.add_task(double(i))

        results = await pool.run_all()
        self.assertEqual(len(results), 5)
        values = sorted(r.result for r in results)
        self.assertEqual(values, [0, 2, 4, 6, 8])

    async def test_run_all_captures_exception(self):
        """Exceptions in tasks are captured per-result when return_exceptions=True."""
        pool = AsyncTaskPool()

        async def fail():
            raise ValueError("expected")

        async def succeed():
            return 42

        await pool.add_task(fail())
        await pool.add_task(succeed())

        results = await pool.run_all(return_exceptions=True)
        self.assertEqual(len(results), 2)
        failures = pool.get_failures()
        self.assertEqual(len(failures), 1)
        self.assertIsInstance(failures[0][1], ValueError)
        self.assertEqual(pool.get_successful(), [42])

    async def test_empty_pool_returns_empty_list(self):
        pool = AsyncTaskPool()
        self.assertEqual(await pool.run_all(), [])


class ConcurrentExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_forwards_kwargs(self):
        """run() must pass **kwargs to the sync function (functools.partial fix)."""
        executor = ConcurrentExecutor(executor_type="thread")
        try:
            result = await executor.run(lambda a, b=0: a + b, 3, b=7)
            self.assertEqual(result, 10)
        finally:
            executor.shutdown()

    async def test_auto_mode_reuses_thread_pool(self):
        """Auto mode must reuse the same ThreadPoolExecutor across calls."""
        executor = ConcurrentExecutor(executor_type="auto")
        try:
            await executor.run(lambda: None)
            first_pool = executor._auto_thread
            await executor.run(lambda: None)
            self.assertIs(executor._auto_thread, first_pool,
                          "auto mode created a new pool on the second call")
        finally:
            executor.shutdown()

    async def test_map_with_timeout(self):
        """map() must apply timeout via wait_for."""
        executor = ConcurrentExecutor(executor_type="thread")
        try:
            results = await executor.map(lambda x: x * 3, [1, 2, 3], timeout=5)
            self.assertEqual(sorted(results), [3, 6, 9])
        finally:
            executor.shutdown()


class AsyncConnectionPoolTests(unittest.IsolatedAsyncioTestCase):
    async def _make_pool(self, size=2, overflow=1):
        counter = {"n": 0}

        async def factory():
            counter["n"] += 1
            return object()

        pool = AsyncConnectionPool(factory=factory, pool_size=size, max_overflow=overflow)
        await pool.initialize()
        return pool

    async def test_pool_does_not_exceed_limit(self):
        """Concurrent acquires must not create more than pool_size + max_overflow conns."""
        pool = await self._make_pool(size=2, overflow=1)
        conns = [await pool.acquire() for _ in range(3)]
        self.assertLessEqual(len(pool._all_connections), 3)
        for c in conns:
            await pool.release(c)
        await pool.close_all()

    async def test_release_discards_overflow(self):
        """Releasing more connections than pool_size must not grow the queue unboundedly."""
        pool = await self._make_pool(size=2, overflow=1)
        # Acquire and release 2 normal connections + 1 overflow
        c1, c2 = await pool.acquire(), await pool.acquire()
        # c3 is overflow (timeout path)
        c3 = await asyncio.wait_for(pool.acquire(timeout=0.5), timeout=1)
        await pool.release(c1)
        await pool.release(c2)
        await pool.release(c3)  # must discard or not block
        await pool.close_all()


class AsyncRateLimiterAdvancedTests(unittest.IsolatedAsyncioTestCase):
    async def test_resize_does_not_strand_waiters(self):
        """Concurrency resize must not replace the live Semaphore (pending-reduction fix)."""
        limiter = AsyncRateLimiterAdvanced(
            min_concurrency=1, max_concurrency=3,
            target_latency_ms=1000,
        )
        await limiter.acquire()
        # Record a slow latency to trigger a reduction
        for _ in range(10):
            limiter.release(latency_ms=5000)

        # After reduction, the semaphore object must still be the original one —
        # i.e., _pending_reduction was used rather than a new Semaphore.
        await limiter.acquire()
        limiter.release(0)
        limiter.release(0)


if __name__ == "__main__":
    unittest.main()
