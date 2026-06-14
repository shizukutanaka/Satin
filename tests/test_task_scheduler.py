"""
Stdlib-only regression tests for the fixes in main/task_scheduler.py.

Run: python -m unittest tests.test_task_scheduler -v
"""
import os
import sys
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import threading  # noqa: E402
import time  # noqa: E402

from task_scheduler import (  # noqa: E402
    ScheduledTask, TaskScheduler, TaskStatus, TaskPriority,
)


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

    def test_delayed_task_runs_promptly(self):
        # Regression: a task scheduled during the loop's idle wait used to run
        # up to ~1s late because schedule() didn't wake the scheduler.
        sched = TaskScheduler(num_workers=1)
        sched.start()
        try:
            done = threading.Event()
            sched.schedule(lambda: done.set(), delay=0.1)
            # Should fire well under the old ~1s idle-sleep ceiling.
            self.assertTrue(done.wait(timeout=0.5))
        finally:
            sched.stop(wait=True)


class PeriodicCancellationTests(unittest.TestCase):
    """A periodic task reschedules itself; cancel_task must actually stop it,
    including when cancelled while the task body is executing (status RUNNING)."""

    def test_cancel_stops_periodic_rescheduling(self):
        sched = TaskScheduler(num_workers=1)
        sched.start()
        try:
            count = {"n": 0}

            def tick():
                count["n"] += 1

            tid = sched.schedule_periodic(tick, interval=0.05)
            time.sleep(0.32)            # let it fire several times
            sched.cancel_task(tid)
            runs_at_cancel = count["n"]
            self.assertGreater(runs_at_cancel, 1)  # it was actually running
            time.sleep(0.3)             # well past several more intervals
            # No further runs after cancellation (allow at most one in-flight).
            self.assertLessEqual(count["n"] - runs_at_cancel, 1)
        finally:
            sched.stop(wait=True)

    def test_cancel_while_executing_stops_reschedule(self):
        sched = TaskScheduler(num_workers=2)
        sched.start()
        try:
            count = {"n": 0}
            started = threading.Event()

            def slow():
                count["n"] += 1
                started.set()
                time.sleep(0.25)        # still running when we cancel

            tid = sched.schedule_periodic(slow, interval=0.05)
            self.assertTrue(started.wait(timeout=2))
            sched.cancel_task(tid)      # cancel mid-execution (status RUNNING)
            runs = count["n"]
            time.sleep(0.5)
            # The in-flight run finishes but must NOT reschedule another.
            self.assertEqual(count["n"], runs)
        finally:
            sched.stop(wait=True)


class StopSentinelCollisionTests(unittest.TestCase):
    """A LOW-priority task has queue-priority 0, identical to the (0, None)
    shutdown sentinel. Before the sequence-tiebreaker fix, having both in the
    PriorityQueue made heapq compare a ScheduledTask against None and raise
    TypeError, crashing stop()."""

    def test_stop_does_not_raise_with_queued_low_task(self):
        sched = TaskScheduler(num_workers=1)
        sched.start()
        try:
            sched.schedule(lambda: time.sleep(0.8))  # occupy the worker
            time.sleep(0.15)
            sched.schedule(lambda: None, priority=TaskPriority.LOW)
            time.sleep(0.05)

            result = {}
            def do_stop():
                try:
                    sched.stop(wait=True)
                    result["ok"] = True
                except Exception as e:  # pragma: no cover
                    result["ok"] = False
                    result["err"] = repr(e)

            t = threading.Thread(target=do_stop)
            t.start()
            t.join(timeout=8)
            self.assertTrue(result.get("ok"), msg=result.get("err", "stop() hung"))
        finally:
            sched.running = False

    def test_many_low_tasks_then_stop(self):
        sched = TaskScheduler(num_workers=2)
        sched.start()
        try:
            sched.schedule(lambda: time.sleep(0.4))
            sched.schedule(lambda: time.sleep(0.4))
            time.sleep(0.1)
            for _ in range(5):
                sched.schedule(lambda: None, priority=TaskPriority.LOW)
            sched.stop(wait=True)  # must not raise
        finally:
            sched.running = False

    def test_priority_ordering_preserved(self):
        sched = TaskScheduler(num_workers=1)
        sched.start()
        try:
            order = []
            sched.schedule(lambda: time.sleep(0.4))  # occupy worker
            time.sleep(0.05)
            sched.schedule(lambda: order.append("low"), priority=TaskPriority.LOW)
            sched.schedule(lambda: order.append("high"), priority=TaskPriority.HIGH)
            time.sleep(1.0)
            self.assertEqual(order, ["high", "low"])
        finally:
            sched.stop(wait=True)


if __name__ == "__main__":
    unittest.main()
