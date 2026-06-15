"""
Satin 管理バッチツール (CLI)

サブコマンド:
  validate              設定ファイルのバリデーション
  mood show             現在の好感度を表示
  mood reset            好感度をニュートラルにリセット
  mood export FILE      好感度状態を JSON にエクスポート
  mood import FILE      JSON から好感度をインポート
  log show [N]          会話ログの直近 N 件を表示（デフォルト: 20）
  log clear             会話ログをクリア
  log export FILE       会話ログを JSON ファイルにエクスポート
  log csv FILE          会話ログを CSV ファイルにエクスポート
  log search QUERY      会話ログをキーワード検索（アーカイブ含む）
  backup list           バックアップ一覧を表示
  backup restore FILE   sync バックアップ zip を復元
  persona show          ペルソナ情報を表示
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

# main/ ディレクトリを sys.path に追加（リポジトリルートから実行を想定）
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MAIN = os.path.dirname(os.path.abspath(__file__))
for _p in (_MAIN, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# --------------------------------------------------------------------------- #
# validate
# --------------------------------------------------------------------------- #
def validate_configs(config_dir: str = ".") -> list[str]:
    """全 JSON 設定ファイルを読み込んで構文チェックし、エラーの一覧を返す。"""
    files = sorted(glob.glob(os.path.join(config_dir, "*.json")))
    errors: list[str] = []
    if not files:
        print(f"[WARN] {config_dir} に JSON ファイルが見つかりませんでした。")
        return errors
    for fname in files:
        try:
            with open(fname, encoding="utf-8") as f:
                json.load(f)
            print(f"[OK]   {os.path.basename(fname)}")
        except json.JSONDecodeError as e:
            msg = f"[ERROR] {fname}: JSON 構文エラー — {e}"
            print(msg)
            errors.append(msg)
        except Exception as e:
            msg = f"[ERROR] {fname}: 読み込み失敗 — {e}"
            print(msg)
            errors.append(msg)
    if errors:
        print(f"\n設定バリデーション完了: {len(errors)} 件のエラー")
    else:
        print("\n全設定ファイルが正常です")
    return errors


# --------------------------------------------------------------------------- #
# mood
# --------------------------------------------------------------------------- #
def cmd_mood_show() -> None:
    try:
        from mood import (
            get_mood_tracker, _default_mood_path, _default_mood_history_path,
            affinity_label, load_level_transitions,
        )
        tracker = get_mood_tracker()
        score = int(round(tracker.affinity))
        level = tracker.level
        label_ja = affinity_label(tracker.affinity, "ja")
        label_en = affinity_label(tracker.affinity, "en")
        print(f"好感度スコア  : {score}/100")
        print(f"関係レベル    : {level} ({label_ja} / {label_en})")
        print(f"対話回数      : {tracker.interactions}")
        if tracker._last_interaction_time > 0:
            import datetime
            dt = datetime.datetime.fromtimestamp(tracker._last_interaction_time)
            print(f"最後の対話    : {dt.strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            print("最後の対話    : なし")
        # レベル変化マイルストーンを表示
        transitions = load_level_transitions(_default_mood_history_path())
        if transitions:
            print("関係の節目    :")
            for t in transitions[-5:]:  # 最近 5 件
                arrow = "↑" if t.get("prev_level", "") < t.get("level", "") else "↓"
                print(f"  {t.get('date', '?')} {arrow} {t.get('prev_level', '?')} → {t.get('level', '?')}")
        print(f"保存先        : {_default_mood_path()}")
    except ImportError:
        print("[ERROR] mood モジュールが見つかりません。")
        sys.exit(1)


def cmd_mood_reset() -> None:
    try:
        from mood import get_mood_tracker, reset_mood_tracker, AFFINITY_START, _default_mood_path
        tracker = get_mood_tracker()
        tracker.affinity = AFFINITY_START
        tracker.interactions = 0
        tracker._last_interaction_time = 0.0
        path = _default_mood_path()
        tracker.save(path)
        reset_mood_tracker()
        print(f"好感度をニュートラル（{int(AFFINITY_START)}/100）にリセットしました。")
        print(f"保存先: {path}")
    except ImportError:
        print("[ERROR] mood モジュールが見つかりません。")
        sys.exit(1)


def cmd_mood_export(dest: str) -> None:
    try:
        from mood import get_mood_tracker
        tracker = get_mood_tracker()
        data = tracker.to_dict()
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"好感度を '{dest}' にエクスポートしました。")
    except ImportError:
        print("[ERROR] mood モジュールが見つかりません。")
        sys.exit(1)


# --------------------------------------------------------------------------- #
# log
# --------------------------------------------------------------------------- #
def cmd_log_show(n: int = 20) -> None:
    try:
        from conversation_log import get_conversation_log
        log = get_conversation_log()
        # ペルソナ名を取得してアバター側ラベルをカスタマイズする
        avatar_label = "Avatar"
        try:
            from persona import get_persona
            p = get_persona()
            if p and p.name:
                avatar_label = p.name
        except Exception:
            pass
        lines = log.recent_texts(n, avatar_label=avatar_label)
        if not lines:
            print("(会話ログが空です)")
            return
        for line in lines:
            print(line)
    except ImportError:
        print("[ERROR] conversation_log モジュールが見つかりません。")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] ログの読み込みに失敗しました: {e}")
        sys.exit(1)


def cmd_log_clear(log_path: str | None = None) -> None:
    try:
        from conversation_log import get_conversation_log, _find_archives
        log = get_conversation_log()
        path = log_path or log.logfile
        archives = _find_archives(path)
        total = (1 if os.path.exists(path) else 0) + len(archives)
        if total == 0:
            print("(ログファイルが存在しません)")
            return
        archive_note = f"（アーカイブ {len(archives)} 件を含む）" if archives else ""
        ans = input(
            f"'{path}' の会話ログ{archive_note}をクリアします。よろしいですか？ [y/N]: "
        ).strip().lower()
        if ans != "y":
            print("キャンセルしました。")
            return
        if os.path.exists(path):
            open(path, "w", encoding="utf-8").close()
        for gz in archives:
            try:
                os.remove(gz)
            except OSError as e:
                print(f"[WARNING] アーカイブの削除に失敗しました: {gz}: {e}")
        print(f"会話ログをクリアしました: {path}{archive_note}")
    except ImportError:
        print("[ERROR] conversation_log モジュールが見つかりません。")
        sys.exit(1)


def cmd_log_export(dest: str) -> None:
    try:
        from conversation_log import get_conversation_log
        log = get_conversation_log()
        # include_archives=True でローテート済みアーカイブも含む完全エクスポート
        events = log.search("", include_archives=True)
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(events, f, ensure_ascii=False, indent=2)
        print(f"会話ログ {len(events)} 件を '{dest}' にエクスポートしました。")
    except ImportError:
        print("[ERROR] conversation_log モジュールが見つかりません。")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] ログのエクスポートに失敗しました: {e}")
        sys.exit(1)


def cmd_log_search(query: str, limit: int = 0) -> None:
    """会話ログから query をキーワード検索して結果を表示する（アーカイブ含む）。"""
    try:
        from conversation_log import get_conversation_log, USER_EVENT_TYPES
        log = get_conversation_log()
        from datetime import datetime as _dt
        # ペルソナ名を取得してアバター側ラベルをカスタマイズする
        avatar_label = "Avatar"
        try:
            from persona import get_persona
            p = get_persona()
            if p and p.name:
                avatar_label = p.name
        except Exception:
            pass
        results = log.search(query, n=limit, include_archives=True)
        if not results:
            print(f"(「{query}」に一致する会話は見つかりませんでした)")
            return
        print(f"「{query}」の検索結果: {len(results)} 件")
        for ev in results:
            ts = ev.get("timestamp", 0)
            try:
                dt_str = _dt.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
            except (OSError, OverflowError, ValueError):
                dt_str = "?"
            event_type = ev.get("event_type", "")
            text = (ev.get("details") or {}).get("text", "")
            prefix = "You" if event_type in USER_EVENT_TYPES else avatar_label
            print(f"[{dt_str}] {prefix}: {text}")
    except ImportError:
        print("[ERROR] conversation_log モジュールが見つかりません。")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] 検索に失敗しました: {e}")
        sys.exit(1)


# --------------------------------------------------------------------------- #
# backup
# --------------------------------------------------------------------------- #
def cmd_backup_list(backup_dir: str = "event_report") -> None:
    if not os.path.isdir(backup_dir):
        print(f"(バックアップディレクトリが見つかりません: {backup_dir})")
        return
    files = sorted(
        f for f in os.listdir(backup_dir)
        if f.endswith(".gz") or f.endswith(".png") or f.endswith(".json") or f.endswith(".zip")
    )
    if not files:
        print("(バックアップファイルが見つかりません)")
        return
    print(f"バックアップ一覧 ({backup_dir}):")
    for fname in files:
        full = os.path.join(backup_dir, fname)
        size = os.path.getsize(full)
        print(f"  {fname:40s}  {size:>8d} bytes")


def cmd_backup_restore(zip_path: str, dest_dir: str | None = None) -> None:
    """同期バックアップ zip を復元する。

    _build_sync_backup() が作成した zip（config/ と .jsonl / .gz ファイルを含む）を
    dest_dir に展開する。dest_dir が省略された場合はリポジトリルート（_ROOT）に復元。

    安全のため復元前に確認プロンプトを表示し、既存ファイルを上書きする前に
    バックアップコピーを作成する。
    """
    import zipfile
    root = dest_dir or _ROOT
    if not os.path.exists(zip_path):
        print(f"[ERROR] バックアップファイルが見つかりません: {zip_path}")
        sys.exit(1)

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
    except Exception as e:
        print(f"[ERROR] zip ファイルを開けませんでした: {e}")
        sys.exit(1)

    # バリデーション: config/ エントリが 1 件以上あること
    config_entries = [n for n in names if n.startswith("config/")]
    log_entries = [n for n in names if n.endswith(".jsonl") or n.endswith(".gz")]
    if not config_entries and not log_entries:
        print("[ERROR] このファイルは Satin バックアップではない可能性があります。")
        sys.exit(1)

    print(f"バックアップ: {zip_path}")
    print(f"復元先       : {root}")
    print(f"設定ファイル : {len(config_entries)} 件")
    print(f"ログファイル : {len(log_entries)} 件")
    print()
    ans = input("復元します。既存ファイルを上書きします。よろしいですか？ [y/N]: ").strip().lower()
    if ans != "y":
        print("キャンセルしました。")
        return

    restored = []
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for entry in names:
                # ディレクトリトラバーサル防止
                dest_path = os.path.realpath(os.path.join(root, entry))
                if not dest_path.startswith(os.path.realpath(root) + os.sep):
                    print(f"  [SKIP] 不正なパス: {entry}")
                    continue
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                with zf.open(entry) as src, open(dest_path, "wb") as dst:
                    import shutil as _shutil
                    _shutil.copyfileobj(src, dst)
                # 個人データファイルはアクセス権を制限する
                if entry.endswith((".jsonl", ".gz", ".json")):
                    try:
                        from fsutil import restrict_to_owner
                        restrict_to_owner(dest_path)
                    except Exception:
                        pass
                restored.append(entry)
                print(f"  復元: {entry}")
    except Exception as e:
        print(f"[ERROR] 復元中にエラーが発生しました: {e}")
        sys.exit(1)

    print(f"\n{len(restored)} 件のファイルを復元しました。")


# --------------------------------------------------------------------------- #
# CLI entry
# --------------------------------------------------------------------------- #
def cmd_mood_import(src: str) -> None:
    """JSON ファイルから好感度をインポートして現在のトラッカーに適用する。"""
    try:
        from mood import get_mood_tracker, _default_mood_path, AFFINITY_START
        with open(src, encoding="utf-8") as f:
            data = json.load(f)
        tracker = get_mood_tracker()
        tracker.affinity = float(data.get("affinity", AFFINITY_START))
        tracker.interactions = int(data.get("interactions", 0))
        tracker._last_interaction_time = float(data.get("last_interaction_time", 0.0))
        if _default_mood_path is not None:
            tracker.save(_default_mood_path())
        print(f"好感度を '{src}' からインポートしました: affinity={tracker.affinity:.1f}")
    except ImportError:
        print("[ERROR] mood モジュールが見つかりません。")
        sys.exit(1)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"[ERROR] ファイルの読み込みに失敗しました: {exc}")
        sys.exit(1)


def cmd_log_csv(dest: str) -> None:
    """会話ログを CSV ファイルにエクスポートする。"""
    try:
        from conversation_log import ConversationLog, DEFAULT_LOGFILE
        log_path = os.path.join(_ROOT, DEFAULT_LOGFILE)
        log = ConversationLog(log_path)
        csv_content = log.to_csv()
        with open(dest, "w", encoding="utf-8-sig", newline="") as f:
            f.write(csv_content)
        print(f"会話ログを CSV に書き出しました: {dest}")
    except ImportError:
        print("[ERROR] conversation_log モジュールが見つかりません。")
        sys.exit(1)
    except Exception as exc:
        print(f"[ERROR] CSV エクスポートに失敗しました: {exc}")
        sys.exit(1)


def cmd_persona_show() -> None:
    """現在のペルソナ情報を表示する。"""
    try:
        from persona import get_persona
        p = get_persona()
    except ImportError:
        print("[ERROR] persona モジュールが見つかりません。")
        sys.exit(1)
    print(f"名前   : {p.name or '(未設定)'}")
    print(f"言語   : {p.lang}")
    # Show a sample greeting
    try:
        greeting = p.greeting()
        print(f"挨拶例 : {greeting}")
    except Exception:
        pass
    # Show response rule counts
    try:
        block = p._resolve_responses_block()
        rules = block.get("rules", [])
        fallback = block.get("fallback", [])
        affinity = block.get("respond_by_affinity", {})
        print(f"応答ルール数 : {len(rules)} (+fallback {len(fallback)})")
        if affinity:
            levels = ", ".join(f"{k}:{len(v)}" for k, v in affinity.items())
            print(f"好感度別ルール : {levels}")
    except Exception:
        pass


def cmd_summary(lang: str = "ja", yesterday: bool = False) -> None:
    """今日（または昨日）のアクティビティサマリーを表示する。"""
    try:
        from daily_summary import daily_summary, summary_greeting
    except ImportError:
        print("[ERROR] daily_summary モジュールが見つかりません。")
        sys.exit(1)

    # CLI/会話ログと同じパスを使う
    event_log_path = None
    try:
        from conversation_log import get_conversation_log
        event_log_path = get_conversation_log().logfile
    except Exception:
        pass
    mood_history_path = None
    try:
        from mood import _default_mood_history_path
        mood_history_path = _default_mood_history_path()
    except Exception:
        pass

    target_date = None
    if yesterday:
        from datetime import date, timedelta
        target_date = date.today() - timedelta(days=1)

    kwargs = {
        "lang": lang,
        "event_log_path": event_log_path,
        "mood_history_path": mood_history_path,
    }
    s = daily_summary(target_date=target_date, **kwargs)
    greeting = summary_greeting(target_date=target_date, **kwargs)

    print(f"=== {s['date']} のサマリー ===")
    print(f"あなたのメッセージ : {s['user_messages']}")
    print(f"アバターの返答     : {s['avatar_replies']}")
    print(f"合計やりとり       : {s['total_interactions']}")
    if s["peak_hour"] is not None:
        print(f"ピーク時間帯       : {s['peak_hour']:02d}:00–{s['peak_hour']:02d}:59")
    if s["affinity"] is not None:
        print(f"好感度             : {s['affinity']:.1f} ({s['affinity_level']})")
    if s.get("streak", 0) >= 2:
        print(f"連続記録           : {s['streak']}日")
    if greeting:
        print(f"\nアバター: {greeting}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="manage_satin",
        description="Satin 管理バッチツール",
    )
    sub = parser.add_subparsers(dest="command", metavar="<コマンド>")

    # validate
    p_val = sub.add_parser("validate", help="設定ファイルのバリデーション")
    p_val.add_argument("--config-dir", default=None, help="config ディレクトリのパス（省略時: リポジトリルートの config/）")

    # mood
    p_mood = sub.add_parser("mood", help="好感度の管理")
    mood_sub = p_mood.add_subparsers(dest="mood_cmd", metavar="<mood-コマンド>")
    mood_sub.add_parser("show", help="現在の好感度を表示")
    mood_sub.add_parser("reset", help="好感度をニュートラルにリセット")
    p_mood_export = mood_sub.add_parser("export", help="好感度を JSON にエクスポート")
    p_mood_export.add_argument("file", help="エクスポート先のファイルパス")
    p_mood_import = mood_sub.add_parser("import", help="JSON から好感度をインポート")
    p_mood_import.add_argument("file", help="インポート元のファイルパス")

    # log
    p_log = sub.add_parser("log", help="会話ログの管理")
    log_sub = p_log.add_subparsers(dest="log_cmd", metavar="<log-コマンド>")
    p_log_show = log_sub.add_parser("show", help="会話ログの直近 N 件を表示")
    p_log_show.add_argument("-n", type=int, default=20, help="表示件数（デフォルト: 20）")
    log_sub.add_parser("clear", help="会話ログをクリア")
    p_log_export = log_sub.add_parser("export", help="会話ログを JSON にエクスポート")
    p_log_export.add_argument("file", help="エクスポート先のファイルパス")
    p_log_csv = log_sub.add_parser("csv", help="会話ログを CSV にエクスポート")
    p_log_csv.add_argument("file", help="出力先の CSV ファイルパス")
    p_log_search = log_sub.add_parser("search", help="会話ログをキーワード検索")
    p_log_search.add_argument("query", help="検索クエリ")
    p_log_search.add_argument("-n", "--limit", type=int, default=0,
                              help="最大表示件数（0 = 全件、デフォルト: 0）")

    # backup
    p_bk = sub.add_parser("backup", help="バックアップの管理")
    bk_sub = p_bk.add_subparsers(dest="backup_cmd", metavar="<backup-コマンド>")
    p_bk_list = bk_sub.add_parser("list", help="バックアップ一覧を表示")
    p_bk_list.add_argument("--dir", default="event_report", help="バックアップディレクトリ（デフォルト: event_report）")
    p_bk_restore = bk_sub.add_parser("restore", help="sync バックアップ zip を復元")
    p_bk_restore.add_argument("file", help="復元元の zip ファイルパス")
    p_bk_restore.add_argument("--dest", default=None, help="復元先ディレクトリ（省略時: リポジトリルート）")

    # persona
    p_persona = sub.add_parser("persona", help="ペルソナ情報の表示")
    persona_sub = p_persona.add_subparsers(dest="persona_cmd", metavar="<persona-コマンド>")
    persona_sub.add_parser("show", help="現在のペルソナ情報を表示")

    # summary
    p_summary = sub.add_parser("summary", help="アクティビティサマリーの表示")
    p_summary.add_argument("--lang", default="ja", help="表示言語（ja/en、デフォルト: ja）")
    p_summary.add_argument("--yesterday", action="store_true", help="昨日のサマリーを表示")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    config_dir_default = os.path.join(_ROOT, "config")

    if args.command == "validate":
        config_dir = args.config_dir or config_dir_default
        errors = validate_configs(config_dir)
        return 1 if errors else 0

    elif args.command == "mood":
        if not args.mood_cmd:
            print("使用方法: manage_satin mood {show,reset,export}")
            return 1
        if args.mood_cmd == "show":
            cmd_mood_show()
        elif args.mood_cmd == "reset":
            cmd_mood_reset()
        elif args.mood_cmd == "export":
            cmd_mood_export(args.file)
        elif args.mood_cmd == "import":
            cmd_mood_import(args.file)
        return 0

    elif args.command == "log":
        if not args.log_cmd:
            print("使用方法: manage_satin log {show,clear,export,csv,search}")
            return 1
        if args.log_cmd == "show":
            cmd_log_show(args.n)
        elif args.log_cmd == "clear":
            cmd_log_clear()
        elif args.log_cmd == "export":
            cmd_log_export(args.file)
        elif args.log_cmd == "csv":
            cmd_log_csv(args.file)
        elif args.log_cmd == "search":
            cmd_log_search(args.query, args.limit)
        return 0

    elif args.command == "backup":
        if not args.backup_cmd:
            print("使用方法: manage_satin backup {list,restore}")
            return 1
        if args.backup_cmd == "list":
            cmd_backup_list(args.dir)
        elif args.backup_cmd == "restore":
            cmd_backup_restore(args.file, args.dest)
        return 0

    elif args.command == "persona":
        if not args.persona_cmd:
            print("使用方法: manage_satin persona {show}")
            return 1
        if args.persona_cmd == "show":
            cmd_persona_show()
        return 0

    elif args.command == "summary":
        cmd_summary(lang=args.lang, yesterday=args.yesterday)
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
