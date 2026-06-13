"""
Unit tests for backup_cli — the backup management CLI wrapper.

Mocks get_backup_manager() so no real backup files are created.
Tests cover: create, list, restore, delete, exception paths, and main() dispatch.
"""
import os
import sys
import unittest
from unittest import mock
from io import StringIO

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import backup_cli  # noqa: E402


def _ns(**kw):
    """Build a minimal argparse-like namespace."""
    import argparse
    ns = argparse.Namespace()
    for k, v in kw.items():
        setattr(ns, k, v)
    return ns


def _mock_manager(**attrs):
    m = mock.MagicMock()
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


class CreateBackupTests(unittest.TestCase):
    def test_success_returns_zero(self):
        mgr = _mock_manager()
        mgr.create_backup.return_value = "/tmp/backup.zip"
        with mock.patch.object(backup_cli, "get_backup_manager", return_value=mgr):
            rc = backup_cli.create_backup(_ns(target_dir="/src", backup_name="bk"))
        self.assertEqual(rc, 0)
        mgr.create_backup.assert_called_once_with("/src", "bk")

    def test_exception_returns_one(self):
        mgr = _mock_manager()
        mgr.create_backup.side_effect = RuntimeError("disk full")
        with mock.patch.object(backup_cli, "get_backup_manager", return_value=mgr):
            rc = backup_cli.create_backup(_ns(target_dir="/src", backup_name=None))
        self.assertEqual(rc, 1)

    def test_prints_path_on_success(self):
        mgr = _mock_manager()
        mgr.create_backup.return_value = "/tmp/backup_20240101.zip"
        with mock.patch.object(backup_cli, "get_backup_manager", return_value=mgr), \
             mock.patch("builtins.print") as mock_print:
            backup_cli.create_backup(_ns(target_dir="/src", backup_name=None))
        combined = " ".join(str(a) for call in mock_print.call_args_list for a in call.args)
        self.assertIn("backup_20240101.zip", combined)


class ListBackupsTests(unittest.TestCase):
    def test_empty_list_returns_zero(self):
        mgr = _mock_manager()
        mgr.list_backups.return_value = []
        with mock.patch.object(backup_cli, "get_backup_manager", return_value=mgr):
            rc = backup_cli.list_backups(_ns())
        self.assertEqual(rc, 0)

    def test_non_empty_list_returns_zero_and_prints(self):
        mgr = _mock_manager()
        mgr.list_backups.return_value = [
            {"name": "bk1", "size": 1024 * 1024, "created": "2024-01-01", "is_valid": True},
        ]
        with mock.patch.object(backup_cli, "get_backup_manager", return_value=mgr), \
             mock.patch("builtins.print") as mock_print:
            rc = backup_cli.list_backups(_ns())
        self.assertEqual(rc, 0)
        all_output = " ".join(str(a) for call in mock_print.call_args_list for a in call.args)
        self.assertIn("bk1", all_output)

    def test_exception_returns_one(self):
        mgr = _mock_manager()
        mgr.list_backups.side_effect = IOError("no access")
        with mock.patch.object(backup_cli, "get_backup_manager", return_value=mgr):
            rc = backup_cli.list_backups(_ns())
        self.assertEqual(rc, 1)


class RestoreBackupTests(unittest.TestCase):
    def test_success_returns_zero(self):
        mgr = _mock_manager()
        mgr.restore_backup.return_value = True
        with mock.patch.object(backup_cli, "get_backup_manager", return_value=mgr):
            rc = backup_cli.restore_backup(_ns(backup_file="bk.zip", target_dir="/dst"))
        self.assertEqual(rc, 0)

    def test_failure_returns_one(self):
        mgr = _mock_manager()
        mgr.restore_backup.return_value = False
        with mock.patch.object(backup_cli, "get_backup_manager", return_value=mgr):
            rc = backup_cli.restore_backup(_ns(backup_file="bk.zip", target_dir="/dst"))
        self.assertEqual(rc, 1)

    def test_exception_returns_one(self):
        mgr = _mock_manager()
        mgr.restore_backup.side_effect = RuntimeError("corrupt archive")
        with mock.patch.object(backup_cli, "get_backup_manager", return_value=mgr):
            rc = backup_cli.restore_backup(_ns(backup_file="bk.zip", target_dir="/dst"))
        self.assertEqual(rc, 1)


class DeleteBackupTests(unittest.TestCase):
    def test_success_returns_zero(self):
        mgr = _mock_manager()
        mgr.delete_backup.return_value = True
        with mock.patch.object(backup_cli, "get_backup_manager", return_value=mgr):
            rc = backup_cli.delete_backup(_ns(backup_file="bk.zip"))
        self.assertEqual(rc, 0)

    def test_failure_returns_one(self):
        mgr = _mock_manager()
        mgr.delete_backup.return_value = False
        with mock.patch.object(backup_cli, "get_backup_manager", return_value=mgr):
            rc = backup_cli.delete_backup(_ns(backup_file="bk.zip"))
        self.assertEqual(rc, 1)

    def test_exception_returns_one(self):
        mgr = _mock_manager()
        mgr.delete_backup.side_effect = OSError("file locked")
        with mock.patch.object(backup_cli, "get_backup_manager", return_value=mgr):
            rc = backup_cli.delete_backup(_ns(backup_file="bk.zip"))
        self.assertEqual(rc, 1)


class MainDispatchTests(unittest.TestCase):
    def test_no_subcommand_prints_help_returns_one(self):
        with mock.patch("sys.argv", ["backup_cli"]), \
             mock.patch("builtins.print"), \
             mock.patch("argparse.ArgumentParser.print_help"):
            rc = backup_cli.main()
        self.assertEqual(rc, 1)

    def test_create_subcommand_dispatched(self):
        mgr = _mock_manager()
        mgr.create_backup.return_value = "/tmp/bk.zip"
        with mock.patch("sys.argv", ["backup_cli", "create", "/src"]), \
             mock.patch.object(backup_cli, "get_backup_manager", return_value=mgr), \
             mock.patch("builtins.print"):
            rc = backup_cli.main()
        self.assertEqual(rc, 0)

    def test_list_subcommand_dispatched(self):
        mgr = _mock_manager()
        mgr.list_backups.return_value = []
        with mock.patch("sys.argv", ["backup_cli", "list"]), \
             mock.patch.object(backup_cli, "get_backup_manager", return_value=mgr), \
             mock.patch("builtins.print"):
            rc = backup_cli.main()
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
