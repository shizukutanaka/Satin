"""
Stdlib-only regression tests for the fixes in main/task_scheduler.py.

Run: python -m unittest tests.test_task_scheduler -v
"""
import os
import sys
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from task_scheduler import ScheduledTask, TaskScheduler, TaskStatus  # noqa: E402


class ScheduledTaskRetryTests(unittest.TestCase):
    def test_retries_until_success(self):
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise ValueError("transient")
            return "ok"

        task = ScheduledTask(priority=0, scheduled_time=0, task_id="x",
                             func=flaky, max_retries=3)
        # Previously returned None on the first failure and stayed PENDING forever.
        self.assertEqual(task.run(), "ok")
        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertEqual(calls["n"], 3)

    def test_exhausted_retries_fail_and_raise(self):
        def always_fail():
            raise RuntimeError("boom")

        task = ScheduledTask(priority=0, scheduled_time=0, task_id="y",
                             func=always_fail, max_retries=2)
        with self.assertRaises(RuntimeError):
            task.run()
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertEqual(task.retries, 2)


class SchedulerEndToEndTests(unittest.TestCase):
    def test_schedule_and_get_result(self):
        sched = TaskScheduler(num_workers=2)
        sched.start()
        try:
            tid = sched.schedule(lambda a, b: a + b, args=(2, 3))
            result = sched.get_task_result(tid, timeout=5)
            self.assertEqual(result, 5)
        finally:
            sched.stop(wait=True)

    def test_cancelled_task_is_not_run(self):
        sched = TaskScheduler(num_workers=1)
        # don't start workers; schedule a delayed task then cancel it
        tid = sched.schedule(lambda: 1 / 0, delay=10)
        self.assertTrue(sched.cancel_task(tid))
        self.assertEqual(sched.get_task_status(tid), TaskStatus.CANCELLED)


if __name__ == "__main__":
    unittest.main()
