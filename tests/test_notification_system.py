"""
Stdlib-only tests for main/notification_system.py.

Run: python -m unittest tests.test_notification_system -v
"""
import os
import sys
import time
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from notification_system import NotificationSystem  # noqa: E402


class NotificationSendTests(unittest.TestCase):
    def setUp(self):
        self.ns = NotificationSystem(app_name="TestApp")

    def test_send_returns_bool(self):
        result = self.ns.send_notification("T", "M")
        self.assertIsInstance(result, bool)

    def test_send_appends_to_history(self):
        self.ns.send_notification("Title", "Body")
        self.assertEqual(self.ns.history_count, 1)

    def test_send_multiple_appends(self):
        for i in range(5):
            self.ns.send_notification(f"T{i}", f"M{i}")
        self.assertEqual(self.ns.history_count, 5)

    def test_history_entry_has_expected_keys(self):
        self.ns.send_notification("Hello", "World", level="info")
        hist = self.ns.get_history(1)
        entry = hist[0]
        for key in ("timestamp", "title", "message", "level"):
            self.assertIn(key, entry)

    def test_history_entry_title_and_message(self):
        self.ns.send_notification("MyTitle", "MyMessage")
        hist = self.ns.get_history(1)
        self.assertEqual(hist[0]["title"], "MyTitle")
        self.assertEqual(hist[0]["message"], "MyMessage")

    def test_history_entry_level_stored(self):
        self.ns.send_notification("T", "M", level="warning")
        hist = self.ns.get_history(1)
        self.assertEqual(hist[0]["level"], "warning")

    def test_history_entry_timestamp_is_recent(self):
        before = time.time() - 1.0
        self.ns.send_notification("T", "M")
        hist = self.ns.get_history(1)
        self.assertGreater(hist[0]["timestamp"], before)


class NotificationHistoryTests(unittest.TestCase):
    def setUp(self):
        self.ns = NotificationSystem()

    def test_get_history_returns_newest_first(self):
        for i in range(3):
            self.ns.send_notification(f"T{i}", "M")
        hist = self.ns.get_history()
        # get_history returns newest first (reversed)
        self.assertEqual(hist[0]["title"], "T2")
        self.assertEqual(hist[-1]["title"], "T0")

    def test_get_history_n_limits_results(self):
        for i in range(10):
            self.ns.send_notification(f"T{i}", "M")
        hist = self.ns.get_history(3)
        self.assertEqual(len(hist), 3)

    def test_get_history_n_larger_than_count(self):
        self.ns.send_notification("T", "M")
        hist = self.ns.get_history(100)
        self.assertEqual(len(hist), 1)

    def test_clear_history_empties_history(self):
        self.ns.send_notification("T", "M")
        self.ns.clear_history()
        self.assertEqual(self.ns.history_count, 0)

    def test_clear_history_get_returns_empty(self):
        self.ns.send_notification("T", "M")
        self.ns.clear_history()
        self.assertEqual(self.ns.get_history(), [])

    def test_history_count_property(self):
        self.assertEqual(self.ns.history_count, 0)
        self.ns.send_notification("T", "M")
        self.assertEqual(self.ns.history_count, 1)


class NotificationBackendTests(unittest.TestCase):
    def test_available_backends_returns_list(self):
        backends = NotificationSystem.available_backends()
        self.assertIsInstance(backends, list)

    def test_logging_always_in_backends(self):
        backends = NotificationSystem.available_backends()
        self.assertIn("logging", backends)

    def test_app_name_stored(self):
        ns = NotificationSystem(app_name="Satin")
        self.assertEqual(ns.app_name, "Satin")


if __name__ == "__main__":
    unittest.main()
