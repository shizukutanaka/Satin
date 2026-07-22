"""
Tests for single_instance.SingleInstance — the multi-launch guard (W-01).

Two copies of the GUI writing config/mood.json / the conversation log / the
profile concurrently can corrupt state. The guard writes a PID lockfile and
refuses to start a second live instance, while auto-stealing a stale lock
left by a crashed process. pid / is_alive are injectable so a single test
process can simulate "another live instance".
"""
import os
import sys
import tempfile
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import single_instance as si  # noqa: E402


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._lock = os.path.join(self._tmp, "satin.lock")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)


class AcquireReleaseTests(_Base):
    def test_acquire_writes_own_pid(self):
        inst = si.SingleInstance(self._lock, pid=1234, is_alive=lambda p: True)
        self.assertTrue(inst.acquire())
        self.assertEqual(si._read_pid(self._lock), 1234)
        self.assertTrue(inst.acquired)

    def test_second_live_instance_is_refused(self):
        first = si.SingleInstance(self._lock, pid=1000, is_alive=lambda p: True)
        self.assertTrue(first.acquire())
        # another process (pid 2000) sees pid 1000 alive → refused
        second = si.SingleInstance(self._lock, pid=2000, is_alive=lambda p: True)
        self.assertFalse(second.acquire())
        self.assertFalse(second.acquired)

    def test_stale_lock_is_stolen(self):
        # pid 1000 crashed (not alive); a new process may take the lock.
        si._write_pid_atomic(self._lock, 1000)
        newcomer = si.SingleInstance(self._lock, pid=2000, is_alive=lambda p: False)
        self.assertTrue(newcomer.acquire())
        self.assertEqual(si._read_pid(self._lock), 2000)

    def test_release_removes_own_lock(self):
        inst = si.SingleInstance(self._lock, pid=1234, is_alive=lambda p: True)
        inst.acquire()
        inst.release()
        self.assertFalse(os.path.exists(self._lock))
        self.assertFalse(inst.acquired)

    def test_reacquire_after_release(self):
        a = si.SingleInstance(self._lock, pid=1000, is_alive=lambda p: True)
        a.acquire()
        a.release()
        b = si.SingleInstance(self._lock, pid=2000, is_alive=lambda p: True)
        self.assertTrue(b.acquire())

    def test_release_does_not_remove_someone_elses_lock(self):
        inst = si.SingleInstance(self._lock, pid=1000, is_alive=lambda p: True)
        inst.acquire()
        # someone else overwrote the lock with their pid
        si._write_pid_atomic(self._lock, 9999)
        inst.release()
        # inst must not have deleted the other holder's lock
        self.assertEqual(si._read_pid(self._lock), 9999)

    def test_release_without_acquire_is_noop(self):
        inst = si.SingleInstance(self._lock, pid=1234)
        inst.release()  # must not raise

    def test_context_manager_releases(self):
        with si.SingleInstance(self._lock, pid=1234, is_alive=lambda p: True) as inst:
            self.assertTrue(inst.acquire())
            self.assertTrue(os.path.exists(self._lock))
        self.assertFalse(os.path.exists(self._lock))

    def test_reacquire_by_same_pid_succeeds(self):
        # Re-running acquire() in the same process must not deadlock itself.
        inst = si.SingleInstance(self._lock, pid=1234, is_alive=lambda p: True)
        self.assertTrue(inst.acquire())
        self.assertTrue(inst.acquire())


class HelperTests(_Base):
    def test_read_pid_missing_returns_none(self):
        self.assertIsNone(si._read_pid(self._lock))

    def test_read_pid_corrupt_returns_none(self):
        with open(self._lock, "w", encoding="utf-8") as f:
            f.write("not a number")
        self.assertIsNone(si._read_pid(self._lock))

    def test_pid_alive_zero_is_false(self):
        self.assertFalse(si._pid_alive(0))
        self.assertFalse(si._pid_alive(-5))

    def test_pid_alive_self_is_true(self):
        self.assertTrue(si._pid_alive(os.getpid()))

    def test_pid_alive_unused_pid_is_false(self):
        # A very high PID is almost certainly not running.
        self.assertFalse(si._pid_alive(2_000_000_000))

    def test_write_pid_creates_parent_dir(self):
        nested = os.path.join(self._tmp, "a", "b", "satin.lock")
        si._write_pid_atomic(nested, 42)
        self.assertEqual(si._read_pid(nested), 42)


if __name__ == "__main__":
    unittest.main()
