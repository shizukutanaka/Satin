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
    ("PIL",         "pip install pillow",           "画像処理（テクスチャ等）"),
    ("numpy",       "pip install numpy",            "数値計算（ポーズ・幾何）"),
    ("cv2",         "pip install opencv-python",    "Web カメラ入力"),
    ("mediapipe",   "pip install mediapipe",        "顔ランドマーク推定"),
    ("pyttsx3",     "pip install pyttsx3",          "音声合成 (TTS)"),
    ("sounddevice", "pip install sounddevice",      "仮想オーディオ出力"),
    ("pygltflib",   "pip install pygltflib",        "glTF アバター読み込み"),
    ("flask",       "pip install flask",            "Web ダッシュボード"),
    ("psutil",      "pip install psutil",           "パフォーマンス監視"),
    ("tenacity",    "pip install tenacity",         "非同期リトライ"),
    ("httpx",       "pip install httpx",            "非同期 HTTP 統合"),
    ("matplotlib",  "pip install matplotlib",       "イベント／好感度のグラフ"),
    ("pydub",       "pip install pydub",            "音声ファイル変換"),
    ("bs4",         "pip install beautifulsoup4",   "Web コンテンツ解析"),
    ("selenium",    "pip install selenium",         "動的ページ取得"),
    ("tqdm",        "pip install tqdm",             "バッチ進捗表示"),
]

# (import_name, message) — これらが無いと起動できない。
REQUIRED_PACKAGES: List[Tuple[str, str]] = [
    ("tkinter", "Python 標準 tkinter が見つかりません。Python を再インストールしてください。"),
]


def optional_check_list() -> List[Tuple[str, str]]:
    """ランチャの依存チェック用に ``(import_name, pip_hint)`` の一覧を返す。"""
    return [(name, hint) for name, hint, _purpose in OPTIONAL_PACKAGES]


def required_check_list() -> List[Tuple[str, str]]:
    """ランチャの依存チェック用に ``(import_name, message)`` の一覧を返す。"""
    return list(REQUIRED_PACKAGES)
