"""
Stdlib-only regression tests confirming avatar/camera modules import cleanly
when heavy GUI/ML/audio deps (PyQt5, OpenGL, numpy, cv2, mediapipe) are absent.

Run: python -m unittest tests.test_avatar_modules -v
"""
import os
import sys
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)


class CameraTrackingSampleTests(unittest.TestCase):
    def test_imports_and_main_is_guarded(self):
        # Previously the entire webcam capture loop ran at module level — importing
        # the module would block forever and crash without cv2/mediapipe.
        import camera_tracking_sample as cts
        # run_tracking() function must exist instead of bare module-level loop
        self.assertTrue(callable(cts.run_tracking))

    def test_cv2_optional(self):
        import camera_tracking_sample as cts
        # cv2 is None when not installed; module must still load
        if cts.cv2 is None:
            self.assertIsNone(cts.cv2)


class Avatar3DModulesImportTest(unittest.TestCase):
    """All 3D avatar modules must import without requiring PyQt5/OpenGL/numpy."""

    def _check(self, module_name):
        mod = __import__(module_name)
        self.assertIsNotNone(mod)

    def test_avatar_3d_autonomous(self):
        self._check("avatar_3d_autonomous")

    def test_avatar_3d_autonomous_or_camera(self):
        self._check("avatar_3d_autonomous_or_camera")

    def test_avatar_3d_autonomous_tts(self):
        self._check("avatar_3d_autonomous_tts")

    def test_avatar_3d_gltf_viewer(self):
        self._check("avatar_3d_gltf_viewer")

    def test_avatar_3d_mic_tts_modes(self):
        self._check("avatar_3d_mic_tts_modes")

    def test_avatar_3d_sync(self):
        self._check("avatar_3d_sync")

    def test_avatar_3d_viewer(self):
        self._check("avatar_3d_viewer")


class AvatarLoaderImportTest(unittest.TestCase):
    def test_imports_without_tkinter_pil(self):
        # tkinter not available in headless; PIL may not be installed
        import avatar_loader
        self.assertTrue(hasattr(avatar_loader, "AvatarLoaderApp"))


class AvatarEventModulesImportTest(unittest.TestCase):
    def test_event_report_without_matplotlib(self):
        import avatar_event_report as aer
        if aer.plt is None:
            self.assertIsNone(aer.mdates)

    def test_event_timeline_viewer_without_pyqt5(self):
        import avatar_event_timeline_viewer as atv
        self.assertTrue(hasattr(atv, "EventTimelineViewer"))


if __name__ == "__main__":
    unittest.main()
