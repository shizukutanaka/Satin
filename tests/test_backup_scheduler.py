"""
Unit tests for BackupScheduler — history, _run_backup, and lifecycle guards.

schedule package is not installed, so add_daily_backup/add_weekly_backup
raise BackupError (which we test). The core backup logic in _run_backup
and history management are tested with mocked dependencies.
"""
import os
import sys
import unittest
from unittest import mock

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from backup_scheduler import BackupScheduler  # noqa: E402
from error_handling import BackupError  # noqa: E402


def _make_scheduler(target_dir="."):
    mock_bm = mock.MagicMock()
    mock_ns = mock.MagicMock()
    return BackupScheduler(mock_bm, mock_ns, backup_target_dir=target_dir), mock_bm, mock_ns


class NoSchedulePackageTests(unittest.TestCase):
    """When schedule is not installed, schedule-registration methods raise BackupError."""

    def test_add_daily_backup_raises_when_no_schedule(self):
        sched, _, _ = _make_scheduler()
        # schedule not installed → _scheduler is None
        with self.assertRaises(BackupError):
            sched.add_daily_backup(2, 0)

    def test_add_weekly_backup_raises_when_no_schedule(self):
        sched, _, _ = _make_scheduler()
        with self.assertRaises(BackupError):
            sched.add_weekly_backup("monday", 2, 0)

    def test_start_raises_when_no_schedule(self):
        sched, _, _ = _make_scheduler()
        with self.assertRaises(BackupError):
            sched.start()


class RunBackupTests(unittest.TestCase):
    def test_successful_backup_adds_history_entry(self):
        sched, mock_bm, _ = _make_scheduler()
        mock_bm.create_backup.return_value = "/tmp/bk.zip"
        sched._run_backup("daily")
        self.assertEqual(len(sched.backup_history), 1)
        self.assertTrue(sched.backup_history[0]["success"])

    def test_failed_backup_records_error(self):
        sched, mock_bm, _ = _make_scheduler()
        mock_bm.create_backup.side_effect = RuntimeError("disk full")
        sched._run_backup("weekly")
        entry = sched.backup_history[0]
        self.assertFalse(entry["success"])
        self.assertIsNotNone(entry["error"])
        self.assertIn("disk full", entry["error"])

    def test_history_entry_has_type_and_timestamp(self):
        sched, mock_bm, _ = _make_scheduler()
        sched._run_backup("daily")
        entry = sched.backup_history[0]
        self.assertEqual(entry["type"], "daily")
        self.assertIn("timestamp", entry)
        self.assertIn("time", entry)

    def test_history_trimmed_to_max(self):
        sched, mock_bm, _ = _make_scheduler()
        sched.max_history = 3
        for _ in range(5):
            sched._run_backup("daily")
        self.assertEqual(len(sched.backup_history), 3)

    def test_notification_sent_on_success(self):
        sched, mock_bm, mock_ns = _make_scheduler()
        mock_bm.create_backup.return_value = "/tmp/bk.zip"
        sched._run_backup("daily")
        # At minimum: started + completed notifications
        self.assertGreaterEqual(mock_ns.send_notification.call_count, 2)

    def test_notification_sent_on_failure(self):
        sched, mock_bm, mock_ns = _make_scheduler()
        mock_bm.create_backup.side_effect = RuntimeError("oops")
        sched._run_backup("daily")
        # At minimum: started + failed notifications
        self.assertGreaterEqual(mock_ns.send_notification.call_count, 2)


class HistoryManagementTests(unittest.TestCase):
    def test_get_backup_history_returns_copy(self):
        sched, mock_bm, _ = _make_scheduler()
        sched._run_backup("daily")
        h1 = sched.get_backup_history()
        h1.clear()  # mutation of returned list must not affect internal state
        self.assertEqual(len(sched.backup_history), 1)

    def test_clear_backup_history(self):
        sched, mock_bm, _ = _make_scheduler()
        sched._run_backup("daily")
        sched.clear_backup_history()
        self.assertEqual(len(sched.backup_history), 0)

    def test_stop_sets_running_false(self):
        sched, _, _ = _make_scheduler()
        sched.running = True
        sched.stop()
        self.assertFalse(sched.running)


if __name__ == "__main__":
    unittest.main()
