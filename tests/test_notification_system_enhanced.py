"""
Tests for the enhanced notification_system module.

Covers: history tracking, available_backends, logging fallback,
clear_history, history_count, and graceful backend failure handling.
Does NOT require plyer or notify2.
"""
import logging
import os
import sys
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from notification_system import NotificationSystem  # noqa: E402


class NotificationSystemBasicTests(unittest.TestCase):
    def test_instantiates_with_default_name(self):
        ns = NotificationSystem()
        self.assertEqual(ns.app_name, "Satin")

    def test_instantiates_with_custom_name(self):
        ns = NotificationSystem("MyApp")
        self.assertEqual(ns.app_name, "MyApp")

    def test_send_notification_does_not_raise(self):
        ns = NotificationSystem()
        # Always falls back to logging; must not raise
        ns.send_notification("Title", "Body")
        ns.send_notification("T", "B", level="error")
        ns.send_notification("T", "B", level="warning")
        ns.send_notification("T", "B", level="success")

    def test_send_returns_bool(self):
        ns = NotificationSystem()
        result = ns.send_notification("Title", "Body")
        # May be True if a desktop backend is available, False otherwise.
        self.assertIsInstance(result, bool)


class NotificationHistoryTests(unittest.TestCase):
    def test_history_starts_empty(self):
        ns = NotificationSystem()
        self.assertEqual(ns.history_count, 0)
        self.assertEqual(ns.get_history(), [])

    def test_history_records_entry_after_send(self):
        ns = NotificationSystem()
        ns.send_notification("Hello", "World", level="info")
        self.assertEqual(ns.history_count, 1)
        h = ns.get_history()
        self.assertEqual(len(h), 1)
        entry = h[0]
        self.assertEqual(entry["title"], "Hello")
        self.assertEqual(entry["message"], "World")
        self.assertEqual(entry["level"], "info")
        self.assertIn("timestamp", entry)

    def test_history_order_is_newest_first(self):
        ns = NotificationSystem()
        ns.send_notification("First", "1")
        ns.send_notification("Second", "2")
        h = ns.get_history()
        self.assertEqual(h[0]["title"], "Second")
        self.assertEqual(h[1]["title"], "First")

    def test_history_n_limit(self):
        ns = NotificationSystem()
        for i in range(5):
            ns.send_notification(f"Title{i}", "msg")
        h = ns.get_history(n=3)
        self.assertEqual(len(h), 3)

    def test_clear_history(self):
        ns = NotificationSystem()
        ns.send_notification("A", "a")
        ns.clear_history()
        self.assertEqual(ns.history_count, 0)
        self.assertEqual(ns.get_history(), [])

    def test_history_count_increments(self):
        ns = NotificationSystem()
        for i in range(3):
            ns.send_notification(f"T{i}", "m")
        self.assertEqual(ns.history_count, 3)


class AvailableBackendsTests(unittest.TestCase):
    def test_logging_always_in_backends(self):
        backends = NotificationSystem.available_backends()
        self.assertIn("logging", backends)

    def test_returns_list(self):
        backends = NotificationSystem.available_backends()
        self.assertIsInstance(backends, list)
        self.assertGreater(len(backends), 0)


class LoggingFallbackTests(unittest.TestCase):
    def test_warning_level_logs_at_warning(self):
        ns = NotificationSystem("TestApp")
        with self.assertLogs("notification_system", level="WARNING") as cm:
            ns.send_notification("Warn", "something bad", level="warning")
        self.assertTrue(any("something bad" in line for line in cm.output))

    def test_error_level_logs_at_error(self):
        ns = NotificationSystem()
        with self.assertLogs("notification_system", level="ERROR") as cm:
            ns.send_notification("Err", "fatal error", level="error")
        self.assertTrue(any("fatal error" in line for line in cm.output))

    def test_info_level_logs_at_info(self):
        ns = NotificationSystem()
        with self.assertLogs("notification_system", level="INFO") as cm:
            ns.send_notification("Info", "info msg", level="info")
        self.assertTrue(any("info msg" in line for line in cm.output))


if __name__ == "__main__":
    unittest.main()
