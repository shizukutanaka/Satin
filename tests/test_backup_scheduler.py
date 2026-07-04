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


class LifecycleResetTests(unittest.TestCase):
    """Regression: start() left running=True on the error path (permanently
    wedging the scheduler in 'already running'), and never cleared _stop_event
    (busy-spin on restart). These tests inject a fake scheduler to drive start()."""

    def test_running_reset_after_loop_crash(self):
        sched, _, _ = _make_scheduler()
        sched._scheduler = mock.MagicMock()
        sched._scheduler.run_pending.side_effect = RuntimeError("loop crash")

        with self.assertRaises(BackupError):
            sched.start()
        self.assertFalse(sched.running, "running must reset to False after a loop crash")

        # Must be restartable, not permanently stuck on the 'already running' guard.
        sched._scheduler.run_pending.side_effect = RuntimeError("again")
        with self.assertRaises(BackupError):
            sched.start()

    def test_stop_event_cleared_on_start(self):
        sched, _, _ = _make_scheduler()
        sched._scheduler = mock.MagicMock()
        # Simulate a leftover set event from a previous stop().
        sched._stop_event.set()

        observed = {}

        def first_iter():
            observed["cleared"] = not sched._stop_event.is_set()
            # Exit the loop and let the trailing wait() return immediately.
            sched.running = False
            sched._stop_event.set()

        sched._scheduler.run_pending.side_effect = first_iter
        sched.start()  # blocks one iteration, then exits cleanly

        self.assertTrue(
            observed.get("cleared"),
            "start() must clear _stop_event so wait() blocks instead of busy-spinning",
        )


class RetentionTests(unittest.TestCase):
    """Regression: BackupScheduler never called delete_backup() anywhere.
    add_daily_backup/add_weekly_backup exist for unattended, recurring
    backups, but with no automated retention, backups accumulated forever —
    unbounded disk growth for anyone using the scheduler as intended. Fixed
    with an opt-in max_backups parameter (default None preserves old
    behavior exactly) enforced after each successful scheduled backup.
    """

    def _backups(self, n):
        return [{"path": f"/backups/b{i}.zip", "created": f"2024-01-{20 - i:02d}"}
                for i in range(n)]

    def test_default_max_backups_none_disables_retention(self):
        """Backward compatibility: without max_backups, no deletion ever happens."""
        sched, mock_bm, _ = _make_scheduler()
        mock_bm.create_backup.return_value = "/tmp/bk.zip"
        mock_bm.list_backups.return_value = self._backups(50)
        sched._run_backup("daily")
        mock_bm.delete_backup.assert_not_called()

    def test_retention_deletes_oldest_beyond_max(self):
        mock_bm = mock.MagicMock()
        mock_ns = mock.MagicMock()
        sched = BackupScheduler(mock_bm, mock_ns, max_backups=3)
        mock_bm.create_backup.return_value = "/tmp/bk.zip"
        mock_bm.list_backups.return_value = self._backups(5)  # newest-first order

        sched._run_backup("daily")

        deleted_paths = [call.args[0] for call in mock_bm.delete_backup.call_args_list]
        # backups()[3:] are the two oldest (list_backups() is newest-first).
        self.assertEqual(sorted(deleted_paths), ["/backups/b3.zip", "/backups/b4.zip"])

    def test_retention_not_applied_when_backup_count_within_limit(self):
        mock_bm = mock.MagicMock()
        mock_ns = mock.MagicMock()
        sched = BackupScheduler(mock_bm, mock_ns, max_backups=10)
        mock_bm.create_backup.return_value = "/tmp/bk.zip"
        mock_bm.list_backups.return_value = self._backups(3)

        sched._run_backup("daily")
        mock_bm.delete_backup.assert_not_called()

    def test_retention_not_applied_when_backup_fails(self):
        """A failed create_backup must not trigger retention deletion."""
        mock_bm = mock.MagicMock()
        mock_ns = mock.MagicMock()
        sched = BackupScheduler(mock_bm, mock_ns, max_backups=1)
        mock_bm.create_backup.side_effect = RuntimeError("disk full")
        mock_bm.list_backups.return_value = self._backups(5)

        sched._run_backup("daily")
        mock_bm.delete_backup.assert_not_called()

    def test_one_delete_failure_does_not_abort_remaining_deletions(self):
        mock_bm = mock.MagicMock()
        mock_ns = mock.MagicMock()
        sched = BackupScheduler(mock_bm, mock_ns, max_backups=1)
        mock_bm.create_backup.return_value = "/tmp/bk.zip"
        mock_bm.list_backups.return_value = self._backups(3)
        mock_bm.delete_backup.side_effect = [RuntimeError("locked"), True]

        sched._run_backup("daily")  # must not raise
        self.assertEqual(mock_bm.delete_backup.call_count, 2)

    def test_list_backups_failure_does_not_abort_run_backup(self):
        mock_bm = mock.MagicMock()
        mock_ns = mock.MagicMock()
        sched = BackupScheduler(mock_bm, mock_ns, max_backups=1)
        mock_bm.create_backup.return_value = "/tmp/bk.zip"
        mock_bm.list_backups.side_effect = RuntimeError("io error")

        sched._run_backup("daily")  # must not raise
        self.assertEqual(len(sched.backup_history), 1)
        self.assertTrue(sched.backup_history[0]["success"])


if __name__ == "__main__":
    unittest.main()
