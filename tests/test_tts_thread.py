"""
Unit tests for tts_thread.TTSThread.

pyttsx3 is typically absent in CI, so tests cover:
- No-op path when pyttsx3 is None (engine is None, run() returns immediately)
- stop() sets running=False
- is_speaking is False initially and flips during speech (via mock)
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

import tts_thread as _tts_mod  # noqa: E402
import optional_deps as _opt  # noqa: E402


class DaemonAndStopTests(unittest.TestCase):
    def test_thread_is_daemon(self):
        with mock.patch.object(_opt, "pyttsx3", None):
            from tts_thread import TTSThread
            t = TTSThread(queue.Queue())
        self.assertTrue(t.daemon)

    def test_stop_clears_running(self):
        with mock.patch.object(_opt, "pyttsx3", None):
            from tts_thread import TTSThread
            t = TTSThread(queue.Queue())
        t.stop()
        self.assertFalse(t.running)


class NoOpWhenPyttsx3AbsentTests(unittest.TestCase):
    def test_exits_immediately_without_pyttsx3(self):
        """run() must return quickly when pyttsx3 is None."""
        with mock.patch.object(_opt, "pyttsx3", None):
            # Re-import to pick up patched pyttsx3
            import importlib
            importlib.reload(_tts_mod)
            from tts_thread import TTSThread
            q = queue.Queue()
            t = TTSThread(q)
            self.assertIsNone(t.engine)
            t.start()
            t.join(timeout=2.0)
            self.assertFalse(t.is_alive())

    def tearDown(self):
        # Reload tts_thread with original optional_deps to not affect other tests
        import importlib
        importlib.reload(_tts_mod)


class IsSpeakingTests(unittest.TestCase):
    def test_is_speaking_false_initially(self):
        """Before any speech, is_speaking must be False."""
        mock_engine = mock.MagicMock()
        mock_pyttsx3 = mock.MagicMock()
        mock_pyttsx3.init.return_value = mock_engine

        with mock.patch.object(_opt, "pyttsx3", mock_pyttsx3):
            import importlib
            importlib.reload(_tts_mod)
            from tts_thread import TTSThread
            t = TTSThread(queue.Queue())

        self.assertFalse(t.is_speaking)

    def test_speak_sets_and_clears_is_speaking(self):
        """is_speaking is True during runAndWait and False after."""
        states = []
        mock_engine = mock.MagicMock()

        def capture_state():
            # Called during runAndWait; record is_speaking at that moment
            states.append(t.is_speaking)

        mock_engine.runAndWait.side_effect = capture_state
        mock_pyttsx3 = mock.MagicMock()
        mock_pyttsx3.init.return_value = mock_engine

        with mock.patch.object(_opt, "pyttsx3", mock_pyttsx3):
            import importlib
            importlib.reload(_tts_mod)
            from tts_thread import TTSThread
            q = queue.Queue()
            t = TTSThread(q)
            t.start()
            q.put("hello")
            # Give the thread time to process the item
            import time
            time.sleep(0.3)
            t.stop()
            t.join(timeout=2.0)

        self.assertEqual(states, [True])
        self.assertFalse(t.is_speaking)

    def tearDown(self):
        import importlib
        importlib.reload(_tts_mod)


if __name__ == "__main__":
    unittest.main()
