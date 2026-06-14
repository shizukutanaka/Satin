"""
Tests for fsutil.restrict_to_owner — best-effort owner-only file permissions
for private data (conversation history, affinity).

Run: python -m unittest tests.test_fsutil -v
"""
import os
import stat
import sys
import tempfile
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from fsutil import restrict_to_owner  # noqa: E402


class RestrictToOwnerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._path = os.path.join(self._tmp, "secret.txt")
        with open(self._path, "w") as f:
            f.write("private")
        os.chmod(self._path, 0o644)  # start world-readable

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_makes_file_owner_only(self):
        self.assertTrue(restrict_to_owner(self._path))
        mode = stat.S_IMODE(os.stat(self._path).st_mode)
        self.assertEqual(mode & 0o077, 0)  # no group/other bits

    def test_owner_can_still_read_write(self):
        restrict_to_owner(self._path)
        mode = stat.S_IMODE(os.stat(self._path).st_mode)
        self.assertTrue(mode & stat.S_IRUSR)
        self.assertTrue(mode & stat.S_IWUSR)

    def test_missing_file_returns_false_no_raise(self):
        result = restrict_to_owner(os.path.join(self._tmp, "nope.txt"))
        self.assertFalse(result)  # must not raise


if __name__ == "__main__":
    unittest.main()
