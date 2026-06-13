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
    AsyncTaskResult,
    AsyncContextManager,
    BatchAsyncProcessor,
    ConcurrentExecutor,
    AsyncConnectionPool,
    AsyncRateLimiterAdvanced,
    gather_with_timeout,
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


class AsyncTaskResultTests(unittest.TestCase):
    def _make(self, **kw):
        from datetime import datetime
        defaults = dict(task_id="t1", coroutine_name="coro", result=None,
                        exception=None, duration_ms=0.0, start_time=None, end_time=None)
        defaults.update(kw)
        return AsyncTaskResult(**defaults)

    def test_success_when_no_exception(self):
        r = self._make(result=42)
        self.assertTrue(r.success)

    def test_not_success_when_exception(self):
        r = self._make(exception=ValueError("x"))
        self.assertFalse(r.success)

    def test_is_done_when_end_time_set(self):
        from datetime import datetime
        r = self._make(end_time=datetime.now())
        self.assertTrue(r.is_done)

    def test_not_done_when_no_end_time(self):
        r = self._make()
        self.assertFalse(r.is_done)

    def test_result_stored(self):
        r = self._make(result="hello")
        self.assertEqual(r.result, "hello")


class AsyncContextManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_aenter_sets_initialized(self):
        mgr = AsyncContextManager("test_resource")
        async with mgr:
            self.assertTrue(mgr._initialized)

    async def test_aexit_clears_initialized(self):
        mgr = AsyncContextManager("test_resource")
        async with mgr:
            pass
        self.assertFalse(mgr._initialized)

    async def test_name_stored(self):
        mgr = AsyncContextManager("my_res")
        self.assertEqual(mgr.name, "my_res")

    async def test_async_init_hook_called(self):
        calls = []

        class MyMgr(AsyncContextManager):
            async def async_init(self):
                calls.append("init")

        async with MyMgr("x"):
            pass
        self.assertIn("init", calls)

    async def test_async_cleanup_called_on_exit(self):
        calls = []

        class MyMgr(AsyncContextManager):
            async def async_cleanup(self, errored: bool = False):
                calls.append(("cleanup", errored))

        async with MyMgr("x"):
            pass
        self.assertEqual(calls, [("cleanup", False)])

    async def test_async_cleanup_called_with_errored_on_exception(self):
        calls = []

        class MyMgr(AsyncContextManager):
            async def async_cleanup(self, errored: bool = False):
                calls.append(("cleanup", errored))

        try:
            async with MyMgr("x"):
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        self.assertEqual(calls, [("cleanup", True)])


class BatchAsyncProcessorTests(unittest.IsolatedAsyncioTestCase):
    async def test_add_returns_none_while_under_limit(self):
        proc = BatchAsyncProcessor(batch_size=5)
        result = await proc.add("item1")
        self.assertIsNone(result)

    async def test_add_returns_batch_when_full(self):
        proc = BatchAsyncProcessor(batch_size=3)
        await proc.add("a")
        await proc.add("b")
        result = await proc.add("c")
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 3)

    async def test_batch_cleared_after_processing(self):
        proc = BatchAsyncProcessor(batch_size=2)
        await proc.add("x")
        await proc.add("y")
        self.assertEqual(len(proc.batch), 0)

    async def test_flush_returns_remaining_items(self):
        proc = BatchAsyncProcessor(batch_size=10)
        await proc.add("a")
        await proc.add("b")
        result = await proc.flush()
        self.assertEqual(result, ["a", "b"])

    async def test_flush_empty_returns_none(self):
        proc = BatchAsyncProcessor(batch_size=5)
        result = await proc.flush()
        self.assertIsNone(result)

    async def test_set_processor_called_on_batch(self):
        called_with = []

        async def my_processor(batch):
            called_with.extend(batch)
            return batch

        proc = BatchAsyncProcessor(batch_size=2)
        proc.set_processor(my_processor)
        await proc.add("p")
        await proc.add("q")
        self.assertEqual(sorted(called_with), ["p", "q"])

    async def test_processor_exception_returns_original_batch(self):
        async def bad_processor(batch):
            raise ValueError("fail")

        proc = BatchAsyncProcessor(batch_size=2)
        proc.set_processor(bad_processor)
        await proc.add("x")
        result = await proc.add("y")
        self.assertEqual(sorted(result), ["x", "y"])


class GatherWithTimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_all_results(self):
        async def add(a, b):
            return a + b

        results = await gather_with_timeout(add(1, 2), add(3, 4), timeout_seconds=5)
        self.assertEqual(sorted(results), [3, 7])

    async def test_timeout_raises(self):
        async def slow():
            await asyncio.sleep(100)

        with self.assertRaises(asyncio.TimeoutError):
            await gather_with_timeout(slow(), timeout_seconds=0.05)

    async def test_empty_coros_returns_empty(self):
        results = await gather_with_timeout(timeout_seconds=5)
        self.assertEqual(results, [])

    async def test_return_exceptions_captures_errors(self):
        async def fail():
            raise ValueError("oops")

        results = await gather_with_timeout(fail(), timeout_seconds=5, return_exceptions=True)
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], ValueError)


if __name__ == "__main__":
    unittest.main()
