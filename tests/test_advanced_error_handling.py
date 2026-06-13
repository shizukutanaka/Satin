"""
Tests for advanced_error_handling.py exception hierarchy and recovery strategies.

Run: python -m unittest tests.test_advanced_error_handling -v
"""
import logging
import os
import sys
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from advanced_error_handling import (  # noqa: E402
    SatinException, APIIntegrationError, YouTubeAPIError,
    WebScrapingError, RateLimitError, DataValidationError,
    ResourceCleanupError, ErrorContext, ErrorRecoveryInfo,
    ErrorRecoveryStrategy,
    ErrorContextManager,
    handle_errors_gracefully,
    with_error_context,
    StructuredErrorFormatter,
    ErrorStatistics,
)


class SatinExceptionTests(unittest.TestCase):
    def test_message_and_defaults(self):
        exc = SatinException("something went wrong")
        self.assertEqual(exc.message, "something went wrong")
        self.assertEqual(exc.error_code, "SatinException")
        self.assertEqual(exc.context, {})
        self.assertIsNone(exc.cause)

    def test_custom_error_code_and_context(self):
        exc = SatinException("msg", error_code="E001", context={"key": "val"})
        self.assertEqual(exc.error_code, "E001")
        self.assertEqual(exc.context["key"], "val")

    def test_to_dict_contains_required_keys(self):
        exc = SatinException("test")
        d = exc.to_dict()
        for key in ("error_type", "error_code", "message", "context", "timestamp"):
            self.assertIn(key, d)
        self.assertEqual(d["error_type"], "SatinException")

    def test_to_json_is_valid_json(self):
        import json
        exc = SatinException("test", context={"n": 42})
        parsed = json.loads(exc.to_json())
        self.assertEqual(parsed["context"]["n"], 42)

    def test_cause_serialized(self):
        cause = ValueError("root cause")
        exc = SatinException("wrapper", cause=cause)
        d = exc.to_dict()
        self.assertIn("root cause", d["cause"])

    def test_is_exception_subclass(self):
        with self.assertRaises(SatinException):
            raise SatinException("boom")


class ExceptionHierarchyTests(unittest.TestCase):
    def test_youtube_api_error_stores_fields(self):
        exc = YouTubeAPIError("quota", api_error_code=403, quota_exceeded=True,
                              retry_after=60.0)
        self.assertEqual(exc.api_error_code, 403)
        self.assertTrue(exc.quota_exceeded)
        self.assertEqual(exc.retry_after, 60.0)
        self.assertIsInstance(exc, APIIntegrationError)

    def test_web_scraping_error_stores_fields(self):
        exc = WebScrapingError("blocked", http_status=403, blocked=True)
        self.assertEqual(exc.http_status, 403)
        self.assertTrue(exc.blocked)

    def test_rate_limit_error_stores_fields(self):
        from datetime import datetime, timedelta
        reset_at = datetime.now() + timedelta(seconds=30)
        exc = RateLimitError("rate limited", reset_at=reset_at, retry_after=30.0)
        self.assertEqual(exc.retry_after, 30.0)
        self.assertEqual(exc.reset_at, reset_at)

    def test_data_validation_error_stores_fields(self):
        exc = DataValidationError("bad value", field="name", value="")
        self.assertEqual(exc.field, "name")
        self.assertEqual(exc.value, "")

    def test_resource_cleanup_error_stores_fields(self):
        exc = ResourceCleanupError("cleanup failed", resource_name="db_conn",
                                   partial_cleanup=True)
        self.assertEqual(exc.resource_name, "db_conn")
        self.assertTrue(exc.partial_cleanup)


class ErrorRecoveryStrategyTests(unittest.TestCase):
    def test_rate_limit_is_recoverable_with_retry(self):
        exc = RateLimitError("limited", retry_after=10.0)
        info = ErrorRecoveryStrategy.determine_recovery(exc)
        self.assertTrue(info.is_recoverable)
        self.assertTrue(info.retry_possible)
        self.assertEqual(info.retry_after_seconds, 10.0)

    def test_rate_limit_defaults_to_60s_when_no_retry_after(self):
        exc = RateLimitError("limited", retry_after=None)
        info = ErrorRecoveryStrategy.determine_recovery(exc)
        self.assertEqual(info.retry_after_seconds, 60.0)

    def test_youtube_quota_exceeded_not_retry_soon(self):
        exc = YouTubeAPIError("quota", quota_exceeded=True)
        info = ErrorRecoveryStrategy.determine_recovery(exc)
        # quota exceeded: not retryable immediately
        self.assertFalse(info.retry_possible)

    def test_youtube_api_error_without_quota_is_retryable(self):
        exc = YouTubeAPIError("transient", quota_exceeded=False)
        info = ErrorRecoveryStrategy.determine_recovery(exc)
        self.assertTrue(info.retry_possible)

    def test_error_context_to_dict(self):
        ctx = ErrorContext(operation="fetch_video", retry_count=2,
                           extra_context={"video_id": "abc"})
        d = ctx.to_dict()
        self.assertEqual(d["operation"], "fetch_video")
        self.assertEqual(d["retry_count"], 2)
        self.assertEqual(d["extra_context"]["video_id"], "abc")


class ErrorContextManagerTests(unittest.TestCase):
    def test_returns_self_on_enter(self):
        mgr = ErrorContextManager("test_op")
        result = mgr.__enter__()
        self.assertIs(result, mgr)

    def test_exit_records_duration(self):
        with ErrorContextManager("op") as mgr:
            pass
        self.assertGreaterEqual(mgr.context.duration_ms, 0.0)

    def test_add_context_stores_value(self):
        with ErrorContextManager("op") as mgr:
            mgr.add_context("key", "value")
        self.assertEqual(mgr.context.extra_context["key"], "value")

    def test_record_retry_increments_count(self):
        with ErrorContextManager("op") as mgr:
            mgr.record_retry()
            mgr.record_retry()
        self.assertEqual(mgr.context.retry_count, 2)

    def test_exception_propagates(self):
        with self.assertRaises(ValueError):
            with ErrorContextManager("op"):
                raise ValueError("boom")

    def test_exit_returns_false_so_exception_propagates(self):
        mgr = ErrorContextManager("op")
        mgr.__enter__()
        result = mgr.__exit__(ValueError, ValueError("err"), None)
        self.assertFalse(result)


class HandleErrorsGracefullyTests(unittest.TestCase):
    def test_returns_fallback_on_exception(self):
        @handle_errors_gracefully(exceptions=(ValueError,), fallback_value=-1)
        def bad():
            raise ValueError("fail")

        self.assertEqual(bad(), -1)

    def test_returns_normal_result_on_success(self):
        @handle_errors_gracefully(exceptions=(ValueError,), fallback_value=-1)
        def good():
            return 42

        self.assertEqual(good(), 42)

    def test_recovery_func_called_on_exception(self):
        called = []

        @handle_errors_gracefully(exceptions=(RuntimeError,),
                                  fallback_value=None,
                                  recovery_func=lambda: called.append(1))
        def fail():
            raise RuntimeError("err")

        fail()
        self.assertEqual(called, [1])

    def test_non_matching_exception_propagates(self):
        @handle_errors_gracefully(exceptions=(ValueError,), fallback_value=None)
        def boom():
            raise TypeError("wrong type")

        with self.assertRaises(TypeError):
            boom()

    def test_satin_exception_handled(self):
        @handle_errors_gracefully(exceptions=(SatinException,), fallback_value="safe")
        def satin_fail():
            raise SatinException("satin error")

        self.assertEqual(satin_fail(), "safe")


class WithErrorContextTests(unittest.TestCase):
    def test_decorated_function_returns_result(self):
        @with_error_context("my_op")
        def add(a, b):
            return a + b

        self.assertEqual(add(3, 4), 7)

    def test_exception_still_propagates(self):
        @with_error_context("my_op")
        def fail():
            raise RuntimeError("explode")

        with self.assertRaises(RuntimeError):
            fail()


class StructuredErrorFormatterTests(unittest.TestCase):
    def _make_record(self, msg="test message", level=logging.ERROR):
        record = logging.LogRecord(
            name="test_logger", level=level,
            pathname="", lineno=0, msg=msg,
            args=(), exc_info=None,
        )
        return record

    def test_format_returns_valid_json(self):
        import json
        formatter = StructuredErrorFormatter()
        output = formatter.format(self._make_record())
        parsed = json.loads(output)
        self.assertIn("timestamp", parsed)
        self.assertIn("message", parsed)
        self.assertIn("level", parsed)

    def test_format_includes_exception_info(self):
        import json, sys
        try:
            raise ValueError("test error")
        except ValueError:
            exc_info = sys.exc_info()
        record = logging.LogRecord(
            name="test", level=logging.ERROR,
            pathname="", lineno=0, msg="err",
            args=(), exc_info=exc_info,
        )
        parsed = json.loads(StructuredErrorFormatter().format(record))
        self.assertIn("exception", parsed)
        self.assertEqual(parsed["exception"]["type"], "ValueError")

    def test_format_includes_level_name(self):
        import json  # noqa: F401
        formatter = StructuredErrorFormatter()
        parsed = json.loads(formatter.format(self._make_record(level=logging.WARNING)))
        self.assertEqual(parsed["level"], "WARNING")


class ErrorStatisticsTests(unittest.TestCase):
    def test_initial_state(self):
        stats = ErrorStatistics()
        self.assertEqual(stats.total_errors, 0)
        self.assertEqual(stats.recoverable_count, 0)
        self.assertIsNone(stats.last_error)

    def test_record_error_increments_total(self):
        stats = ErrorStatistics()
        stats.record_error(ValueError("x"), "op1")
        self.assertEqual(stats.total_errors, 1)

    def test_record_error_tracks_type(self):
        stats = ErrorStatistics()
        stats.record_error(ValueError("x"), "op1")
        self.assertIn("ValueError", stats.error_by_type)
        self.assertEqual(stats.error_by_type["ValueError"], 1)

    def test_record_error_tracks_operation(self):
        stats = ErrorStatistics()
        stats.record_error(RuntimeError("y"), "my_op")
        self.assertEqual(stats.error_by_operation["my_op"], 1)

    def test_recoverable_counted_for_satin_exception(self):
        stats = ErrorStatistics()
        exc = RateLimitError("limited", retry_after=10.0)
        stats.record_error(exc, "op")
        self.assertGreaterEqual(stats.recoverable_count, 1)

    def test_get_error_rate_empty_returns_empty(self):
        stats = ErrorStatistics()
        self.assertEqual(stats.get_error_rate(), {})

    def test_get_error_rate_with_errors(self):
        stats = ErrorStatistics()
        stats.record_error(ValueError("x"), "op")
        rate = stats.get_error_rate()
        self.assertIn("recoverable_rate", rate)
        self.assertIn("unrecoverable_rate", rate)

    def test_to_dict_has_expected_keys(self):
        stats = ErrorStatistics()
        d = stats.to_dict()
        for key in ("total_errors", "error_by_type", "error_by_operation",
                    "recoverable_count", "unrecoverable_count", "error_rates"):
            self.assertIn(key, d)

    def test_last_error_stored(self):
        stats = ErrorStatistics()
        exc = RuntimeError("last one")
        stats.record_error(exc, "op")
        self.assertIs(stats.last_error, exc)


if __name__ == "__main__":
    unittest.main()
