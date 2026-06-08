"""
Regression tests for avatar_event_log_rotate.rotate_log().

Key bug fixed: backup cleanup used os.listdir('.') (CWD) instead of
the directory containing the logfile, so old backups were never found
when the logfile lived outside CWD, and os.remove(old) would fail
(bare filename, not full path) even when they were found.

Run: python -m unittest tests.test_avatar_event_log_rotate -v
"""
import gzip
import os
import sys
import tempfile
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from avatar_event_log_rotate import rotate_log  # noqa: E402


def _write_logfile(path, size_bytes):
    with open(path, "w", encoding="utf-8") as f:
        f.write("x" * size_bytes)


class RotateLogBasicTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_no_rotation_below_max_size(self):
        logfile = os.path.join(self._tmp, "app.log")
        _write_logfile(logfile, 100)
        rotate_log(logfile, max_size=1024, max_backups=5)
        # No .gz backup should have been created
        gz_files = [f for f in os.listdir(self._tmp) if f.endswith(".gz")]
        self.assertEqual(gz_files, [])
        # Original file must still exist and be untouched
        self.assertEqual(os.path.getsize(logfile), 100)

    def test_rotation_creates_gz_backup(self):
        logfile = os.path.join(self._tmp, "app.log")
        _write_logfile(logfile, 200)
        rotate_log(logfile, max_size=100, max_backups=5)
        gz_files = [f for f in os.listdir(self._tmp) if f.endswith(".gz")]
        self.assertEqual(len(gz_files), 1)
        # The rotated gz must contain the original content
        with gzip.open(os.path.join(self._tmp, gz_files[0]), "rt", encoding="utf-8") as gf:
            content = gf.read()
        self.assertEqual(content, "x" * 200)

    def test_rotation_truncates_original(self):
        logfile = os.path.join(self._tmp, "app.log")
        _write_logfile(logfile, 200)
        rotate_log(logfile, max_size=100, max_backups=5)
        self.assertEqual(os.path.getsize(logfile), 0)

    def test_nonexistent_logfile_does_not_raise(self):
        rotate_log(os.path.join(self._tmp, "missing.log"), max_size=1, max_backups=5)

    def test_old_backups_pruned_in_logfile_directory(self):
        """Regression: cleanup must scan logfile's dir, not CWD."""
        logfile = os.path.join(self._tmp, "app.log")
        # Create 4 existing fake backups in the logfile's directory
        for i in range(4):
            fake = os.path.join(self._tmp, f"app.log.2024010{i+1}_000000.gz")
            with gzip.open(fake, "wb") as gf:
                gf.write(b"old")
        # Now rotate (creates a 5th backup)
        _write_logfile(logfile, 200)
        rotate_log(logfile, max_size=100, max_backups=3)
        gz_files = sorted(f for f in os.listdir(self._tmp) if f.endswith(".gz"))
        # Only max_backups=3 newest should remain
        self.assertEqual(len(gz_files), 3)

    def test_old_backup_removal_uses_full_path(self):
        """os.remove must use full path, not bare filename (works outside CWD)."""
        orig_cwd = os.getcwd()
        try:
            # Change CWD away from the temp dir so bare-filename remove would fail
            os.chdir(os.path.dirname(self._tmp) or "/")
            logfile = os.path.join(self._tmp, "svc.log")
            # Pre-populate 6 backups
            for i in range(6):
                fake = os.path.join(self._tmp, f"svc.log.2024010{i+1}_000000.gz")
                with gzip.open(fake, "wb") as gf:
                    gf.write(b"old")
            _write_logfile(logfile, 200)
            # Should not raise even though CWD != logfile dir
            rotate_log(logfile, max_size=100, max_backups=2)
            gz_files = [f for f in os.listdir(self._tmp) if f.endswith(".gz")]
            self.assertLessEqual(len(gz_files), 2)
        finally:
            os.chdir(orig_cwd)


if __name__ == "__main__":
    unittest.main()
