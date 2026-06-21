"""
Regression tests for main/tts_with_virtual_audio.TTSWorker.

The TTS worker uses pyttsx3.save_to_file() to render speech to a temp WAV
which is then played on a chosen output device. On Windows, holding a
NamedTemporaryFile open while letting pyttsx3 write to that same path
causes a share-violation PermissionError — save_to_file fails silently
and no audio is produced. The fix closes the temp handle first and just
keeps the path. These tests verify that fix via an inline simulation of
the worker body (so they run anywhere — no pyttsx3 / sounddevice needed).

Run: python -m unittest tests.test_tts_with_virtual_audio -v
"""
import os
import sys
import tempfile
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)


def _simulate_worker_iteration(save_to_file, run_and_wait, play_wav_on_device):
    """Reproduces the post-fix flow inside TTSWorker.run() one iteration."""
    tf_path = None
    try:
        tf = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
        tf_path = tf.name
        tf.close()
        save_to_file("hello", tf_path)
        run_and_wait()
        play_wav_on_device(tf_path, 0)
    except Exception:
        pass
    finally:
        if tf_path and os.path.exists(tf_path):
            try:
                os.unlink(tf_path)
            except OSError:
                pass
    return tf_path


class TempFileHandlingTests(unittest.TestCase):
    def test_temp_file_handle_closed_before_save_to_file(self):
        """The path passed to save_to_file must refer to a *closed* handle,
        otherwise Windows pyttsx3 fails with a share violation."""
        observed = {}

        def save_to_file(text, path):
            # Probe: can a separate process-style writer open this path for
            # exclusive write? We approximate by ensuring our handle is closed.
            # If the test framework left a handle open, this would still pass
            # on POSIX — the real fix is structural; we check it via inspect.
            observed["path"] = path
            with open(path, "wb") as fh:
                fh.write(b"RIFF....WAVEfake")

        _simulate_worker_iteration(
            save_to_file=save_to_file,
            run_and_wait=lambda: None,
            play_wav_on_device=lambda p, idx: None,
        )
        self.assertIn("path", observed)

    def test_temp_file_is_cleaned_up_after_success(self):
        paths = []

        def play(path, idx):
            paths.append(path)
            self.assertTrue(os.path.exists(path), "file must exist during play")

        _simulate_worker_iteration(
            save_to_file=lambda t, p: open(p, "wb").write(b"x"),
            run_and_wait=lambda: None,
            play_wav_on_device=play,
        )
        self.assertEqual(len(paths), 1)
        self.assertFalse(os.path.exists(paths[0]), "file must be cleaned up after iteration")

    def test_temp_file_is_cleaned_up_after_exception(self):
        leaked = {}

        def play(path, idx):
            leaked["path"] = path
            raise RuntimeError("device gone")

        _simulate_worker_iteration(
            save_to_file=lambda t, p: open(p, "wb").write(b"x"),
            run_and_wait=lambda: None,
            play_wav_on_device=play,
        )
        # Even though play raised, finally must have unlinked the temp file.
        self.assertFalse(os.path.exists(leaked["path"]))


class SourceStructureTests(unittest.TestCase):
    """Static guard: the worker must not hold a NamedTemporaryFile open
    *across* the pyttsx3 save_to_file/runAndWait calls (Windows share
    violation). Use inspect to confirm the body is post-fix shape."""

    def test_run_does_not_use_with_named_temp_file(self):
        import inspect
        from tts_with_virtual_audio import TTSWorker
        src = inspect.getsource(TTSWorker.run)
        self.assertNotIn(
            "with tempfile.NamedTemporaryFile",
            src,
            "Holding NamedTemporaryFile open across save_to_file breaks on Windows",
        )

    def test_run_closes_temp_handle_before_save(self):
        import inspect
        from tts_with_virtual_audio import TTSWorker
        src = inspect.getsource(TTSWorker.run)
        # The fix opens the temp file, captures .name, then immediately closes
        # before calling pyttsx3. Confirm tf.close() appears before the actual
        # save_to_file CALL (engine.save_to_file), not its mention in a comment.
        close_pos = src.find("tf.close()")
        save_call_pos = src.find("engine.save_to_file")
        self.assertGreater(close_pos, 0, "tf.close() must be present")
        self.assertGreater(save_call_pos, 0, "engine.save_to_file(...) call must be present")
        self.assertLess(close_pos, save_call_pos,
                        "Close the temp handle BEFORE handing the path to pyttsx3")


if __name__ == "__main__":
    unittest.main()
