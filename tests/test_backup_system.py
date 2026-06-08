"""
Stdlib-only regression tests for backup_manager.py, backup_scheduler.py,
notification_system.py, and the BackupError addition to error_handling.py.

Run: python -m unittest tests.test_backup_system -v
"""
import os
import sys
import zipfile
import tempfile
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)


class BackupManagerImportTests(unittest.TestCase):
    def test_imports_without_google_cloud(self):
        # Previously crashed: ModuleNotFoundError: No module named 'google'
        import backup_manager
        self.assertTrue(hasattr(backup_manager, "BackupManager"))

    def test_no_duplicate_methods(self):
        import backup_manager
        import inspect
        src = inspect.getsource(backup_manager.BackupManager)
        # Each key method must appear exactly once
        for method in ("def create_backup", "def list_backups", "def restore_backup",
                       "def delete_backup", "def _validate_backup"):
            count = src.count(method)
            self.assertEqual(count, 1, f"{method} defined {count} times (expected 1)")

    def test_validate_backup_works_on_real_zip(self):
        import backup_manager as bm
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
            fname = f.name
        try:
            with zipfile.ZipFile(fname, "w") as zf:
                zf.writestr("hello.txt", "world")
            mgr = object.__new__(bm.BackupManager)  # skip __init__ (needs config)
            self.assertTrue(mgr._validate_backup(bm.Path(fname)))
        finally:
            os.unlink(fname)


class BackupSchedulerImportTests(unittest.TestCase):
    def test_imports_without_relative_errors(self):
        # Previously: ImportError relative import, BackupError missing, etc.
        import backup_scheduler
        self.assertTrue(hasattr(backup_scheduler, "BackupScheduler"))

    def test_instantiation_without_schedule_package(self):
        import backup_scheduler as bs
        from notification_system import NotificationSystem
        ns = NotificationSystem()
        # Create a dummy BackupManager that won't hit the filesystem
        class FakeBM:
            def create_backup(self, d): pass
        sched = bs.BackupScheduler(FakeBM(), ns, backup_target_dir="/tmp")
        self.assertFalse(sched.running)
        self.assertEqual(sched.backup_history, [])


class NotificationSystemTests(unittest.TestCase):
    def test_imports_and_instantiates(self):
        from notification_system import NotificationSystem
        ns = NotificationSystem("TestApp")
        self.assertEqual(ns.app_name, "TestApp")

    def test_send_notification_does_not_crash(self):
        from notification_system import NotificationSystem
        ns = NotificationSystem()
        ns.send_notification("Title", "Body", level="error")  # must not raise


class BackupErrorTests(unittest.TestCase):
    def test_backup_error_in_error_handling(self):
        from error_handling import BackupError, SatinError
        err = BackupError("disk full")
        self.assertIsInstance(err, SatinError)
        self.assertEqual(err.message, "disk full")


if __name__ == "__main__":
    unittest.main()
