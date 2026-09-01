"""
任意（オプション）／必須依存パッケージの単一宣言。

`satin_launcher.py` の依存チェック（起動時の不足案内）と、将来の
requirements 生成・ドキュメント化の「唯一の真実の源」。従来は同等の一覧が
ランチャ内にハードコードされ、`setup/requirements*.txt` と二重管理になって
いた（仕様書 W5）。

このモジュールは **重い import を一切行わない**。numpy / cv2 / PyQt5 などの
実体 import は `optional_deps.py` が担う。ここは純粋なデータだけを持つので、
ランチャが軽量なまま `importlib.import_module` で存在確認できる。

各エントリは ``(import_name, pip_hint, purpose)`` の3要素タプル:
  - import_name: ``importlib.import_module`` に渡すモジュール名
  - pip_hint:    不足時にユーザーへ案内するインストールコマンド
  - purpose:     その依存が有効化する機能（ドキュメント用）
"""
from __future__ import annotations

from typing import List, Tuple

# (import_name, pip_hint, purpose)
OPTIONAL_PACKAGES: List[Tuple[str, str, str]] = [
    ("PyQt5",       "pip install PyQt5",            "3D アバター GUI"),
    ("OpenGL",      "pip install PyOpenGL",         "3D アバター描画 (OpenGL)"),
    ("numpy",       "pip install numpy",            "数値計算（ポーズ・幾何）"),
    ("pyttsx3",     "pip install pyttsx3",          "音声合成 (TTS)"),
    ("pygltflib",   "pip install pygltflib",        "glTF アバター読み込み"),
    ("flask",       "pip install flask",            "Web ダッシュボード"),
]

# (import_name, message) — これらが無いと起動できない。
#
# ここは REQUIRED_PACKAGES がランチャの *全モード* に対して起動前チェック
# されるため、あるモードでしか使わない依存を入れてはいけない（かつて
# tkinter がここにあり、tkinter を一切使わない --chat・--dashboard・
# --manage・--validate まで起動不能になっていた）。モード固有の依存は
# そのモードの try/except に任せる。現状、全モード共通の必須依存は無い。
#
# PIL(Pillow) も以前は任意依存に挙がっていたが、唯一の利用者だった
# avatar_loader.py（tkinter のサムネイル付きファイル選択ダイアログ）は、
# 本体 GUI の /avatar コマンドと機能が重複するため削除した。
REQUIRED_PACKAGES: List[Tuple[str, str]] = []


def optional_check_list() -> List[Tuple[str, str]]:
    """ランチャの依存チェック用に ``(import_name, pip_hint)`` の一覧を返す。"""
    return [(name, hint) for name, hint, _purpose in OPTIONAL_PACKAGES]


def required_check_list() -> List[Tuple[str, str]]:
    """ランチャの依存チェック用に ``(import_name, message)`` の一覧を返す。"""
    return list(REQUIRED_PACKAGES)
