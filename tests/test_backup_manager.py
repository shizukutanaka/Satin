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


class ZipSlipDefenseTests(unittest.TestCase):
    """Regression: restore_backup used shutil.unpack_archive which calls
    ZipFile.extractall without path sanitization. A malicious zip containing
    '../escaped.txt' or absolute paths could write files outside target_dir
    (arbitrary file write). The fix validates each entry's resolved path."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._mgr = _make_manager(self._tmp)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_malicious_zip(self, members):
        """Build a zip with the given (arcname, content) members."""
        import zipfile as _zf
        path = os.path.join(self._tmp, "evil.zip")
        # Use mode 'w' and write raw arcnames (including '../...' and absolutes).
        with _zf.ZipFile(path, "w") as zf:
            for arcname, content in members:
                zf.writestr(arcname, content)
        # Move into the manager's backup_dir so restore_backup() will accept it.
        target = os.path.join(self._mgr.backup_dir, "evil.zip")
        shutil.move(path, target)
        return target

    def test_traversal_entry_is_skipped(self):
        zip_path = self._make_malicious_zip([
            ("good.txt", b"ok"),
            ("../escaped.txt", b"PWNED"),
        ])
        restore_dir = os.path.join(self._tmp, "restore_target")
        ok = self._mgr.restore_backup(zip_path, restore_dir)
        self.assertTrue(ok)
        # Good entry restored, traversal entry NOT written above restore_dir.
        self.assertTrue(os.path.exists(os.path.join(restore_dir, "good.txt")))
        escaped_path = os.path.realpath(os.path.join(restore_dir, "..", "escaped.txt"))
        self.assertFalse(
            os.path.exists(escaped_path),
            f"Zip Slip: traversal entry escaped to {escaped_path}",
        )

    def test_absolute_path_entry_is_skipped(self):
        evil_target = os.path.join(self._tmp, "abs_escaped.txt")
        # Use a path absolute relative to the test tmp so we can assert it stays absent.
        zip_path = self._make_malicious_zip([
            ("good2.txt", b"ok"),
            (evil_target.lstrip("/"), b"PWNED_ABS"),
        ])
        restore_dir = os.path.join(self._tmp, "restore_abs")
        ok = self._mgr.restore_backup(zip_path, restore_dir)
        self.assertTrue(ok)
        self.assertTrue(os.path.exists(os.path.join(restore_dir, "good2.txt")))
        # The absolute-style path is rendered inside restore_dir (with the leading
        # slash stripped during join). Verify nothing was written to evil_target.
        self.assertFalse(os.path.exists(evil_target),
                         "Absolute-style entry must not write outside restore_dir")

    def test_normal_restore_still_works(self):
        # Regression guard: the rewrite must not break the happy path.
        target = _make_target(self._tmp, n=3)
        backup_path = self._mgr.create_backup(target)
        restore_dir = os.path.join(self._tmp, "restore_ok")
        self.assertTrue(self._mgr.restore_backup(backup_path, restore_dir))
        self.assertGreaterEqual(len(os.listdir(restore_dir)), 3)


@unittest.skipIf(os.name == "nt", "POSIX permission bits only")
class BackupPermissionTests(unittest.TestCase):
    """Regression: backup zip contained personal data (mood.json,
    user_profile.json, conversation log) but was world-readable (umask
    default), so other users on a shared machine could read it. The fix
    restricts it to owner-only after creation (fsutil.restrict_to_owner)."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._mgr = _make_manager(self._tmp)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_created_backup_is_owner_only(self):
        import stat
        target = _make_target(self._tmp, n=1)
        backup_path = self._mgr.create_backup(target)
        mode = stat.S_IMODE(os.stat(backup_path).st_mode)
        self.assertEqual(mode & 0o077, 0,
                         f"backup must not be readable by group/other; mode={oct(mode)}")


class CreateBackupAtomicityTests(unittest.TestCase):
    """Regression: create_backup() had shutil.make_archive write directly to
    the final backup path. A crash mid-write (or reusing backup_name) left a
    truncated/corrupt zip and destroyed any prior good backup at that path.
    Fix: write to a temp path under backup_dir, then os.replace atomically.
    """

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._mgr = _make_manager(self._tmp)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_reusing_backup_name_after_partial_write_preserves_old_backup(self):
        """A second create_backup() call that writes SOME bytes to whatever
        path make_archive() was given, then fails, must not corrupt the
        original good backup at backup_name — because the fix directs
        make_archive() at a distinct temp path, not backup_path directly.

        This fakes make_archive() by writing garbage to the path it's asked
        to produce (simulating a partial/truncated write) and then raising,
        rather than fully replacing the call — so it actually exercises
        whether the destination path itself was ever touched.
        """
        target = _make_target(self._tmp, n=2)
        path = self._mgr.create_backup(target, backup_name="daily")
        with open(path, "rb") as f:
            original_bytes = f.read()
        self.assertTrue(len(original_bytes) > 0)

        def fake_make_archive(base_name, fmt, root_dir):
            # Simulate a real archiver: write partial/garbage bytes to
            # <base_name>.zip, then crash before finishing.
            with open(base_name + ".zip", "wb") as f:
                f.write(b"PARTIAL-CORRUPT-DATA")
            raise OSError("disk full")

        with mock.patch.object(bm_mod.shutil, "make_archive", side_effect=fake_make_archive):
            with self.assertRaises(OSError):
                self._mgr.create_backup(target, backup_name="daily")

        # The original backup must be untouched, not truncated/corrupted —
        # only possible if make_archive wrote to a temp path, not backup_path.
        with open(path, "rb") as f:
            after_bytes = f.read()
        self.assertEqual(original_bytes, after_bytes,
                         "A failed re-create must not corrupt the prior good backup: "
                         "old bug wrote make_archive's output directly to backup_path.")

    def test_no_stray_temp_files_left_on_success(self):
        target = _make_target(self._tmp, n=1)
        self._mgr.create_backup(target, backup_name="clean")
        leftovers = [p for p in self._mgr.backup_dir.iterdir() if p.name.startswith(".")]
        self.assertEqual(leftovers, [], f"Temp files must be cleaned up: {leftovers}")


class GetLatestBackupRaceTests(unittest.TestCase):
    """Regression: get_latest_backup()'s sort key called x.stat() with no
    error handling, unlike list_backups(). A file removed between glob() and
    stat() (e.g. by a concurrent delete_backup() from backup_scheduler) raised
    an uncaught FileNotFoundError instead of the Optional[Path] the signature
    promises.
    """

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._mgr = _make_manager(self._tmp)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_file_removed_between_glob_and_stat_does_not_raise(self):
        target = _make_target(self._tmp, n=1)
        self._mgr.create_backup(target, backup_name="a")
        self._mgr.create_backup(target, backup_name="b")

        real_stat = Path.stat
        raised = {"done": False}

        def flaky_stat(self_path, *a, **kw):
            # Only simulate the race for the .zip files being sorted, not
            # internal directory-existence checks made by glob() itself.
            if self_path.suffix == ".zip" and not raised["done"]:
                raised["done"] = True
                raise FileNotFoundError("removed concurrently")
            return real_stat(self_path, *a, **kw)

        with mock.patch.object(Path, "stat", flaky_stat):
            result = self._mgr.get_latest_backup()
        self.assertIsNotNone(result, "Must still return a backup, not raise")


class ListBackupsTypeFieldTests(unittest.TestCase):
    """Regression: list_backups() labeled every backup's "type" via
    `"full" if "full_backup" in name else "incremental"`, but create_backup()
    never produces a name containing "full_backup" (default is
    backup_<timestamp>.zip) and there is no incremental-backup code path
    anywhere in the class. Every real backup was mislabeled "incremental"."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._mgr = _make_manager(self._tmp)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_default_name_backup_reports_full(self):
        target = _make_target(self._tmp, n=1)
        self._mgr.create_backup(target)  # default timestamped name
        entries = self._mgr.list_backups()
        self.assertEqual(entries[0]["type"], "full")

    def test_custom_name_without_full_backup_substring_still_reports_full(self):
        target = _make_target(self._tmp, n=1)
        self._mgr.create_backup(target, backup_name="daily_snapshot")
        entries = self._mgr.list_backups()
        self.assertEqual(entries[0]["type"], "full",
                         "Old bug: only names containing 'full_backup' were "
                         "labeled full; everything else was mislabeled incremental.")


class RestoreBackupAtomicityTests(unittest.TestCase):
    """Regression: restore_backup() extracted zip entries directly into
    target_dir one at a time. A failure partway through (corrupt entry, disk
    full) left already-extracted files in target_dir despite the method
    returning False, silently mutating the directory callers were told
    nothing had changed in.
    """

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._mgr = _make_manager(self._tmp)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_normal_restore_still_works(self):
        target = _make_target(self._tmp, n=3)
        backup_path = self._mgr.create_backup(target)
        restore_dir = os.path.join(self._tmp, "restored")
        ok = self._mgr.restore_backup(backup_path, restore_dir)
        self.assertTrue(ok)
        for i in range(3):
            self.assertTrue(os.path.exists(os.path.join(restore_dir, f"file_{i}.txt")))

    def test_failure_partway_through_leaves_target_dir_untouched(self):
        target = _make_target(self._tmp, n=3)
        backup_path = self._mgr.create_backup(target)
        restore_dir = os.path.join(self._tmp, "restored_partial")
        os.makedirs(restore_dir, exist_ok=True)

        real_copyfileobj = bm_mod.shutil.copyfileobj
        call_count = {"n": 0}

        def flaky_copyfileobj(src, dst, *a, **kw):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise OSError("disk full")
            return real_copyfileobj(src, dst, *a, **kw)

        with mock.patch.object(bm_mod.shutil, "copyfileobj", flaky_copyfileobj):
            ok = self._mgr.restore_backup(backup_path, restore_dir)

        self.assertFalse(ok)
        remaining = os.listdir(restore_dir)
        self.assertEqual(
            remaining, [],
            f"target_dir must be untouched on failure, found: {remaining}. "
            "Old bug: partially-extracted files were left behind despite "
            "returning False.",
        )

    def test_no_stray_staging_dirs_left_after_restore(self):
        target = _make_target(self._tmp, n=1)
        backup_path = self._mgr.create_backup(target)
        restore_dir = os.path.join(self._tmp, "restored2")
        self._mgr.restore_backup(backup_path, restore_dir)
        leftovers = [p for p in self._mgr.backup_dir.iterdir()
                    if p.is_dir() and p.name.startswith(".restore_staging_")]
        self.assertEqual(leftovers, [], f"Staging dirs must be cleaned up: {leftovers}")


if __name__ == "__main__":
    unittest.main()
