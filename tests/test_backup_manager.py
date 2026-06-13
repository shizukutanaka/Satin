"""
Unit tests for backup_manager.BackupManager.

Uses a temp directory for both the config path and the backup store so no
production files are touched. Cloud backup path is not tested (requires GCS).
"""
import os
import sys
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import backup_manager as bm_mod  # noqa: E402
from backup_manager import BackupManager  # noqa: E402


def _make_manager(tmp: str) -> BackupManager:
    """Create a BackupManager whose backup_dir lives under tmp."""
    cfg_path = os.path.join(tmp, "config.json")
    with open(cfg_path, "w") as f:
        json.dump({}, f)

    mock_cfg = mock.MagicMock()
    mock_cfg.config_path = cfg_path
    mock_cfg.get_plugin_config.return_value = None  # disable cloud

    with mock.patch.object(bm_mod, "get_config_manager", return_value=mock_cfg):
        mgr = BackupManager()
    return mgr


def _make_target(tmp: str, n: int = 3) -> str:
    """Create a target directory with n small text files."""
    target = os.path.join(tmp, "target")
    os.makedirs(target, exist_ok=True)
    for i in range(n):
        with open(os.path.join(target, f"file_{i}.txt"), "w") as f:
            f.write(f"content {i}")
    return target


class CreateBackupTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._mgr = _make_manager(self._tmp)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_creates_zip_file(self):
        target = _make_target(self._tmp)
        path = self._mgr.create_backup(target)
        self.assertTrue(os.path.exists(path))
        self.assertTrue(path.endswith(".zip"))

    def test_zip_is_valid(self):
        import zipfile
        target = _make_target(self._tmp)
        path = self._mgr.create_backup(target)
        with zipfile.ZipFile(path) as zf:
            self.assertIsNone(zf.testzip())

    def test_custom_backup_name_used(self):
        target = _make_target(self._tmp)
        path = self._mgr.create_backup(target, backup_name="my_backup")
        self.assertIn("my_backup", os.path.basename(path))

    def test_missing_target_raises(self):
        with self.assertRaises(FileNotFoundError):
            self._mgr.create_backup(os.path.join(self._tmp, "nonexistent"))

    def test_returned_path_exists(self):
        target = _make_target(self._tmp)
        path = self._mgr.create_backup(target)
        self.assertTrue(Path(path).exists())


class ListAndLatestTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._mgr = _make_manager(self._tmp)
        self._target = _make_target(self._tmp)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_list_empty_when_no_backups(self):
        self.assertEqual(self._mgr.list_backups(), [])

    def test_list_returns_one_entry_after_create(self):
        self._mgr.create_backup(self._target)
        backups = self._mgr.list_backups()
        self.assertEqual(len(backups), 1)

    def test_list_entry_has_expected_keys(self):
        self._mgr.create_backup(self._target)
        entry = self._mgr.list_backups()[0]
        for key in ("name", "path", "size", "created", "is_valid"):
            self.assertIn(key, entry)

    def test_list_entry_is_valid(self):
        self._mgr.create_backup(self._target)
        entry = self._mgr.list_backups()[0]
        self.assertTrue(entry["is_valid"])

    def test_get_latest_none_when_empty(self):
        self.assertIsNone(self._mgr.get_latest_backup())

    def test_get_latest_returns_path(self):
        self._mgr.create_backup(self._target)
        latest = self._mgr.get_latest_backup()
        self.assertIsNotNone(latest)
        self.assertTrue(latest.exists())


class RestoreAndDeleteTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._mgr = _make_manager(self._tmp)
        target = _make_target(self._tmp, n=2)
        self._backup_path = self._mgr.create_backup(target)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_restore_returns_true_on_success(self):
        restore_dir = os.path.join(self._tmp, "restored")
        result = self._mgr.restore_backup(self._backup_path, restore_dir)
        self.assertTrue(result)

    def test_restore_extracts_files(self):
        restore_dir = os.path.join(self._tmp, "restored2")
        self._mgr.restore_backup(self._backup_path, restore_dir)
        self.assertTrue(os.path.isdir(restore_dir))
        self.assertGreater(len(os.listdir(restore_dir)), 0)

    def test_restore_missing_backup_returns_false(self):
        result = self._mgr.restore_backup("/nonexistent/bk.zip", "/tmp/dst")
        self.assertFalse(result)

    def test_delete_returns_true(self):
        result = self._mgr.delete_backup(self._backup_path)
        self.assertTrue(result)

    def test_delete_removes_file(self):
        self._mgr.delete_backup(self._backup_path)
        self.assertFalse(os.path.exists(self._backup_path))

    def test_delete_missing_returns_false(self):
        result = self._mgr.delete_backup("/nonexistent/bk.zip")
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
