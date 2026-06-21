"""
Unit tests for camera_thread.CameraThread.

OpenCV and mediapipe are typically absent in CI, so these tests cover:
- Thread exits immediately when cv2/mediapipe is unavailable (no-op path)
- stop() sets running=False so a live thread can terminate
- Thread is daemon by default
"""
import os
import queue
import sys
import threading
import unittest
from unittest import mock

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import camera_thread as _cam_mod  # noqa: E402
from camera_thread import CameraThread  # noqa: E402


class DaemonAndStopTests(unittest.TestCase):
    def test_thread_is_daemon(self):
        t = CameraThread(queue.Queue())
        self.assertTrue(t.daemon)

    def test_stop_clears_running(self):
        t = CameraThread(queue.Queue())
        self.assertTrue(t.running)
        t.stop()
        self.assertFalse(t.running)


class NoOpWhenDepsAbsentTests(unittest.TestCase):
    def test_exits_immediately_without_cv2(self):
        """run() must return quickly when cv2 is None (no camera access)."""
        with mock.patch.object(_cam_mod, "cv2", None):
            t = CameraThread(queue.Queue())
            t.start()
            t.join(timeout=2.0)
            self.assertFalse(t.is_alive(), "Thread should have exited after run() returned")

    def test_exits_immediately_without_mediapipe(self):
        with mock.patch.object(_cam_mod, "mp_face_mesh", None):
            t = CameraThread(queue.Queue())
            t.start()
            t.join(timeout=2.0)
            self.assertFalse(t.is_alive())


class PoseQueueBackpressureTests(unittest.TestCase):
    """Regression: pose_queue was an unbounded queue.Queue and the producer
    put() a frame every camera frame. If the consumer (Qt timer) stalls
    (window minimized, GL paused) the queue grows without bound. _enqueue_pose
    caps the backlog to the latest few frames."""

    def test_backlog_capped_when_consumer_stalls(self):
        q = queue.Queue()
        t = CameraThread(q)
        # Simulate a stalled consumer: push many frames, nobody drains.
        for i in range(1000):
            t._enqueue_pose((i, 0, 0, 0, 0, 0))
        self.assertLessEqual(q.qsize(), CameraThread._MAX_BACKLOG,
                             "pose queue must not grow unbounded when consumer stalls")

    def test_latest_frame_is_retained(self):
        q = queue.Queue()
        t = CameraThread(q)
        for i in range(10):
            t._enqueue_pose((i,))
        # Drain and confirm the most recent frame survived.
        drained = []
        while not q.empty():
            drained.append(q.get_nowait())
        self.assertIn((9,), drained, "the newest pose must be retained")

    def test_normal_flow_when_consumer_keeps_up(self):
        q = queue.Queue()
        t = CameraThread(q)
        # Producer/consumer in lockstep: each put is immediately drained.
        for i in range(5):
            t._enqueue_pose((i,))
            self.assertEqual(q.get_nowait(), (i,))
        self.assertTrue(q.empty())


if __name__ == "__main__":
    unittest.main()
