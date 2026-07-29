"""
Satin のバージョン単一宣言。

従来 `.py` 側にバージョン定数が無く、版は `config/config.json` の "version"
だけだった。パッケージ配布・バグ報告で版を機械的に特定できるよう、ここを
コード側の唯一の宣言点とする。`config/config.json` の "version" と一致させる
（`tests/test_version.py` が整合を検証）。
"""
from __future__ import annotations

__version__ = "1.1.0"


def get_version() -> str:
    """アプリのバージョン文字列を返す。"""
    return __version__
