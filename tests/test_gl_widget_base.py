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
        "glLoadIdentity", "gluPerspective",
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
    def test_normal_aspect(self):
        with _GLPatch() as gl:
            _Widget().resizeGL(800, 400)
            gl.calls["gluPerspective"].assert_called_once_with(45.0, 2.0, 0.1, 100.0)
            gl.calls["glViewport"].assert_called_once_with(0, 0, 800, 400)

    def test_zero_height_does_not_divide_by_zero(self):
        with _GLPatch() as gl:
            # Must not raise ZeroDivisionError; falls back to aspect 1.0.
            _Widget().resizeGL(640, 0)
            gl.calls["gluPerspective"].assert_called_once_with(45.0, 1.0, 0.1, 100.0)


class NoOpWhenUnavailableTests(unittest.TestCase):
    def test_methods_are_noop_without_opengl(self):
        # With the real (likely False) flag, calls must be harmless no-ops.
        if gl_widget_base._GL_AVAILABLE:
            self.skipTest("OpenGL is installed; no-op path not exercised")
        _Widget().initializeGL()
        _Widget().resizeGL(640, 0)  # also must not crash


if __name__ == "__main__":
    unittest.main()
