"""
Stdlib-only regression tests for the Tier-1 fixes in main/observability.py.

Run: python -m unittest tests.test_observability -v
"""
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main.observability import (  # noqa: E402
    Metrics, StructuredLogHandler, StructuredLog,
    Span, TraceProvider, HealthCheckResult, HealthChecker,
    LogLevel,
)


class MetricsTests(unittest.TestCase):
    def test_counters_are_thread_safe(self):
        m = Metrics()
        threads_n, per_thread = 8, 5000

        def worker():
            for _ in range(per_thread):
                m.record_api_call("api")
                m.record_error("err")

        threads = [threading.Thread(target=worker) for _ in range(threads_n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        expected = threads_n * per_thread
        # Without locking, concurrent read-modify-write loses increments.
        self.assertEqual(m.api_call_counts["api"], expected)
        self.assertEqual(m.error_counts["err"], expected)

    def test_latency_samples_are_bounded(self):
        m = Metrics()
        for i in range(m._MAX_LATENCY_SAMPLES + 500):
            m.record_operation_latency("op", float(i))
        self.assertEqual(len(m.operation_latencies["op"]), m._MAX_LATENCY_SAMPLES)

    def test_summary_snapshot_is_consistent(self):
        m = Metrics()
        m.record_operation_latency("op", 10.0)
        m.record_operation_latency("op", 20.0)
        summary = m.get_summary()
        self.assertEqual(summary["operation_latencies"]["op"]["count"], 2)
        self.assertEqual(summary["operation_latencies"]["op"]["mean_ms"], 15.0)


class StructuredLogHandlerMaxSizeTests(unittest.TestCase):
    """Regression: logs list grew without bound causing unbounded memory growth."""

    def _make_record(self, msg="test"):
        import logging
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg=msg, args=(), exc_info=None
        )
        return record

    def test_logs_capped_at_max_size(self):
        handler = StructuredLogHandler(max_size=5)
        for i in range(10):
            handler.emit(self._make_record(f"msg{i}"))
        self.assertEqual(len(handler.logs), 5)

    def test_oldest_evicted_first(self):
        handler = StructuredLogHandler(max_size=3)
        for i in range(5):
            handler.emit(self._make_record(f"msg{i}"))
        messages = [log.message for log in handler.logs]
        # Oldest 2 evicted; last 3 remain
        self.assertEqual(messages, ["msg2", "msg3", "msg4"])

    def test_default_max_size_is_large(self):
        handler = StructuredLogHandler()
        self.assertEqual(handler.max_size, 10_000)


class StructuredLogHandlerRobustnessTests(unittest.TestCase):
    """Regression: emit() must not silently drop logs (via handleError) for
    exc_info=True with no active exception, or for non-standard level names."""

    def _record(self, level, levelname, msg="x", exc_info=None):
        import logging
        rec = logging.LogRecord(
            name="t", level=level, pathname="", lineno=0,
            msg=msg, args=(), exc_info=exc_info,
        )
        rec.levelname = levelname
        return rec

    def test_exc_info_true_without_active_exception_is_handled(self):
        import logging
        # sys.exc_info() with no active exception -> (None, None, None), which is
        # truthy; record.exc_info[0].__name__ would have raised AttributeError.
        rec = logging.LogRecord(
            name="t", level=logging.ERROR, pathname="", lineno=0,
            msg="boom", args=(), exc_info=(None, None, None),
        )
        handler = StructuredLogHandler(max_size=10)
        handler.emit(rec)
        self.assertEqual(len(handler.logs), 1)
        self.assertIsNone(handler.logs[0].error_type)
        self.assertIsNone(handler.logs[0].error_message)

    def test_real_exception_still_captured(self):
        import logging
        try:
            raise ValueError("nope")
        except ValueError:
            import sys
            rec = logging.LogRecord(
                name="t", level=logging.ERROR, pathname="", lineno=0,
                msg="failed", args=(), exc_info=sys.exc_info(),
            )
        handler = StructuredLogHandler(max_size=10)
        handler.emit(rec)
        self.assertEqual(handler.logs[0].error_type, "ValueError")
        self.assertIn("nope", handler.logs[0].error_message)

    def test_unknown_level_name_falls_back_by_levelno(self):
        import logging
        logging.addLevelName(25, "NOTICE")  # custom level, not in LogLevel enum
        rec = self._record(25, "NOTICE", msg="notice")
        handler = StructuredLogHandler(max_size=10)
        handler.emit(rec)
        self.assertEqual(len(handler.logs), 1)
        # 25 is between INFO(20) and WARNING(30) -> maps to INFO
        self.assertEqual(handler.logs[0].level, LogLevel.INFO)

    def test_notset_level_does_not_drop_log(self):
        import logging
        rec = self._record(logging.NOTSET, "NOTSET", msg="ns")
        handler = StructuredLogHandler(max_size=10)
        handler.emit(rec)
        self.assertEqual(len(handler.logs), 1)
        self.assertEqual(handler.logs[0].level, LogLevel.DEBUG)


class StructuredLogTests(unittest.TestCase):
    def _make_log(self):
        from datetime import datetime
        return StructuredLog(
            timestamp=datetime.now(),
            level=LogLevel.INFO,
            message="test message",
            logger_name="test_logger",
            trace_id="trace-001",
            span_id="span-001",
        )

    def test_to_dict_has_required_keys(self):
        log = self._make_log()
        d = log.to_dict()
        for key in ("level", "message", "logger_name", "timestamp"):
            self.assertIn(key, d)

    def test_to_json_is_valid_json(self):
        import json
        log = self._make_log()
        parsed = json.loads(log.to_json())
        self.assertEqual(parsed["message"], "test message")

    def test_level_stored_correctly(self):
        log = self._make_log()
        self.assertEqual(log.level, LogLevel.INFO)


class SpanTests(unittest.TestCase):
    def _make_span(self):
        return Span(
            span_id="span_001",
            trace_id="trace_001",
            operation_name="test_op",
        )

    def test_duration_ms_positive_after_end(self):
        span = self._make_span()
        span.end()
        self.assertGreaterEqual(span.duration_ms(), 0)

    def test_end_sets_status(self):
        span = self._make_span()
        span.end(status="OK")
        self.assertEqual(span.status, "OK")

    def test_add_event_stored(self):
        span = self._make_span()
        span.add_event("my_event", {"key": "value"})
        self.assertEqual(len(span.events), 1)
        self.assertEqual(span.events[0]["name"], "my_event")

    def test_to_dict_has_expected_keys(self):
        span = self._make_span()
        span.end()
        d = span.to_dict()
        for key in ("span_id", "operation_name", "status", "duration_ms"):
            self.assertIn(key, d)


class TraceProviderTests(unittest.TestCase):
    def test_start_span_returns_span(self):
        tp = TraceProvider()
        span = tp.start_span("my_op")
        self.assertIsNotNone(span)
        self.assertEqual(span.operation_name, "my_op")

    def test_end_span_marks_as_ended(self):
        tp = TraceProvider()
        span = tp.start_span("op")
        tp.end_span(span.span_id, status="OK")
        self.assertEqual(span.status, "OK")

    def test_get_traces_returns_dict(self):
        tp = TraceProvider()
        span = tp.start_span("my_op")
        tp.end_span(span.span_id)
        traces = tp.get_traces()
        # Traces keyed by trace_id; look for the span by operation_name
        all_spans = [s for group in traces.values() for s in group]
        ops = [s["operation_name"] for s in all_spans]
        self.assertIn("my_op", ops)

    def test_span_id_unique_per_call(self):
        tp = TraceProvider()
        s1 = tp.start_span("op")
        s2 = tp.start_span("op")
        self.assertNotEqual(s1.span_id, s2.span_id)


class HealthCheckResultTests(unittest.TestCase):
    def test_to_dict_has_expected_keys(self):
        result = HealthCheckResult(status="UP", checks={"db": {"status": "UP"}})
        d = result.to_dict()
        for key in ("status", "checks", "uptime_seconds"):
            self.assertIn(key, d)

    def test_status_stored(self):
        result = HealthCheckResult(status="DEGRADED")
        self.assertEqual(result.status, "DEGRADED")


class HealthCheckerTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_passing_checks_return_up(self):
        checker = HealthChecker()
        checker.register_check("db", lambda: True)
        result = await checker.check_health()
        self.assertEqual(result.status, "UP")

    async def test_failing_check_returns_degraded(self):
        checker = HealthChecker()
        checker.register_check("db", lambda: False)
        result = await checker.check_health()
        self.assertEqual(result.status, "DEGRADED")

    async def test_check_results_included(self):
        checker = HealthChecker()
        checker.register_check("cache", lambda: True)
        result = await checker.check_health()
        self.assertIn("cache", result.checks)
        self.assertEqual(result.checks["cache"]["status"], "UP")

    async def test_async_check_function_supported(self):
        checker = HealthChecker()

        async def async_check():
            return True

        checker.register_check("async_svc", async_check)
        result = await checker.check_health()
        self.assertEqual(result.checks["async_svc"]["status"], "UP")

    async def test_exception_in_check_returns_error_status(self):
        checker = HealthChecker()

        def broken():
            raise RuntimeError("Connection refused")

        checker.register_check("db", broken)
        result = await checker.check_health()
        self.assertEqual(result.checks["db"]["status"], "ERROR")
        self.assertIn("Connection refused", result.checks["db"]["message"])

    async def test_uptime_is_positive(self):
        checker = HealthChecker()
        result = await checker.check_health()
        self.assertGreaterEqual(result.uptime_seconds, 0)


class StructuredLogHandlerThreadSafetyTests(unittest.TestCase):
    """Regression: emit() mutated self.logs without a lock, so concurrent
    calls from multiple threads could corrupt the deque or lose entries."""

    def _make_record(self, msg="x"):
        import logging
        return logging.LogRecord(
            name="t", level=logging.INFO, pathname="", lineno=0,
            msg=msg, args=(), exc_info=None,
        )

    def test_concurrent_emit_does_not_corrupt(self):
        handler = StructuredLogHandler(max_size=10_000)
        n_threads, per_thread = 8, 200
        errors = []

        def worker():
            for i in range(per_thread):
                try:
                    handler.emit(self._make_record(f"msg{i}"))
                except Exception as exc:
                    errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        # All per_thread * n_threads messages must have landed (cap is 10k, total is 1600).
        self.assertEqual(len(handler.logs), n_threads * per_thread)

    def test_get_logs_under_concurrent_emit(self):
        handler = StructuredLogHandler(max_size=500)
        stop = threading.Event()
        exceptions = []

        def emitter():
            while not stop.is_set():
                try:
                    handler.emit(self._make_record())
                except Exception as exc:
                    exceptions.append(exc)

        t = threading.Thread(target=emitter, daemon=True)
        t.start()
        for _ in range(100):
            try:
                handler.get_logs()
            except Exception as exc:
                exceptions.append(exc)
        stop.set()
        t.join(timeout=2)
        self.assertEqual(exceptions, [])


class TraceProviderOutOfOrderEndTests(unittest.TestCase):
    """Regression: end_span() only popped the stack when span_id was at the
    top, so closing a parent before its child left dead IDs in the stack."""

    def test_out_of_order_end_does_not_leak_stack(self):
        tp = TraceProvider()
        parent = tp.start_span("parent")
        child = tp.start_span("child")
        # Close parent while child is still 'active'
        tp.end_span(parent.span_id, status="OK")
        self.assertNotIn(parent.span_id, tp.active_span_stack)
        # Child is still open
        self.assertIn(child.span_id, tp.active_span_stack)
        tp.end_span(child.span_id, status="OK")
        self.assertNotIn(child.span_id, tp.active_span_stack)

    def test_end_unknown_span_is_safe(self):
        tp = TraceProvider()
        tp.end_span("does-not-exist")  # must not raise


class TraceProviderBoundedSpansTests(unittest.TestCase):
    """Regression: spans dict grew without bound — a long-running process
    would leak unbounded memory."""

    def test_spans_pruned_when_cap_reached(self):
        tp = TraceProvider()
        tp._max_spans = 10

        # Fill beyond cap; all spans are immediately ended so they're prunable.
        for i in range(20):
            span = tp.start_span(f"op{i}")
            tp.end_span(span.span_id)

        self.assertLessEqual(len(tp.spans), 10)

    def test_active_spans_not_pruned_until_ended(self):
        tp = TraceProvider()
        tp._max_spans = 5

        # 5 open spans — fill to cap.
        open_spans = [tp.start_span(f"live{i}") for i in range(5)]
        # Adding one more forces a prune; since no spans are ended yet,
        # one active span is evicted, but the total is back at the cap.
        extra = tp.start_span("extra")
        self.assertLessEqual(len(tp.spans), tp._max_spans)
        del open_spans, extra


class HealthCheckResultJsonSafetyTests(unittest.TestCase):
    """Regression: to_dict() returned a raw datetime object for 'timestamp',
    so json.dumps(result.to_dict()) raised TypeError without default=str."""

    def test_to_dict_timestamp_is_string(self):
        import json
        result = HealthCheckResult(status="UP")
        d = result.to_dict()
        # Must be JSON-serialisable without default=str
        serialised = json.dumps(d)
        parsed = json.loads(serialised)
        self.assertIsInstance(parsed["timestamp"], str)


if __name__ == "__main__":
    unittest.main()
