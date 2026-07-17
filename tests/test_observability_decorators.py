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


class TraceOperationSpanExportTests(unittest.TestCase):
    """Regression: trace_operation() created a throwaway `TraceProvider()`
    inside the wrapper on every call. The span was started and ended on that
    instance, then the instance was discarded — spans never accumulated
    anywhere and ObservabilityExporter (which reads from a TraceProvider
    instance) could never see them.

    Fix: decorators now write to a shared `global_trace_provider` singleton,
    mirroring the existing `global_metrics` singleton pattern.
    """

    def setUp(self):
        obs.global_trace_provider.spans.clear()
        obs.global_trace_provider.active_span_stack.clear()

    def test_sync_call_span_is_recorded_in_global_trace_provider(self):
        @trace_operation("exportable_sync_op")
        def add(a, b):
            return a + b

        self.assertEqual(add(2, 3), 5)
        traces = obs.global_trace_provider.get_traces()
        all_ops = [span["operation_name"] for spans in traces.values() for span in spans]
        self.assertIn(
            "exportable_sync_op", all_ops,
            "Span from a decorated sync call must be visible in "
            "global_trace_provider.get_traces() (old bug: throwaway TraceProvider "
            "instance per call meant spans were never accumulated).",
        )

    def test_async_call_span_is_recorded_in_global_trace_provider(self):
        @trace_operation("exportable_async_op")
        async def echo(x):
            await asyncio.sleep(0)
            return x

        self.assertEqual(run(echo("hi")), "hi")
        traces = obs.global_trace_provider.get_traces()
        all_ops = [span["operation_name"] for spans in traces.values() for span in spans]
        self.assertIn("exportable_async_op", all_ops)

    def test_span_status_ok_recorded_on_success(self):
        @trace_operation("status_ok_op")
        def f():
            return 1

        f()
        traces = obs.global_trace_provider.get_traces()
        spans = [s for spans in traces.values() for s in spans if s["operation_name"] == "status_ok_op"]
        self.assertTrue(spans)
        self.assertEqual(spans[-1]["status"], "OK")

    def test_span_status_error_recorded_on_exception(self):
        @trace_operation("status_error_op")
        def f():
            raise ValueError("boom")

        with self.assertRaises(ValueError):
            f()
        traces = obs.global_trace_provider.get_traces()
        spans = [s for spans in traces.values() for s in spans if s["operation_name"] == "status_error_op"]
        self.assertTrue(spans)
        self.assertEqual(spans[-1]["status"], "ERROR")

    def test_active_span_stack_does_not_leak_across_calls(self):
        """Regression: decorators called span.end() directly instead of
        trace_provider.end_span(span_id, ...), so active_span_stack was never
        popped. With a persistent global provider (post-fix), this would leak
        an entry per call forever if not fixed alongside the singleton change."""
        @trace_operation("stack_leak_op")
        def f():
            return 1

        for _ in range(20):
            f()

        self.assertEqual(
            len(obs.global_trace_provider.active_span_stack), 0,
            "active_span_stack must be empty after all spans complete; "
            "old bug: span.end() bypassed trace_provider.end_span(), leaving "
            "stale span_ids on the stack forever with a persistent provider.",
        )


if __name__ == "__main__":
    unittest.main()
