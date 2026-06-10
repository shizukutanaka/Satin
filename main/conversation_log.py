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

import json
import logging
import os
import threading
from typing import Dict, List, Optional

from avatar_event_logger import AvatarEventLogger

logger = logging.getLogger(__name__)

# 既存ツール (dashboard / timeline viewer / alert) の既定と同じファイルを共有する
DEFAULT_LOGFILE = "avatar_event_log.jsonl"

EVENT_USER_COMMENT = "user_comment"
EVENT_AVATAR_REPLY = "avatar_reply"


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
        """
        if n <= 0 or not os.path.exists(self.logfile):
            return []
        entries: List[Dict] = []
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
                        entries.append(ev)
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("会話ログの読み出しに失敗しました: %s", e)
            return []
        return entries[-n:]

    def recent_texts(self, n: int = 20) -> List[str]:
        """直近 n 件を「You: ...」「Avatar: ...」形式の文字列リストで返す（表示用）。"""
        lines = []
        for ev in self.recent(n):
            text = (ev.get("details") or {}).get("text", "")
            prefix = "You" if ev.get("event_type") == EVENT_USER_COMMENT else "Avatar"
            lines.append(f"{prefix}: {text}")
        return lines


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
