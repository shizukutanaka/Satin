"""
Unit tests for avatar_3d_autonomous_or_camera.Avatar3DAutoOrCamViewer's pure
logic (mode switching, tick-based autonomous state cycling, camera pose
queue draining, persona-fallback text picking).

Qt/OpenGL are absent in CI, so instances are built via object.__new__ to
bypass the QOpenGLWidget-dependent __init__, following the pattern already
used in tests/test_avatar_event_timeline_viewer.py.
"""
import os
import queue
import sys
import unittest
from unittest import mock

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import avatar_3d_autonomous_or_camera as _mod  # noqa: E402


def _fake_viewer(**overrides):
    v = object.__new__(_mod.Avatar3DAutoOrCamViewer)
    defaults = dict(
        mode="autonomous",
        position=[0.0, 0.0],
        direction=0.0,
        ticks=0,
        talk_text="",
        talks=["a", "b"],
        pose_queue=queue.Queue(),
        cam_thread=None,
        current_pose=None,
    )
    defaults.update(overrides)
    for k, val in defaults.items():
        setattr(v, k, val)
    return v


class SetModeTests(unittest.TestCase):
    def test_same_mode_is_a_noop(self):
        """Setting the current mode again must not restart camera/reset state."""
        v = _fake_viewer(mode="autonomous", ticks=42)
        with mock.patch.object(_mod.Avatar3DAutoOrCamViewer, "update", create=True):
            v.set_mode("autonomous")
        self.assertEqual(v.ticks, 42, "no-op mode set must not reset autonomous state")

    def test_switch_to_camera_starts_camera_thread(self):
        v = _fake_viewer(mode="autonomous")
        with mock.patch.object(_mod, "CameraThread") as MockThread, \
             mock.patch.object(_mod.Avatar3DAutoOrCamViewer, "update", create=True):
            instance = MockThread.return_value
            instance.is_alive.return_value = False
            v.set_mode("camera")
        self.assertEqual(v.mode, "camera")
        MockThread.assert_called_once()
        instance.start.assert_called_once()

    def test_switch_to_autonomous_stops_camera_and_resets(self):
        fake_thread = mock.Mock()
        v = _fake_viewer(mode="camera", cam_thread=fake_thread, ticks=99, talk_text="hi")
        with mock.patch.object(_mod.Avatar3DAutoOrCamViewer, "update", create=True):
            v.set_mode("autonomous")
        self.assertEqual(v.mode, "autonomous")
        self.assertIsNone(v.cam_thread)
        self.assertFalse(fake_thread.running)
        self.assertEqual(v.ticks, 0)
        self.assertEqual(v.talk_text, "")


class ResetAutonomousTests(unittest.TestCase):
    def test_resets_position_ticks_and_talk_text(self):
        v = _fake_viewer(position=[1.0, 2.0], ticks=50, talk_text="hi")
        v.reset_autonomous()
        self.assertEqual(v.position, [0.0, 0.0])
        self.assertEqual(v.ticks, 0)
        self.assertEqual(v.talk_text, "")


class UpdateAutonomousTests(unittest.TestCase):
    """Tick-based state cycling: run (0-59) -> rest (60-99) -> talk (100-139)
    -> reset to 0 (>=140)."""

    def test_run_phase_does_not_set_talk_text(self):
        v = _fake_viewer(ticks=0, talk_text="stale")
        with mock.patch.object(_mod, "np", None):
            v.update_autonomous()
        self.assertEqual(v.ticks, 1)
        # Run phase leaves talk_text untouched by this call (still "stale" from before).
        self.assertEqual(v.talk_text, "stale")

    def test_rest_phase_sets_talk_text_via_fallback(self):
        v = _fake_viewer(ticks=59, talks=["only-choice"])
        with mock.patch.object(_mod, "get_persona", None):
            v.update_autonomous()
        self.assertEqual(v.ticks, 60)
        self.assertIn(v.talk_text, ["ふう…ちょっと休憩。", "すこし止まります。"])

    def test_talk_phase_uses_talks_fallback_list(self):
        v = _fake_viewer(ticks=99, talks=["only-choice"])
        with mock.patch.object(_mod, "get_persona", None):
            v.update_autonomous()
        self.assertEqual(v.ticks, 100)
        self.assertEqual(v.talk_text, "only-choice")

    def test_cycle_resets_at_140(self):
        v = _fake_viewer(ticks=139, talk_text="something")
        with mock.patch.object(_mod, "get_persona", None):
            v.update_autonomous()
        self.assertEqual(v.ticks, 0)
        self.assertEqual(v.talk_text, "")

    def test_persona_rest_text_used_when_available(self):
        v = _fake_viewer(ticks=59)
        fake_persona = mock.Mock()
        fake_persona.rest.return_value = "persona rest line"
        with mock.patch.object(_mod, "get_persona", return_value=fake_persona):
            v.update_autonomous()
        self.assertEqual(v.talk_text, "persona rest line")

    def test_persona_empty_string_falls_back_to_hardcoded(self):
        """If persona.rest() returns '' (falsy), the fallback array must be used."""
        v = _fake_viewer(ticks=59)
        fake_persona = mock.Mock()
        fake_persona.rest.return_value = ""
        with mock.patch.object(_mod, "get_persona", return_value=fake_persona):
            v.update_autonomous()
        self.assertIn(v.talk_text, ["ふう…ちょっと休憩。", "すこし止まります。"])


class UpdateCameraTests(unittest.TestCase):
    def test_drains_queue_and_keeps_latest_pose(self):
        v = _fake_viewer()
        v.pose_queue.put((1, 1, 1, 1, 1, 1))
        v.pose_queue.put((2, 2, 2, 2, 2, 2))
        v.update_camera()
        self.assertEqual(v.current_pose, (2, 2, 2, 2, 2, 2))
        self.assertTrue(v.pose_queue.empty())

    def test_empty_queue_leaves_current_pose_unchanged(self):
        v = _fake_viewer(current_pose="unchanged")
        v.update_camera()
        self.assertEqual(v.current_pose, "unchanged")

    def test_falsy_pose_does_not_overwrite_current_pose(self):
        """A falsy value (e.g. None) pulled from the queue must not clobber
        the last known-good pose, per `if pose:` guard."""
        v = _fake_viewer(current_pose="keep-me")
        v.pose_queue.put(None)
        v.update_camera()
        self.assertEqual(v.current_pose, "keep-me")


class StopCameraTests(unittest.TestCase):
    def test_stop_with_no_thread_is_safe(self):
        v = _fake_viewer(cam_thread=None)
        v.stop_camera()  # must not raise
        self.assertIsNone(v.current_pose)

    def test_stop_signals_running_false_and_clears_thread(self):
        fake_thread = mock.Mock()
        v = _fake_viewer(cam_thread=fake_thread)
        v.stop_camera()
        self.assertFalse(fake_thread.running)
        self.assertIsNone(v.cam_thread)


class PickTextFallbackTests(unittest.TestCase):
    def test_pick_talk_text_uses_talks_list_without_persona(self):
        v = _fake_viewer(talks=["only-option"])
        with mock.patch.object(_mod, "get_persona", None):
            self.assertEqual(v._pick_talk_text(), "only-option")

    def test_pick_talk_text_prefers_persona(self):
        v = _fake_viewer(talks=["fallback"])
        fake_persona = mock.Mock()
        fake_persona.talk.return_value = "persona talk line"
        with mock.patch.object(_mod, "get_persona", return_value=fake_persona):
            self.assertEqual(v._pick_talk_text(), "persona talk line")


if __name__ == "__main__":
    unittest.main()
