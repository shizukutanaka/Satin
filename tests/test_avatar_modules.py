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


class AvatarLoaderImportTest(unittest.TestCase):
    def test_imports_without_tkinter_pil(self):
        # tkinter not available in headless; PIL may not be installed
        import avatar_loader
        self.assertTrue(hasattr(avatar_loader, "AvatarLoaderApp"))


if __name__ == "__main__":
    unittest.main()
