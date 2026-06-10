"""
Regression test for the thread-unsafe zip-write bug in the batch manager modules.

comment_manager_batch / overlay_manager_batch / tts_manager_batch backed up
config files by calling batch_process(add_file, ...), which runs zf.write()
concurrently across ThreadPoolExecutor threads. zipfile.ZipFile is NOT
thread-safe, so the archive could be corrupted or raise. The fix writes
sequentially.

Run: python -m unittest tests.test_batch_backup_zip -v
"""
import glob
import inspect
import json
import os
import sys
import tempfile
import unittest
import zipfile

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import comment_manager_batch as cmb  # noqa: E402
import overlay_manager_batch as omb  # noqa: E402
import tts_manager_batch as tmb  # noqa: E402


class BatchBackupZipTests(unittest.TestCase):
    def _make_configs(self, d, prefix, n=12):
        for i in range(n):
            with open(os.path.join(d, f"{prefix}_{i:03d}.json"), "w", encoding="utf-8") as f:
                json.dump({"idx": i, "data": "x" * 100}, f)

    def _run_backup_and_check(self, module, prefix, backup_func):
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as d:
            self._make_configs(d, prefix)
            os.chdir(d)
            try:
                backup_func(d)
                zips = glob.glob(os.path.join(d, "*.zip"))
                self.assertEqual(len(zips), 1, "exactly one backup zip expected")
                # The archive must be valid (not corrupted by concurrent writes)
                with zipfile.ZipFile(zips[0]) as zf:
                    self.assertIsNone(zf.testzip(), "zip integrity check failed")
                    # all 12 source files must be present
                    self.assertEqual(len(zf.namelist()), 12)
            finally:
                os.chdir(cwd)

    def test_comment_backup_produces_valid_zip(self):
        self._run_backup_and_check(cmb, "comment_manager", cmb.batch_backup_comments)

    def test_overlay_backup_produces_valid_zip(self):
        # find the backup function name
        fn = getattr(omb, "batch_backup_overlays", None) or getattr(omb, "batch_backup_overlay", None)
        self.assertIsNotNone(fn, "overlay backup function not found")
        self._run_backup_and_check(omb, "overlay_manager", fn)

    def test_tts_backup_produces_valid_zip(self):
        fn = getattr(tmb, "batch_backup_tts", None)
        self.assertIsNotNone(fn, "tts backup function not found")
        self._run_backup_and_check(tmb, "tts_manager", fn)

    def test_zip_uses_flat_arcnames(self):
        """Regression: zf.write(fname) without arcname embedded absolute paths.
        After the fix, ZIP entries must use basename only (no directory separator)."""
        with tempfile.TemporaryDirectory() as d:
            self._make_configs(d, "comment_manager")
            cwd = os.getcwd()
            os.chdir(d)
            try:
                cmb.batch_backup_comments(d)
                zips = glob.glob(os.path.join(d, "*.zip"))
                with zipfile.ZipFile(zips[0]) as zf:
                    for name in zf.namelist():
                        self.assertNotIn("/", name, f"Expected flat arcname, got: {name}")
                        self.assertNotIn("\\", name)
            finally:
                os.chdir(cwd)

    def test_no_concurrent_zf_write(self):
        # Static guard: the shared backup helper must write files sequentially
        # (not via batch_process/ThreadPoolExecutor) to avoid zip corruption.
        import batch_config_utils as bcu
        src = inspect.getsource(bcu.backup_configs)
        # zf.write must appear inside a plain for-loop, not in a callable
        # passed to batch_process.
        self.assertIn("for fname in files", src)
        # batch_process must NOT appear in the backup path.
        self.assertNotIn("batch_process", src)


if __name__ == "__main__":
    unittest.main()
