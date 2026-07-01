"""
Unit tests for avatar_3d_mic_tts_modes: MicVolumeThread's graceful-degradation
path and Avatar3DModesViewer's pure logic (mode switching, mouth-open
computation, TTS queueing).

Qt/OpenGL are absent in CI, so Avatar3DModesViewer instances are built via
object.__new__ to bypass the QOpenGLWidget-dependent __init__, following the
pattern already used in tests/test_avatar_event_timeline_viewer.py.
"""
import os
import queue
import sys
import unittest
from unittest import mock

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import avatar_3d_mic_tts_modes as _mod  # noqa: E402


def _fake_viewer(**overrides):
    v = object.__new__(_mod.Avatar3DModesViewer)
    defaults = dict(
        mouth_open=0.0,
        mode="mic",
        mic_thread=None,
        tts_thread=None,
        tts_queue=None,
        is_tts_speaking=False,
    )
    defaults.update(overrides)
    for k, val in defaults.items():
        setattr(v, k, val)
    return v


class MicVolumeThreadTests(unittest.TestCase):
    def test_initial_state(self):
        t = _mod.MicVolumeThread()
        self.assertTrue(t.daemon)
        self.assertTrue(t.running)
        self.assertEqual(t.volume, 0.0)

    def test_run_returns_immediately_without_np_or_sd(self):
        """run() must no-op (not raise) when numpy/sounddevice are unavailable —
        the exact situation in this test environment (both are None)."""
        t = _mod.MicVolumeThread()
        with mock.patch.object(_mod, "np", None), mock.patch.object(_mod, "sd", None):
            t.run()  # must return immediately, not raise or block


class SetModeTests(unittest.TestCase):
    def test_switch_mode_resets_mouth_open(self):
        v = _fake_viewer(mode="mic", mouth_open=0.7)
        with mock.patch.object(_mod.Avatar3DModesViewer, "update", create=True):
            v.set_mode("tts")
        self.assertEqual(v.mode, "tts")
        self.assertEqual(v.mouth_open, 0.0)


class TtsSpeakTests(unittest.TestCase):
    def test_puts_text_on_queue_when_present(self):
        v = _fake_viewer(tts_queue=queue.Queue())
        v.tts_speak("hello")
        self.assertEqual(v.tts_queue.get_nowait(), "hello")

    def test_noop_without_queue(self):
        v = _fake_viewer(tts_queue=None)
        v.tts_speak("hello")  # must not raise


class UpdateMouthTests(unittest.TestCase):
    def test_mic_mode_reflects_thread_volume(self):
        mic = mock.Mock(volume=0.42)
        v = _fake_viewer(mode="mic", mic_thread=mic)
        with mock.patch.object(_mod.Avatar3DModesViewer, "update", create=True):
            v.update_mouth()
        self.assertEqual(v.mouth_open, 0.42)

    def test_mic_mode_without_thread_closes_mouth(self):
        v = _fake_viewer(mode="mic", mic_thread=None, mouth_open=0.9)
        with mock.patch.object(_mod.Avatar3DModesViewer, "update", create=True):
            v.update_mouth()
        self.assertEqual(v.mouth_open, 0.0)

    def test_tts_mode_opens_mouth_while_speaking(self):
        tts = mock.Mock(is_speaking=True)
        v = _fake_viewer(mode="tts", tts_thread=tts)
        with mock.patch.object(_mod.Avatar3DModesViewer, "update", create=True):
            v.update_mouth()
        self.assertEqual(v.mouth_open, 1.0)

    def test_tts_mode_closes_mouth_when_not_speaking(self):
        tts = mock.Mock(is_speaking=False)
        v = _fake_viewer(mode="tts", tts_thread=tts, mouth_open=1.0)
        with mock.patch.object(_mod.Avatar3DModesViewer, "update", create=True):
            v.update_mouth()
        self.assertEqual(v.mouth_open, 0.0)

    def test_tts_mode_without_thread_closes_mouth(self):
        v = _fake_viewer(mode="tts", tts_thread=None, mouth_open=1.0)
        with mock.patch.object(_mod.Avatar3DModesViewer, "update", create=True):
            v.update_mouth()
        self.assertEqual(v.mouth_open, 0.0)


class ThreadSetterTests(unittest.TestCase):
    def test_set_mic_thread_stores_reference(self):
        v = _fake_viewer()
        sentinel = object()
        v.set_mic_thread(sentinel)
        self.assertIs(v.mic_thread, sentinel)

    def test_set_tts_thread_stores_reference(self):
        v = _fake_viewer()
        sentinel = object()
        v.set_tts_thread(sentinel)
        self.assertIs(v.tts_thread, sentinel)

    def test_set_tts_queue_stores_reference(self):
        v = _fake_viewer()
        q = queue.Queue()
        v.set_tts_queue(q)
        self.assertIs(v.tts_queue, q)


if __name__ == "__main__":
    unittest.main()
