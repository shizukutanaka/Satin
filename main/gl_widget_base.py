"""
OpenGL ウィジェットの共有ビューポート設定 Mixin。

8 個のアバター GL ウィジェットが同一の initializeGL() / resizeGL() を
重複して持っていたため共通化した。resizeGL は高さ 0 のときのゼロ除算を
ガードする（従来 7 ファイルは float(w)/float(h) で h=0 時にクラッシュ
し得たが、ここで一括修正）。

設定:
  - GL_CLEAR_COLOR: glClearColor へ渡す (r, g, b, a)。サブクラスで上書き可。
"""
from __future__ import annotations

try:
    from OpenGL.GL import (  # noqa: F401
        glClearColor,
        glEnable,
        glViewport,
        glMatrixMode,
        glLoadIdentity,
        GL_DEPTH_TEST,
        GL_PROJECTION,
        GL_MODELVIEW,
    )
    from OpenGL.GLU import gluPerspective
    _GL_AVAILABLE = True
except ImportError:
    _GL_AVAILABLE = False


class GLViewportMixin:
    # glClearColor に渡す背景色 (r, g, b, a)
    GL_CLEAR_COLOR = (0.2, 0.2, 0.2, 1.0)

    def initializeGL(self) -> None:
        if not _GL_AVAILABLE:
            return
        glClearColor(*self.GL_CLEAR_COLOR)
        glEnable(GL_DEPTH_TEST)

    def resizeGL(self, w: int, h: int) -> None:
        if not _GL_AVAILABLE:
            return
        glViewport(0, 0, w, h)
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        # h=0 でのゼロ除算を回避（アスペクト比 1 にフォールバック）
        aspect = float(w) / float(h) if h else 1.0
        gluPerspective(45.0, aspect, 0.1, 100.0)
        glMatrixMode(GL_MODELVIEW)
