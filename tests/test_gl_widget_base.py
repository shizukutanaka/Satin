"""
Unit tests for gl_widget_base.GLViewportMixin — the shared OpenGL viewport
setup extracted from the 8 avatar GL widgets.

OpenGL is typically not installed in CI, so these tests patch the module-level
GL functions and the _GL_AVAILABLE flag to exercise the real logic (notably the
h=0 divide-by-zero guard and the configurable clear color).
"""
import os
import sys
import unittest
from unittest import mock

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import gl_widget_base  # noqa: E402
from gl_widget_base import GLViewportMixin  # noqa: E402


class _Widget(GLViewportMixin):
    pass


class _BlueWidget(GLViewportMixin):
    GL_CLEAR_COLOR = (0.8, 0.9, 1.0, 1.0)


class _GLPatch:
    """Patch the GL symbols gl_widget_base imported, plus _GL_AVAILABLE=True."""

    NAMES = (
        "glClearColor", "glEnable", "glViewport", "glMatrixMode",
        "glLoadIdentity", "glFrustum",
    )
    # GL constants are also undefined when OpenGL is not installed.
    CONSTANTS = ("GL_DEPTH_TEST", "GL_PROJECTION", "GL_MODELVIEW")

    def __enter__(self):
        self._patchers = [mock.patch.object(gl_widget_base, "_GL_AVAILABLE", True)]
        self.calls = {}
        for name in self.NAMES:
            m = mock.MagicMock(name=name)
            self.calls[name] = m
            self._patchers.append(mock.patch.object(gl_widget_base, name, m, create=True))
        for const in self.CONSTANTS:
            self._patchers.append(
                mock.patch.object(gl_widget_base, const, object(), create=True)
            )
        for p in self._patchers:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patchers:
            p.stop()
        return False


class InitializeGLTests(unittest.TestCase):
    def test_default_clear_color(self):
        with _GLPatch() as gl:
            _Widget().initializeGL()
            gl.calls["glClearColor"].assert_called_once_with(0.2, 0.2, 0.2, 1.0)

    def test_overridden_clear_color(self):
        with _GLPatch() as gl:
            _BlueWidget().initializeGL()
            gl.calls["glClearColor"].assert_called_once_with(0.8, 0.9, 1.0, 1.0)


class ResizeGLTests(unittest.TestCase):
    """射影は GLU ではなくコアの glFrustum で積む（gl_widget_base の docstring 参照）。

    `gluPerspective(fovy, aspect, near, far)` と等価な視錐台は
        top = near * tan(fovy / 2), right = top * aspect
    で、glFrustum(-right, right, -top, top, near, far) になる。
    """

    def _expected_bounds(self, aspect):
        import math
        top = 0.1 * math.tan(math.radians(45.0) / 2.0)
        right = top * aspect
        return -right, right, -top, top

    def _assert_frustum(self, mock_call, aspect):
        mock_call.assert_called_once()
        left, right, bottom, top, near, far = mock_call.call_args[0]
        e_left, e_right, e_bottom, e_top = self._expected_bounds(aspect)
        self.assertAlmostEqual(left, e_left, places=9)
        self.assertAlmostEqual(right, e_right, places=9)
        self.assertAlmostEqual(bottom, e_bottom, places=9)
        self.assertAlmostEqual(top, e_top, places=9)
        self.assertEqual(near, 0.1)
        self.assertEqual(far, 100.0)

    def test_normal_aspect(self):
        with _GLPatch() as gl:
            _Widget().resizeGL(800, 400)
            self._assert_frustum(gl.calls["glFrustum"], 2.0)
            gl.calls["glViewport"].assert_called_once_with(0, 0, 800, 400)

    def test_zero_height_does_not_divide_by_zero(self):
        with _GLPatch() as gl:
            # Must not raise ZeroDivisionError; falls back to aspect 1.0.
            _Widget().resizeGL(640, 0)
            self._assert_frustum(gl.calls["glFrustum"], 1.0)


class NoOpWhenUnavailableTests(unittest.TestCase):
    def test_methods_are_noop_without_opengl(self):
        # With the real (likely False) flag, calls must be harmless no-ops.
        if gl_widget_base._GL_AVAILABLE:
            self.skipTest("OpenGL is installed; no-op path not exercised")
        _Widget().initializeGL()
        _Widget().resizeGL(640, 0)  # also must not crash


if __name__ == "__main__":
    unittest.main()
