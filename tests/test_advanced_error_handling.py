"""
Tests for advanced_error_handling.py exception hierarchy and recovery strategies.

Run: python -m unittest tests.test_advanced_error_handling -v
"""
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


if __name__ == "__main__":
    unittest.main()
