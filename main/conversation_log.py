"""
会話履歴ログ。

ユーザーのコメントとアバターの応答を既存の AvatarEventLogger (JSONL) に記録し、
タイムラインビューア / ダッシュボード / レポートなど既存のイベントログ
ツールチェーンから会話を閲覧できるようにする。これまでイベントログ基盤は
存在したが、プロダクト本体からは一切書き込まれていなかった（＝会話が残らない）。

イベント種別:
  - user_comment: ユーザーが入力したコメント  details={"text": ...}
  - avatar_reply: アバターの応答              details={"text": ..., "to": <元コメント>}

記録の失敗（ディスクフル等）は呼び出し元の UI/TTS を壊さないよう必ず握り潰す。
依存は標準ライブラリのみ。
"""
from __future__ import annotations

import gzip
import json
import logging
import os
import threading
from typing import Dict, Generator, List, Optional

from avatar_event_logger import AvatarEventLogger

logger = logging.getLogger(__name__)

# 既存ツール (dashboard / timeline viewer / alert) の既定と同じファイルを共有する
DEFAULT_LOGFILE = "avatar_event_log.jsonl"

EVENT_USER_COMMENT = "user_comment"
EVENT_AVATAR_REPLY = "avatar_reply"

# 集計・表示時に「ユーザー発話」「アバター発話」とみなすイベント種別の正準集合。
# 正規値に加え、過去ログ/外部ログ互換のためのレガシー別名 ("user"/"avatar") を含む。
# dashboard と daily_summary が同じ分類を共有し、同一ログで集計が食い違わないようにする
# 単一の真実の源（single source of truth）。
USER_EVENT_TYPES = frozenset({EVENT_USER_COMMENT, "user"})
AVATAR_EVENT_TYPES = frozenset({EVENT_AVATAR_REPLY, "avatar"})


def _archive_sort_key(path: str) -> tuple:
    """アーカイブのソートキーを返す。

    命名規則 ``<logfile>.<YYYYMMDD_HHMMSS>.gz`` のタイムスタンプ部分を使う。
    バックアップ復元後に mtime がリセットされても正しい時系列順を保つ。
    フォールバックとして mtime を使う（命名規則が異なる旧ファイル向け）。
    """
    import re
    m = re.search(r"\.(\d{8}_\d{6})\.gz$", path)
    if m:
        return (0, m.group(1))  # (優先度, タイムスタンプ文字列)
    return (1, str(os.path.getmtime(path)))  # フォールバック: mtime


def _find_archives(logfile: str) -> List[str]:
    """ローテートされた gzip アーカイブを古い順で返す。

    avatar_event_log_rotate.rotate_log() は ``<logfile>.<YYYYMMDD_HHMMSS>.gz``
    という命名規則でアーカイブを作成する。ファイル名に埋め込まれたタイムスタンプで
    ソートするため、バックアップ復元後に mtime がリセットされても順序が壊れない。
    ログファイルが存在しない・ディレクトリが読めない場合は空リスト。
    """
    try:
        log_dir = os.path.dirname(os.path.abspath(logfile))
        basename = os.path.basename(logfile) + "."
        files = [
            os.path.join(log_dir, f)
            for f in os.listdir(log_dir)
            if f.startswith(basename) and f.endswith(".gz")
        ]
        return sorted(files, key=_archive_sort_key)
    except OSError:
        return []


def _iter_gz_lines(gz_path: str) -> Generator[str, None, None]:
    """gzip アーカイブの各行を文字列として yield する。読み込みエラーは握りつぶす。"""
    try:
        with gzip.open(gz_path, "rt", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                yield line
    except Exception as e:  # pragma: no cover - OS/format error
        logger.debug("アーカイブの読み込みをスキップします (%s): %s", gz_path, e)


class ConversationLog:
    """ユーザーとアバターの会話を JSONL イベントログへ記録・読み出しするクラス。"""

    def __init__(self, logfile: str = DEFAULT_LOGFILE):
        self.logfile = logfile
        self._logger = AvatarEventLogger(logfile)

    # ---- 記録 ------------------------------------------------------------ #
    def log_user_comment(self, text: str) -> None:
        """ユーザーのコメントを記録する。失敗しても例外は送出しない。"""
        if not text:
            return
        try:
            self._logger.log_event(EVENT_USER_COMMENT, text=str(text))
        except Exception as e:  # pragma: no cover - defensive: UI を壊さない
            logger.warning("会話ログの記録に失敗しました: %s", e)

    def log_avatar_reply(self, text: str, to: Optional[str] = None) -> None:
        """アバターの応答を記録する。to には応答対象の元コメントを渡せる。"""
        if not text:
            return
        details = {"text": str(text)}
        if to:
            details["to"] = str(to)
        try:
            self._logger.log_event(EVENT_AVATAR_REPLY, **details)
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("会話ログの記録に失敗しました: %s", e)

    def log_exchange(self, comment: str, reply: str) -> None:
        """「コメント → 応答」の 1 往復をまとめて記録する。"""
        self.log_user_comment(comment)
        # オウム返し (reply == comment) は応答として二重記録しない
        if reply and reply != comment:
            self.log_avatar_reply(reply, to=comment)

    # ---- 読み出し ---------------------------------------------------------- #
    def recent(self, n: int = 20) -> List[Dict]:
        """直近 n 件の会話イベント (user_comment / avatar_reply) を古い順で返す。

        ログファイルが無い・壊れた行がある場合も安全に処理する。
        ライブファイルの件数が n に満たない場合（ローテーション直後など）は
        アーカイブも遡って補完する。
        """
        if n <= 0:
            return []
        # まずライブファイルから収集する
        live_entries: List[Dict] = []
        if os.path.exists(self.logfile):
            try:
                with open(self.logfile, encoding="utf-8") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        try:
                            ev = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if ev.get("event_type") in (EVENT_USER_COMMENT, EVENT_AVATAR_REPLY):
                            live_entries.append(ev)
            except Exception as e:  # pragma: no cover - defensive
                logger.warning("会話ログの読み出しに失敗しました: %s", e)
        # ライブファイルで n 件揃う場合はアーカイブ走査は不要
        if len(live_entries) >= n:
            return live_entries[-n:]
        # 不足分をアーカイブ（新しい順）から補完する
        need = n - len(live_entries)
        archive_entries: List[Dict] = []
        for gz_path in reversed(_find_archives(self.logfile)):
            for line in _iter_gz_lines(gz_path):
                if not line.strip():
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if ev.get("event_type") in (EVENT_USER_COMMENT, EVENT_AVATAR_REPLY):
                    archive_entries.append(ev)
            if len(archive_entries) >= need:
                break
        # アーカイブは新→旧の順に読んでいるので反転して古→新に並べ直す
        archive_tail = list(reversed(archive_entries[-need:]))
        return archive_tail + live_entries

    def recent_texts(
        self,
        n: int = 20,
        user_label: str = "You",
        avatar_label: str = "Avatar",
    ) -> List[str]:
        """直近 n 件を「[YYYY-MM-DD HH:MM:SS] You: ...」形式の文字列リストで返す（表示用）。

        user_label / avatar_label でラベルをカスタマイズできる（例: ペルソナ名）。
        """
        from datetime import datetime as _dt
        lines = []
        for ev in self.recent(n):
            text = (ev.get("details") or {}).get("text", "")
            prefix = user_label if ev.get("event_type") in USER_EVENT_TYPES else avatar_label
            ts = ev.get("timestamp", 0)
            try:
                dt_str = _dt.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
                lines.append(f"[{dt_str}] {prefix}: {text}")
            except (OSError, OverflowError, ValueError):
                lines.append(f"{prefix}: {text}")
        return lines

    def search(self, query: str, n: int = 0, include_archives: bool = True) -> List[Dict]:
        """会話履歴からキーワード検索し、一致したイベントを古い順で返す。

        Args:
            query: 検索クエリ（大文字小文字を無視した部分一致）。空なら全件。
            n: 返す最大件数（0 = 全件）。
            include_archives: True（既定）のとき、ローテートされた gzip アーカイブも
                検索する。ログローテーション後も会話履歴が消えないようにするための
                「コンパニオンが記憶を失わない」保証。

        Returns:
            会話イベント（user/avatar、レガシー別名含む）のうち text フィールドに
            query を含むイベントのリスト。イベント分類は USER_EVENT_TYPES /
            AVATAR_EVENT_TYPES（dashboard と共有の正準集合）に従う。
        """
        q_lower = query.strip().lower() if query else ""
        conv_types = USER_EVENT_TYPES | AVATAR_EVENT_TYPES
        entries: List[Dict] = []

        def _collect_line(line: str) -> None:
            if not line.strip():
                return
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                return
            if ev.get("event_type") not in conv_types:
                return
            text = ((ev.get("details") or {}).get("text") or "")
            if not q_lower or q_lower in str(text).lower():
                entries.append(ev)

        # アーカイブを古い順に検索（ローテーション後も履歴が途切れない）
        if include_archives:
            for gz_path in _find_archives(self.logfile):
                for line in _iter_gz_lines(gz_path):
                    _collect_line(line)

        # 現行ログファイル
        if os.path.exists(self.logfile):
            try:
                with open(self.logfile, encoding="utf-8") as f:
                    for line in f:
                        _collect_line(line)
            except Exception as e:  # pragma: no cover - defensive
                logger.warning("会話ログの検索に失敗しました: %s", e)

        return entries[-n:] if n > 0 else entries

    def to_csv(self, n: int = 0, user_label: str = "You", avatar_label: str = "Avatar",
               include_archives: bool = True) -> str:
        """会話履歴を CSV 形式の文字列で返す。

        Args:
            n: 直近 n 件（0 = 全件）
            user_label:   CSV の speaker 列でユーザーを表すラベル
            avatar_label: CSV の speaker 列でアバターを表すラベル
            include_archives: True（既定）のとき、ローテート済みアーカイブも含む。

        Returns:
            header + rows の CSV 文字列（UTF-8、CRLF 改行）。
        """
        import csv
        import io
        from datetime import datetime as _dt

        entries = self.search("", n=n, include_archives=include_archives)
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\r\n")
        writer.writerow(["timestamp", "datetime", "speaker", "text"])
        for ev in entries:
            ts = ev.get("timestamp", 0)
            try:
                dt_str = _dt.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
            except (OSError, OverflowError, ValueError):
                dt_str = ""
            et = ev.get("event_type", "")
            speaker = user_label if et == EVENT_USER_COMMENT else avatar_label
            text = (ev.get("details") or {}).get("text", "")
            writer.writerow([ts, dt_str, speaker, text])
        return buf.getvalue()


# --------------------------------------------------------------------------- #
# プロセス内シングルトン（全ビューアで同じログファイルを共有）
# --------------------------------------------------------------------------- #
_conversation_log: Optional[ConversationLog] = None
_lock = threading.Lock()


def get_conversation_log(logfile: str = DEFAULT_LOGFILE) -> ConversationLog:
    """共有 ConversationLog を返す（初回呼び出し時に生成）。"""
    global _conversation_log
    if _conversation_log is None:
        with _lock:
            if _conversation_log is None:
                _conversation_log = ConversationLog(logfile)
    return _conversation_log


def reset_conversation_log() -> None:
    """シングルトンを破棄する（テスト・ログファイル切替用）。"""
    global _conversation_log
    with _lock:
        _conversation_log = None
