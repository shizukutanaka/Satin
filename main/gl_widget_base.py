"""
OpenGL ウィジェットの共有ビューポート設定 Mixin。

8 個のアバター GL ウィジェットが同一の initializeGL() / resizeGL() を
重複して持っていたため共通化した。resizeGL は高さ 0 のときのゼロ除算を
ガードする（従来 7 ファイルは float(w)/float(h) で h=0 時にクラッシュ
し得たが、ここで一括修正）。

**GLU に依存しない。** 以前は射影行列を `gluPerspective` で作っていたが、
これには落とし穴が 2 つあった:

1. `pip install PyOpenGL` はシステムライブラリ `libGLU.so` を導入しない。
   Linux のクリーン環境では PyOpenGL が入っていても GLU が無いことがある。
2. その場合でも **import は成功する**。PyOpenGL は呼び出し時に解決する遅延
   バインディングを作るため、`from OpenGL.GLU import gluPerspective` は通り、
   実際に呼んだ瞬間に `NullFunctionError` になる。旧コードの
   `except ImportError` はこれを捕まえられず、しかも Qt は仮想メソッド内の
   例外で **abort する**ため、Python の traceback すら残さずプロセスごと落ちた。
   「任意依存が欠けても縮退して起動を継続する」という設計原則に反していた。

`gluPerspective(fovy, aspect, near, far)` はコアの `glFrustum` で厳密に
書き下せる（視錐台の上端 top = near·tan(fovy/2)、右端 right = top·aspect）。
実際に GL 上で両者の GL_PROJECTION_MATRIX を比較し、差が float32 の丸め幅
（<5e-7）に収まることを確認したうえで置き換えた。これで必須の描画経路から
GLU が消える — 依存を減らすことは、依存の欠落に備えることより確実である。

設定:
  - GL_CLEAR_COLOR: glClearColor へ渡す (r, g, b, a)。サブクラスで上書き可。
"""
from __future__ import annotations

import math

try:
    from OpenGL.GL import (  # noqa: F401
        glClearColor,
        glEnable,
        glViewport,
        glMatrixMode,
        glLoadIdentity,
        glFrustum,
        GL_DEPTH_TEST,
        GL_PROJECTION,
        GL_MODELVIEW,
    )
    _GL_AVAILABLE = True
except ImportError:
    _GL_AVAILABLE = False

#: 視野角（度）。従来の gluPerspective(45.0, ...) と同じ。
FOV_Y_DEGREES = 45.0
#: 近クリップ面・遠クリップ面。
Z_NEAR = 0.1
Z_FAR = 100.0


def _apply_perspective(aspect: float) -> None:
    """gluPerspective(FOV_Y_DEGREES, aspect, Z_NEAR, Z_FAR) と等価な射影を積む。

    GLU を使わずコアの glFrustum で構成する（理由は module docstring）。
    """
    top = Z_NEAR * math.tan(math.radians(FOV_Y_DEGREES) / 2.0)
    right = top * aspect
    glFrustum(-right, right, -top, top, Z_NEAR, Z_FAR)


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
        _apply_perspective(aspect)
        glMatrixMode(GL_MODELVIEW)
