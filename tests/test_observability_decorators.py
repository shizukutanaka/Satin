"""
Regression tests: observability decorators must support async functions.

Bug: trace_operation / observe_metrics only had sync wrappers. Applied to an
`async def`, they called func(...) and got a coroutine -> returned it un-awaited
(so the caller got a coroutine, not the result), recorded ~0ms latency, and
never caught exceptions raised inside the coroutine.

Run: python -m unittest tests.test_observability_decorators -v
"""
import asyncio
import os
import sys
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import observability as obs  # noqa: E402
from observability import trace_operation, observe_metrics  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class AsyncTraceOperationTests(unittest.TestCase):
    def test_async_function_result_is_awaited(self):
        @trace_operation("op")
        async def add(a, b):
            await asyncio.sleep(0)
            return a + b

        result = run(add(2, 3))
        # Must be the value, not a coroutine.
        self.assertEqual(result, 5)

    def test_async_latency_is_recorded_and_reflects_real_duration(self):
        @trace_operation("slow_op")
        async def slow():
            await asyncio.sleep(0.02)
            return "done"

        self.assertEqual(run(slow()), "done")
        samples = obs.global_metrics.operation_latencies.get("slow_op", [])
        self.assertTrue(samples, "no latency sample recorded for async op")
        # The recorded latency must reflect the awaited 20ms, not ~0ms (the old
        # sync wrapper timed only coroutine creation).
        self.assertGreaterEqual(max(samples), 15.0)

    def test_async_exception_propagates_and_is_recorded(self):
        @trace_operation("boom")
        async def boom():
            await asyncio.sleep(0)
            raise ValueError("kaboom")

        with self.assertRaises(ValueError):
            run(boom())

    def test_sync_function_still_works(self):
        @trace_operation("sync_op")
        def mul(a, b):
            return a * b

        self.assertEqual(mul(4, 5), 20)


class AsyncObserveMetricsTests(unittest.TestCase):
    def test_async_result_awaited(self):
        @observe_metrics("op2")
        async def echo(x):
            await asyncio.sleep(0)
            return x

        self.assertEqual(run(echo("hi")), "hi")

    def test_async_exception_propagates(self):
        @observe_metrics("op3")
        async def boom():
            raise RuntimeError("x")

        with self.assertRaises(RuntimeError):
            run(boom())

    def test_sync_still_works(self):
        @observe_metrics("op4")
        def f():
            return 42

        self.assertEqual(f(), 42)


if __name__ == "__main__":
    unittest.main()
