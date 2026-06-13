"""
Stdlib-only tests for main/break_reminder.py.

Uses very short timers (milliseconds) to exercise the scheduling logic
without actually waiting minutes.

Run: python -m unittest tests.test_break_reminder -v
"""
import os
import sys
import threading
import time
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from break_reminder import (  # noqa: E402
    BreakReminder, BreakReminderSession, load_break_reminder,
    _DEFAULT_WORK_MINUTES, _DEFAULT_SHORT_BREAK, _DEFAULT_LONG_BREAK,
    _DEFAULT_CYCLES_BEFORE_LONG,
)

# Use seconds instead of minutes for tests to avoid waiting real time.
# Monkey-patch session work_minutes to tiny values and override the
# _schedule_* methods to use seconds as minutes (i.e. 1 "minute" = 0.001s).
_TINY = 0.001  # seconds per "minute" in tests


def _make_fast_reminder(**kwargs) -> BreakReminder:
    """Return a BreakReminder where timers fire in ~1 ms per 'minute'."""
    br = BreakReminder(**kwargs)
    # Override schedule helpers to scale minutes → tiny seconds
    orig_schedule_work = BreakReminder._schedule_work
    orig_schedule_break = BreakReminder._schedule_break

    def fast_schedule_work(self):
        if self._stop_event.is_set():
            return
        self.session.is_on_break = False
        self.session.started_at = time.time()
        delay = self.session.work_minutes * _TINY
        self._timer = threading.Timer(delay, self._on_work_done)
        self._timer.daemon = True
        self._timer.start()

    def fast_schedule_break(self):
        if self._stop_event.is_set():
            return
        self.session.is_on_break = True
        self.session.started_at = time.time()
        break_mins = self.session.current_break_minutes
        delay = break_mins * _TINY
        self._timer = threading.Timer(delay, self._on_break_done)
        self._timer.daemon = True
        self._timer.start()

    import types
    br._schedule_work = types.MethodType(fast_schedule_work, br)
    br._schedule_break = types.MethodType(fast_schedule_break, br)
    return br


class BreakReminderSessionTests(unittest.TestCase):
    def test_initial_state(self):
        s = BreakReminderSession()
        self.assertEqual(s.completed_cycles, 0)
        self.assertFalse(s.is_on_break)
        self.assertIsNone(s.started_at)

    def test_default_values(self):
        s = BreakReminderSession()
        self.assertEqual(s.work_minutes, _DEFAULT_WORK_MINUTES)
        self.assertEqual(s.short_break_minutes, _DEFAULT_SHORT_BREAK)
        self.assertEqual(s.long_break_minutes, _DEFAULT_LONG_BREAK)
        self.assertEqual(s.cycles_before_long, _DEFAULT_CYCLES_BEFORE_LONG)

    def test_current_break_short(self):
        s = BreakReminderSession(cycles_before_long=4)
        s.completed_cycles = 0  # next is cycle 1 of 4 → short break
        self.assertEqual(s.current_break_minutes, s.short_break_minutes)

    def test_current_break_long(self):
        s = BreakReminderSession(cycles_before_long=4)
        s.completed_cycles = 3  # next is cycle 4 → long break
        self.assertTrue(s.is_long_break_due)
        self.assertEqual(s.current_break_minutes, s.long_break_minutes)

    def test_to_dict_has_expected_keys(self):
        s = BreakReminderSession()
        d = s.to_dict()
        for key in ("completed_cycles", "is_on_break", "work_minutes"):
            self.assertIn(key, d)


class BreakReminderStartStopTests(unittest.TestCase):
    def setUp(self):
        self.br = BreakReminder(work_minutes=1, short_break_minutes=1, long_break_minutes=2)

    def tearDown(self):
        self.br.stop()

    def test_not_running_before_start(self):
        self.assertFalse(self.br.running)

    def test_running_after_start(self):
        self.br.start()
        self.assertTrue(self.br.running)

    def test_not_running_after_stop(self):
        self.br.start()
        self.br.stop()
        self.assertFalse(self.br.running)

    def test_double_start_is_idempotent(self):
        self.br.start()
        self.br.start()  # should not raise
        self.assertTrue(self.br.running)

    def test_stop_when_not_started_does_not_raise(self):
        self.br.stop()  # should not raise

    def test_get_status_has_expected_keys(self):
        status = self.br.get_status()
        for key in ("running", "completed_cycles", "is_on_break", "work_minutes"):
            self.assertIn(key, status)

    def test_reset_clears_cycles(self):
        self.br.session.completed_cycles = 3
        self.br.reset()
        self.assertEqual(self.br.session.completed_cycles, 0)

    def test_reset_clears_history(self):
        self.br._history.append({"event": "test"})
        self.br.reset()
        self.assertEqual(self.br.get_history(), [])


class BreakReminderCallbackTests(unittest.TestCase):
    def test_notify_func_called_on_work_done(self):
        notifications = []
        br = _make_fast_reminder(
            work_minutes=1,
            short_break_minutes=100,  # long enough to not re-fire in test
            notify_func=lambda t, b: notifications.append((t, b)),
        )
        br.start()
        time.sleep(0.05)  # 1 "minute" = 0.001s → should fire quickly
        br.stop()
        self.assertGreater(len(notifications), 0)

    def test_speak_func_called_on_work_done(self):
        speeches = []
        br = _make_fast_reminder(
            work_minutes=1,
            short_break_minutes=100,
            speak_func=lambda t: speeches.append(t),
        )
        br.start()
        time.sleep(0.05)
        br.stop()
        self.assertGreater(len(speeches), 0)

    def test_history_recorded_after_work_done(self):
        br = _make_fast_reminder(work_minutes=1, short_break_minutes=100)
        br.start()
        time.sleep(0.05)
        br.stop()
        history = br.get_history()
        self.assertGreater(len(history), 0)
        self.assertTrue(any(e["event"] == "work_done" for e in history))

    def test_cycle_increments_after_break(self):
        br = _make_fast_reminder(work_minutes=1, short_break_minutes=1)
        br.start()
        time.sleep(0.1)  # enough for work + break
        br.stop()
        self.assertGreater(br.session.completed_cycles, 0)

    def test_english_lang_uses_english_messages(self):
        messages = []
        br = _make_fast_reminder(
            work_minutes=1,
            short_break_minutes=100,
            lang="en",
            speak_func=lambda t: messages.append(t),
        )
        br.start()
        time.sleep(0.05)
        br.stop()
        if messages:
            self.assertTrue(any("break" in m.lower() for m in messages))


class BreakReminderFromConfigTests(unittest.TestCase):
    def test_from_config_with_none(self):
        br = BreakReminder.from_config(None)
        self.assertEqual(br.session.work_minutes, _DEFAULT_WORK_MINUTES)

    def test_from_config_with_overrides(self):
        br = BreakReminder.from_config({"work_minutes": 50, "short_break_minutes": 10})
        self.assertEqual(br.session.work_minutes, 50)
        self.assertEqual(br.session.short_break_minutes, 10)

    def test_from_config_with_empty_dict(self):
        br = BreakReminder.from_config({})
        self.assertEqual(br.session.work_minutes, _DEFAULT_WORK_MINUTES)


class LoadBreakReminderTests(unittest.TestCase):
    def test_load_returns_break_reminder_instance(self):
        br = load_break_reminder()
        self.assertIsInstance(br, BreakReminder)

    def test_load_with_lang(self):
        br = load_break_reminder(lang="en")
        self.assertEqual(br.lang, "en")

    def test_load_config_file_is_used(self):
        # config/plugins/break_reminder.json has work_minutes=25
        br = load_break_reminder()
        self.assertEqual(br.session.work_minutes, 25)


if __name__ == "__main__":
    unittest.main()
