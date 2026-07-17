"""
Satin ランチャー

起動フロー:
1. 依存パッケージの存在チェック（不足があれば案内）
2. 設定ファイルの有無を確認
3. 既定では 3D アバター本体（TTS・好感度・会話ログ・スラッシュコマンドを持つ
   avatar_3d_autonomous_tts.MainWindow）を起動する

コマンドライン引数:
  --chat            ヘッドレスでアバターと会話する CLI を起動
  --lang LANG       会話言語 (例: ja, en) — --chat と併用
  --no-greet        --chat 時: 開始あいさつを省略
  --no-mood         --chat 時: 好感度トラッキングを無効化
  --dashboard       Flask ダッシュボードを起動
  --manage [args…]  CLI 管理バッチツールを起動（サブコマンドを渡せる: mood show 等）
  --validate        設定バリデーションのみ実行して終了（エラー時は exit code 1）
  --avatar-loader   外部アバターファイル(.vrm/.fbx/.glb/.gltf)選択ダイアログのみを起動
                    （3D 描画・TTS・会話機能は無い簡易ツール。従来の既定モード）
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
# 依存一覧の唯一の真実の源は main/dependency_manifest.py（純データ、重い import
# 無し）。マニフェストが見つからない異常時でも起動診断が壊れないよう、最小限の
# フォールバックを持つ。
try:
    from dependency_manifest import optional_check_list, required_check_list

    _OPTIONAL_DEPS: list[tuple[str, str]] = optional_check_list()
    _REQUIRED_DEPS: list[tuple[str, str]] = required_check_list()
except Exception:  # pragma: no cover - defensive fallback
    # tkinter は全モード共通の必須依存ではない（_launch_avatar_loader() が
    # 自前で try/except している）。dependency_manifest.py の
    # REQUIRED_PACKAGES と同じ理由でここも空にする。
    _OPTIONAL_DEPS = []
    _REQUIRED_DEPS = []


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


def _launch_avatar_gui() -> None:
    """3D アバター本体（TTS・好感度・会話ログ・スラッシュコマンド）を起動する。

    既定の起動モード。以前は avatar_loader.AvatarLoaderApp（外部アバター
    ファイルを選ぶだけで何も起動しない簡易ダイアログ）が既定になっており、
    launch/win/run_satin.bat・launch/mac/run_satin.sh・README が案内する
    「Satin を起動する」手順の実体が、この本体 GUI に一切辿り着けない状態
    だった（商用品質監査で発見）。ファイル選択ダイアログは --avatar-loader
    で引き続き利用できる。
    """
    try:
        from PyQt5.QtWidgets import QApplication
        from avatar_3d_autonomous_tts import MainWindow
        app = QApplication(sys.argv[:1])
        win = MainWindow()
        win.show()
        sys.exit(app.exec_())
    except ImportError as e:
        print(f"[ERROR] 3D アバター GUI 起動失敗: {e}", file=sys.stderr)
        sys.exit(1)


def _launch_dashboard(host: str = "127.0.0.1", port: int | None = None) -> None:
    try:
        from dashboard import app, DEFAULT_DASHBOARD_PORT, _resolve_port
        # port 明示時はそれを使い、未指定なら dashboard.py 直接実行と同じ解決
        # （SATIN_DASHBOARD_PORT → DEFAULT_DASHBOARD_PORT=5003）に揃える。
        resolved = port if port is not None else _resolve_port(DEFAULT_DASHBOARD_PORT)
        print(f"[INFO] ダッシュボードを http://{host}:{resolved} で起動します")
        app.run(host=host, port=resolved, debug=False)
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
    parser.add_argument("--avatar-loader", action="store_true",
                        help="外部アバターファイル選択ダイアログのみを起動（従来の既定モード）")
    parser.add_argument("--host",      default="127.0.0.1", help="ダッシュボードのホスト (default: 127.0.0.1)")
    parser.add_argument("--port",      type=int, default=None, help="ダッシュボードのポート (default: 5003 / 環境変数 SATIN_DASHBOARD_PORT)")
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
    elif args.avatar_loader:
        _launch_avatar_loader()
    else:
        # デフォルト: 3D アバター本体（TTS・好感度・会話ログ）を起動
        _launch_avatar_gui()


if __name__ == "__main__":
    main()
