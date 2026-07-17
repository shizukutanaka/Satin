"""
Stdlib-only tests for main/notification_system.py.

Run: python -m unittest tests.test_notification_system -v
"""
import os
import sys
import time
import unittest
from unittest import mock

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

    def test_get_history_zero_returns_empty(self):
        # Regression: items[-0:] == items[0:] returned the whole history for n=0.
        for i in range(3):
            self.ns.send_notification(f"T{i}", "M")
        self.assertEqual(self.ns.get_history(0), [])

    def test_get_history_negative_returns_empty(self):
        for i in range(3):
            self.ns.send_notification(f"T{i}", "M")
        self.assertEqual(self.ns.get_history(-1), [])

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


class DesktopFallbackChainTests(unittest.TestCase):
    """Regression: _try_desktop() checked _PLYER_AVAILABLE (import-time
    success) and returned _try_plyer()'s result immediately, even when it
    was False (runtime failure — e.g. headless Linux with no display, where
    plyer imports fine but notify() always raises). notify2 was never
    attempted even if it was available and would have worked. Docstring
    promises a priority chain (plyer -> notify2 -> logging); the fix makes
    it actually fall through on runtime failure, not just import failure.
    """

    def setUp(self):
        import notification_system as ns_mod
        self._ns_mod = ns_mod
        self.ns = NotificationSystem(app_name="TestApp")

    def test_falls_through_to_notify2_when_plyer_fails_at_runtime(self):
        with mock.patch.object(self._ns_mod, "_PLYER_AVAILABLE", True), \
             mock.patch.object(self.ns, "_try_plyer", return_value=False) as m_plyer, \
             mock.patch.object(self._ns_mod, "_NOTIFY2_AVAILABLE", True), \
             mock.patch.object(self.ns, "_try_notify2", return_value=True) as m_notify2:
            result = self.ns._try_desktop("t", "m", 5)
        m_plyer.assert_called_once()
        m_notify2.assert_called_once()
        self.assertTrue(result)

    def test_does_not_call_notify2_when_plyer_succeeds(self):
        with mock.patch.object(self._ns_mod, "_PLYER_AVAILABLE", True), \
             mock.patch.object(self.ns, "_try_plyer", return_value=True), \
             mock.patch.object(self._ns_mod, "_NOTIFY2_AVAILABLE", True), \
             mock.patch.object(self.ns, "_try_notify2") as m_notify2:
            result = self.ns._try_desktop("t", "m", 5)
        m_notify2.assert_not_called()
        self.assertTrue(result)

    def test_returns_false_when_both_backends_fail(self):
        with mock.patch.object(self._ns_mod, "_PLYER_AVAILABLE", True), \
             mock.patch.object(self.ns, "_try_plyer", return_value=False), \
             mock.patch.object(self._ns_mod, "_NOTIFY2_AVAILABLE", True), \
             mock.patch.object(self.ns, "_try_notify2", return_value=False):
            result = self.ns._try_desktop("t", "m", 5)
        self.assertFalse(result)

    def test_no_plyer_tries_notify2_directly(self):
        with mock.patch.object(self._ns_mod, "_PLYER_AVAILABLE", False), \
             mock.patch.object(self._ns_mod, "_NOTIFY2_AVAILABLE", True), \
             mock.patch.object(self.ns, "_try_notify2", return_value=True) as m_notify2:
            result = self.ns._try_desktop("t", "m", 5)
        m_notify2.assert_called_once()
        self.assertTrue(result)


class Notify2InitRaceTests(unittest.TestCase):
    """Regression: `if not self._notify2_inited: _notify2.init(...); ...= True`
    was an unlocked check-then-act. backup_scheduler runs send_notification
    from a timer thread, so concurrent callers could race and call
    notify2.init() more than once. Fixed with a lock + re-check inside it.
    """

    def test_init_called_only_once_across_concurrent_calls(self):
        import threading
        import notification_system as ns_mod

        init_calls = []
        fake_notify2 = mock.MagicMock()
        fake_notify2.init.side_effect = lambda name: init_calls.append(name)
        fake_notify2.Notification.return_value = mock.MagicMock()

        ns = NotificationSystem(app_name="TestApp")
        barrier = threading.Barrier(8)

        def worker():
            barrier.wait()
            with mock.patch.object(ns_mod, "_notify2", fake_notify2):
                ns._try_notify2("t", "m", 1)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(init_calls), 1,
                         f"notify2.init() must be called exactly once, got {len(init_calls)}")


if __name__ == "__main__":
    unittest.main()
