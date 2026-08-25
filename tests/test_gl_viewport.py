"""GLViewportMixin — 射影行列と、GLU 非依存であることの検証。

## なぜ GLU を必須経路から外したか

`pip install PyOpenGL` はシステムライブラリ `libGLU.so` を導入しない。Linux の
クリーンな環境では PyOpenGL があっても GLU が無いことがある。そして厄介なのは
**その場合でも import が成功する**点である。PyOpenGL は呼び出し時に解決する
遅延バインディングを作るので、`from OpenGL.GLU import gluPerspective` は通り、
実際に呼んだ瞬間に `NullFunctionError` になる。

旧コードのガードは `except ImportError` で、これを捕まえられなかった。さらに
Qt は仮想メソッド（`resizeGL`）内で例外が出るとプロセスを **abort** するため、
Python の traceback すら残さず落ちた。この環境で実際に再現している:

    OpenGL.error.NullFunctionError: Attempt to call an undefined function
    gluPerspective, check for bool(gluPerspective) before calling
    Aborted

「任意依存が欠けても縮退して起動を継続する」という設計原則（SPECIFICATION
§1.1）に真っ向から反する。

対処として、欠落に備えるのではなく**依存そのものを消した**。
`gluPerspective(fovy, aspect, near, far)` はコアの `glFrustum` で厳密に
書き下せるので、GLU を呼ばずに同じ射影を積む。実際に GL 上で両者の
GL_PROJECTION_MATRIX を比較し、差が float32 の丸め幅（<5e-7）に収まることを
確認したうえで置き換えた。

このテストは GL を起動しない。**必須経路が GLU に触れないこと**という不変条件
そのものを検証するので、GLU の有無に関係なく意味を持つ。
"""
from __future__ import annotations

import math
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MAIN = os.path.join(_ROOT, "main")
sys.path.insert(0, _MAIN)

import gl_widget_base as glvb  # noqa: E402


class GluIndependenceTests(unittest.TestCase):
    """GLU への依存が**コードとして**存在しないことを検証する。

    生のソース文字列を走査してはいけない。この不変条件を説明する文章そのものが
    "gluPerspective" や "OpenGL.GLU" を含むため、コメントと実装を区別できない
    検査は自分の解説文に反応して落ちる（実際に一度そうなった）。AST で
    import 文と呼び出し式だけを見る。
    """

    def _tree(self):
        import ast
        with open(os.path.join(_MAIN, "gl_widget_base.py"), encoding="utf-8") as fh:
            return ast.parse(fh.read())

    def test_module_does_not_import_from_glu(self):
        import ast
        bad = []
        for node in ast.walk(self._tree()):
            if isinstance(node, ast.ImportFrom) and "GLU" in (node.module or ""):
                bad.append(node.module)
            elif isinstance(node, ast.Import):
                bad += [a.name for a in node.names if "GLU" in a.name]
        self.assertEqual(bad, [], f"必須経路が GLU を import している: {bad}")

    def test_module_calls_no_glu_function(self):
        import ast
        called = []
        for node in ast.walk(self._tree()):
            if isinstance(node, ast.Call):
                fn = node.func
                name = getattr(fn, "id", None) or getattr(fn, "attr", None) or ""
                if name.startswith("glu"):
                    called.append(name)
        self.assertEqual(called, [], f"GLU 関数を呼んでいる: {called}")

    def test_glu_is_not_in_the_module_namespace(self):
        leaked = [n for n in dir(glvb) if n.startswith("glu")]
        self.assertEqual(leaked, [], f"GLU 名が名前空間に居る: {leaked}")

    def test_perspective_uses_core_gl_only(self):
        """射影が glFrustum（コア GL）で構成されていること。"""
        self.assertTrue(hasattr(glvb, "glFrustum"))
        self.assertTrue(callable(glvb._apply_perspective))


class PerspectiveMathTests(unittest.TestCase):
    """glFrustum の引数が gluPerspective と同じ視錐台を表すこと。

    GL を起動せずに、仕様上の等式で検証する:
        top   = zNear * tan(fovy / 2)
        right = top * aspect
    """

    def _expected(self, aspect: float):
        top = glvb.Z_NEAR * math.tan(math.radians(glvb.FOV_Y_DEGREES) / 2.0)
        return -top * aspect, top * aspect, -top, top

    def test_frustum_bounds_match_the_gluperspective_formula(self):
        calls = []
        real = glvb.glFrustum
        try:
            glvb.glFrustum = lambda *a: calls.append(a)
            for aspect in (1.0, 16 / 9, 0.5, 4 / 3):
                calls.clear()
                glvb._apply_perspective(aspect)
                self.assertEqual(len(calls), 1)
                left, right, bottom, top, near, far = calls[0]
                e_left, e_right, e_bottom, e_top = self._expected(aspect)
                with self.subTest(aspect=aspect):
                    self.assertAlmostEqual(left, e_left, places=9)
                    self.assertAlmostEqual(right, e_right, places=9)
                    self.assertAlmostEqual(bottom, e_bottom, places=9)
                    self.assertAlmostEqual(top, e_top, places=9)
                    self.assertEqual(near, glvb.Z_NEAR)
                    self.assertEqual(far, glvb.Z_FAR)
        finally:
            glvb.glFrustum = real

    def test_defaults_match_the_previous_gluperspective_arguments(self):
        """置換前と同じ画角・クリップ面であること（見た目を変えていない）。"""
        self.assertEqual(glvb.FOV_Y_DEGREES, 45.0)
        self.assertEqual(glvb.Z_NEAR, 0.1)
        self.assertEqual(glvb.Z_FAR, 100.0)

    def test_zero_height_falls_back_to_square_aspect(self):
        """h=0 でゼロ除算しないこと（従来 7 ファイルにあったクラッシュ）。"""
        calls = []
        real_funcs = {}
        for name in ("glViewport", "glMatrixMode", "glLoadIdentity", "glFrustum"):
            real_funcs[name] = getattr(glvb, name)
        try:
            glvb.glViewport = lambda *a: None
            glvb.glMatrixMode = lambda *a: None
            glvb.glLoadIdentity = lambda *a: None
            glvb.glFrustum = lambda *a: calls.append(a)
            glvb.GLViewportMixin().resizeGL(640, 0)
        finally:
            for name, fn in real_funcs.items():
                setattr(glvb, name, fn)
        self.assertEqual(len(calls), 1)
        left, right, bottom, top, _, _ = calls[0]
        self.assertAlmostEqual(right, top, places=9)  # aspect 1.0


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
