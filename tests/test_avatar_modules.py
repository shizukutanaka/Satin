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


class NoTkinterDependencyTest(unittest.TestCase):
    """tkinter / Pillow に依存するモジュールが残っていないこと。

    唯一の利用者だった avatar_loader.py（サムネイル付きファイル選択
    ダイアログ）は、本体 GUI の /avatar と機能が重複するため削除した。
    再び忍び込むと、ヘッドレス環境（--chat / --dashboard / CI）で
    import 不能なモジュールが増える。
    """

    def test_no_module_imports_tkinter_or_pil(self):
        import ast
        import glob
        offenders = []
        for path in glob.glob(os.path.join(_MAIN, "**", "*.py"), recursive=True):
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=path)
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                for name in names:
                    root = name.split(".")[0]
                    if root in ("tkinter", "PIL"):
                        offenders.append(f"{os.path.basename(path)}: {name}")
        self.assertEqual(offenders, [], f"tkinter/PIL への依存が復活している: {offenders}")


if __name__ == "__main__":
    unittest.main()
