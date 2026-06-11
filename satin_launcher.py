"""
Satin ランチャー

起動フロー:
1. 依存パッケージの存在チェック（不足があれば案内）
2. 設定ファイルの有無を確認
3. GUI が利用可能なら Avatar Loader を起動、そうでなければ CLI 管理ツールを起動

コマンドライン引数:
  --chat        ヘッドレスでアバターと会話する CLI を起動
  --dashboard   Flask ダッシュボードを起動
  --manage      CLI 管理バッチツールを起動
  --validate    設定バリデーションのみ実行して終了
  --help / -h   ヘルプを表示して終了
"""
from __future__ import annotations

import argparse
import importlib
import os
import sys

# launch/ スクリプトはリポジトリルートから起動する想定だが、
# main/ ディレクトリを sys.path に追加しておく。
_ROOT = os.path.dirname(os.path.abspath(__file__))
_MAIN = os.path.join(_ROOT, "main")
if _MAIN not in sys.path:
    sys.path.insert(0, _MAIN)

# --------------------------------------------------------------------------- #
# 依存チェック
# --------------------------------------------------------------------------- #
_OPTIONAL_DEPS: list[tuple[str, str]] = [
    ("PyQt5",       "pip install PyQt5"),
    ("PIL",         "pip install pillow"),
    ("numpy",       "pip install numpy"),
    ("cv2",         "pip install opencv-python"),
    ("mediapipe",   "pip install mediapipe"),
    ("pyttsx3",     "pip install pyttsx3"),
    ("sounddevice", "pip install sounddevice"),
    ("pygltflib",   "pip install pygltflib"),
    ("flask",       "pip install flask"),
    ("psutil",      "pip install psutil"),
    ("tenacity",    "pip install tenacity"),
    ("httpx",       "pip install httpx"),
    ("matplotlib",  "pip install matplotlib"),
    ("pydub",       "pip install pydub"),
    ("bs4",         "pip install beautifulsoup4"),
    ("selenium",    "pip install selenium"),
    ("tqdm",        "pip install tqdm"),
]

_REQUIRED_DEPS: list[tuple[str, str]] = [
    ("tkinter", "Python 標準 tkinter が見つかりません。Python を再インストールしてください。"),
]


def _check_deps(verbose: bool = False) -> list[str]:
    missing_optional: list[str] = []
    for pkg, hint in _REQUIRED_DEPS:
        try:
            importlib.import_module(pkg)
        except ImportError:
            print(f"[ERROR] 必須パッケージ不足: {pkg} — {hint}", file=sys.stderr)
            sys.exit(1)

    for pkg, hint in _OPTIONAL_DEPS:
        try:
            importlib.import_module(pkg)
        except ImportError:
            missing_optional.append(f"  {pkg:15s}  →  {hint}")

    if missing_optional and verbose:
        print("[INFO] 以下のオプションパッケージが未インストールです（一部機能が無効になります）:")
        for m in missing_optional:
            print(m)

    return missing_optional


# --------------------------------------------------------------------------- #
# 設定チェック
# --------------------------------------------------------------------------- #
def _check_config() -> None:
    config_dir = os.path.join(_ROOT, "config")
    if not os.path.isdir(config_dir):
        print("[WARN] config/ ディレクトリが見つかりません。デフォルト設定で起動します。")


# --------------------------------------------------------------------------- #
# 各起動モード
# --------------------------------------------------------------------------- #
def _launch_avatar_loader() -> None:
    try:
        import tkinter as tk
        from avatar_loader import AvatarLoaderApp
        root = tk.Tk()
        AvatarLoaderApp(root)
        root.mainloop()
    except ImportError as e:
        print(f"[ERROR] GUI 起動失敗: {e}", file=sys.stderr)
        sys.exit(1)


def _launch_dashboard(host: str = "127.0.0.1", port: int = 5000) -> None:
    try:
        from dashboard import app
        print(f"[INFO] ダッシュボードを http://{host}:{port} で起動します")
        app.run(host=host, port=port, debug=False)
    except ImportError as e:
        print(f"[ERROR] Flask ダッシュボード起動失敗: {e}", file=sys.stderr)
        sys.exit(1)


def _launch_chat() -> None:
    """ヘッドレスのペルソナ対話 CLI を起動する（GUI 不要）。"""
    from persona_cli import run_chat
    run_chat()


def _launch_manage() -> None:
    from manage_satin import validate_configs
    validate_configs(os.path.join(_ROOT, "config"))


def _launch_validate() -> None:
    from manage_satin import validate_configs
    validate_configs(os.path.join(_ROOT, "config"))
    print("[INFO] バリデーション完了")


# --------------------------------------------------------------------------- #
# エントリポイント
# --------------------------------------------------------------------------- #
def main() -> None:
    parser = argparse.ArgumentParser(
        prog="satin_launcher",
        description="Satin ランチャー",
    )
    parser.add_argument("--chat",      action="store_true", help="ヘッドレスでアバターと会話する CLI を起動")
    parser.add_argument("--dashboard", action="store_true", help="Flask ダッシュボードを起動")
    parser.add_argument("--manage",    action="store_true", help="CLI 管理バッチツールを起動")
    parser.add_argument("--validate",  action="store_true", help="設定バリデーションのみ実行して終了")
    parser.add_argument("--host",      default="127.0.0.1", help="ダッシュボードのホスト (default: 127.0.0.1)")
    parser.add_argument("--port",      type=int, default=5000, help="ダッシュボードのポート (default: 5000)")
    parser.add_argument("--no-dep-check", action="store_true", help="依存チェックをスキップ")
    args = parser.parse_args()

    if not args.no_dep_check:
        _check_deps(verbose=True)

    _check_config()

    if args.validate:
        _launch_validate()
    elif args.chat:
        _launch_chat()
    elif args.manage:
        _launch_manage()
    elif args.dashboard:
        _launch_dashboard(host=args.host, port=args.port)
    else:
        # デフォルト: GUI アバターローダーを起動
        _launch_avatar_loader()


if __name__ == "__main__":
    main()
