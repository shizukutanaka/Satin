"""
Satin ランチャー

起動フロー:
1. 依存パッケージの存在チェック（不足があれば案内）
2. 設定ファイルの有無を確認
3. GUI が利用可能なら Avatar Loader を起動、そうでなければ CLI 管理ツールを起動

コマンドライン引数:
  --chat            ヘッドレスでアバターと会話する CLI を起動
  --lang LANG       会話言語 (例: ja, en) — --chat と併用
  --no-greet        --chat 時: 開始あいさつを省略
  --no-mood         --chat 時: 好感度トラッキングを無効化
  --dashboard       Flask ダッシュボードを起動
  --manage [args…]  CLI 管理バッチツールを起動（サブコマンドを渡せる: mood show 等）
  --validate        設定バリデーションのみ実行して終了（エラー時は exit code 1）
  --help / -h       ヘルプを表示して終了
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


def _launch_chat(lang: str | None = None, no_greet: bool = False, no_mood: bool = False) -> None:
    """ヘッドレスのペルソナ対話 CLI を起動する（GUI 不要）。

    persona_cli.main() を経由することで、auto_decay・mood 保存・言語選択など
    フル機能が有効になる。
    """
    from persona_cli import main as _chat_main
    argv = []
    if lang:
        argv += ["--lang", lang]
    if no_greet:
        argv.append("--no-greet")
    if no_mood:
        argv.append("--no-mood")
    raise SystemExit(_chat_main(argv))


def _launch_manage(manage_args: list[str] | None = None) -> None:
    """manage_satin CLI を起動する。引数が無い場合はヘルプを表示する。"""
    from manage_satin import main as _manage_main
    raise SystemExit(_manage_main(manage_args or []))


def _launch_validate() -> None:
    from manage_satin import validate_configs
    errors = validate_configs(os.path.join(_ROOT, "config"))
    print("[INFO] バリデーション完了")
    if errors:
        raise SystemExit(1)


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
    parser.add_argument("--lang",      default=None, help="会話言語 (例: ja, en) — --chat と併用")
    parser.add_argument("--no-greet",  action="store_true", help="--chat 時: 開始あいさつを省略")
    parser.add_argument("--no-mood",   action="store_true", help="--chat 時: 好感度トラッキングを無効化")
    parser.add_argument("--no-dep-check", action="store_true", help="依存チェックをスキップ")
    parser.add_argument("manage_subargs", nargs=argparse.REMAINDER,
                        help="--manage 時に manage_satin に転送するサブコマンド引数")
    args = parser.parse_args()

    if not args.no_dep_check:
        _check_deps(verbose=True)

    _check_config()

    if args.validate:
        _launch_validate()
    elif args.chat:
        _launch_chat(lang=args.lang, no_greet=args.no_greet, no_mood=args.no_mood)
    elif args.manage:
        _launch_manage(args.manage_subargs or None)
    elif args.dashboard:
        _launch_dashboard(host=args.host, port=args.port)
    else:
        # デフォルト: GUI アバターローダーを起動
        _launch_avatar_loader()


if __name__ == "__main__":
    main()
