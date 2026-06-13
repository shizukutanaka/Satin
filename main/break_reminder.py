"""
ブレークリマインダー: ユーザーに定期的な休憩を促す機能。

設定ファイル: config/plugins/break_reminder.json
  {
    "work_minutes": 25,       // 作業時間（分）。デフォルト 25（ポモドーロ）
    "short_break_minutes": 5, // 短休憩時間（分）
    "long_break_minutes": 15, // 長休憩時間（分）。4サイクル毎
    "cycles_before_long": 4,  // 長休憩までのサイクル数
    "enabled": true
  }
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_WORK_MINUTES = 25
_DEFAULT_SHORT_BREAK = 5
_DEFAULT_LONG_BREAK = 15
_DEFAULT_CYCLES_BEFORE_LONG = 4

_REMINDER_MESSAGES = {
    "ja": {
        "work_done": "お疲れ様！ {break_minutes}分間の休憩を取りましょう。目を休め、ストレッチしてみてください。",
        "long_break": "よく頑張りました！{break_minutes}分間の長めの休憩です。水を飲んで、少し歩きましょう。",
        "break_done": "休憩終了！また作業を始めましょう。{work_minutes}分間の作業です。",
        "title_work": "作業時間終了",
        "title_break": "休憩時間終了",
    },
    "en": {
        "work_done": "Time's up! Take a {break_minutes}-minute break. Rest your eyes and stretch.",
        "long_break": "Great work! Time for a {break_minutes}-minute long break. Drink some water and take a walk.",
        "break_done": "Break over! Start your next {work_minutes}-minute work session.",
        "title_work": "Work Session Done",
        "title_break": "Break Over",
    },
}


class BreakReminderSession:
    """単一のポモドーロ・セッション状態を保持するデータクラス。"""

    def __init__(
        self,
        work_minutes: int = _DEFAULT_WORK_MINUTES,
        short_break_minutes: int = _DEFAULT_SHORT_BREAK,
        long_break_minutes: int = _DEFAULT_LONG_BREAK,
        cycles_before_long: int = _DEFAULT_CYCLES_BEFORE_LONG,
    ):
        self.work_minutes = work_minutes
        self.short_break_minutes = short_break_minutes
        self.long_break_minutes = long_break_minutes
        self.cycles_before_long = cycles_before_long

        self.completed_cycles: int = 0
        self.is_on_break: bool = False
        self.started_at: Optional[float] = None

    @property
    def current_break_minutes(self) -> int:
        """次の休憩が長休憩かどうかを判定して分数を返す。"""
        if (self.completed_cycles + 1) % self.cycles_before_long == 0:
            return self.long_break_minutes
        return self.short_break_minutes

    @property
    def is_long_break_due(self) -> bool:
        return (self.completed_cycles + 1) % self.cycles_before_long == 0

    def to_dict(self) -> dict:
        return {
            "completed_cycles": self.completed_cycles,
            "is_on_break": self.is_on_break,
            "work_minutes": self.work_minutes,
            "short_break_minutes": self.short_break_minutes,
            "long_break_minutes": self.long_break_minutes,
            "cycles_before_long": self.cycles_before_long,
        }


class BreakReminder:
    """
    ポモドーロ・テクニック準拠のブレークリマインダー。

    作業時間が終わったら通知を送り、休憩時間が終わったらまた通知する。
    NotificationSystem を使う（未インストールの場合は logging にフォールバック）。
    コールバック関数でアバターに発話させることもできる。
    """

    def __init__(
        self,
        work_minutes: int = _DEFAULT_WORK_MINUTES,
        short_break_minutes: int = _DEFAULT_SHORT_BREAK,
        long_break_minutes: int = _DEFAULT_LONG_BREAK,
        cycles_before_long: int = _DEFAULT_CYCLES_BEFORE_LONG,
        lang: str = "ja",
        notify_func: Optional[Callable[[str, str], None]] = None,
        speak_func: Optional[Callable[[str], None]] = None,
    ):
        self.session = BreakReminderSession(
            work_minutes=work_minutes,
            short_break_minutes=short_break_minutes,
            long_break_minutes=long_break_minutes,
            cycles_before_long=cycles_before_long,
        )
        self.lang = lang if lang in _REMINDER_MESSAGES else "en"
        self._notify_func = notify_func
        self._speak_func = speak_func

        self._timer: Optional[threading.Timer] = None
        self._stop_event = threading.Event()
        self._running = False
        self._lock = threading.Lock()

        # Try to import NotificationSystem; fall back to logging
        try:
            from notification_system import NotificationSystem
            self._ns: Optional[object] = NotificationSystem(app_name="Satin")
        except Exception:
            self._ns = None

        self._history: List[dict] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls, config: Optional[dict] = None, **kwargs) -> "BreakReminder":
        """設定辞書（config/plugins/break_reminder.json の内容）から生成。"""
        if not config:
            config = {}
        return cls(
            work_minutes=int(config.get("work_minutes", _DEFAULT_WORK_MINUTES)),
            short_break_minutes=int(config.get("short_break_minutes", _DEFAULT_SHORT_BREAK)),
            long_break_minutes=int(config.get("long_break_minutes", _DEFAULT_LONG_BREAK)),
            cycles_before_long=int(config.get("cycles_before_long", _DEFAULT_CYCLES_BEFORE_LONG)),
            **kwargs,
        )

    def start(self) -> None:
        """作業タイマーを開始する。すでに実行中なら何もしない。"""
        with self._lock:
            if self._running:
                logger.debug("BreakReminder: already running, ignoring start()")
                return
            self._running = True
            self._stop_event.clear()
        self._schedule_work()
        logger.info(
            "BreakReminder started: work=%dm, short_break=%dm, long_break=%dm",
            self.session.work_minutes,
            self.session.short_break_minutes,
            self.session.long_break_minutes,
        )

    def stop(self) -> None:
        """タイマーを停止する。進行中のタイマーをキャンセルする。"""
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._stop_event.set()
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        logger.info("BreakReminder stopped.")

    def reset(self) -> None:
        """セッション状態をリセットして最初のサイクルからやり直す。"""
        self.stop()
        self.session.completed_cycles = 0
        self.session.is_on_break = False
        self.session.started_at = None
        self._history.clear()

    @property
    def running(self) -> bool:
        return self._running

    def get_status(self) -> dict:
        """現在の状態を辞書で返す。"""
        return {
            "running": self._running,
            **self.session.to_dict(),
            "history_count": len(self._history),
        }

    def get_history(self) -> List[dict]:
        """イベント履歴（コピー）を返す。"""
        return list(self._history)

    # ------------------------------------------------------------------
    # Internal timer logic
    # ------------------------------------------------------------------

    def _schedule_work(self) -> None:
        if self._stop_event.is_set():
            return
        self.session.is_on_break = False
        self.session.started_at = time.time()
        delay = self.session.work_minutes * 60
        self._timer = threading.Timer(delay, self._on_work_done)
        self._timer.daemon = True
        self._timer.start()

    def _schedule_break(self) -> None:
        if self._stop_event.is_set():
            return
        self.session.is_on_break = True
        self.session.started_at = time.time()
        break_mins = self.session.current_break_minutes
        delay = break_mins * 60
        self._timer = threading.Timer(delay, self._on_break_done)
        self._timer.daemon = True
        self._timer.start()

    def _on_work_done(self) -> None:
        if self._stop_event.is_set():
            return
        msgs = _REMINDER_MESSAGES[self.lang]
        break_mins = self.session.current_break_minutes
        is_long = self.session.is_long_break_due

        if is_long:
            body = msgs["long_break"].format(break_minutes=break_mins)
        else:
            body = msgs["work_done"].format(break_minutes=break_mins)

        title = msgs["title_work"]
        self._notify(title, body)
        self._record("work_done", {"break_minutes": break_mins, "long": is_long})
        self._schedule_break()

    def _on_break_done(self) -> None:
        if self._stop_event.is_set():
            return
        msgs = _REMINDER_MESSAGES[self.lang]
        body = msgs["break_done"].format(work_minutes=self.session.work_minutes)
        title = msgs["title_break"]
        self._notify(title, body)
        self.session.completed_cycles += 1
        self._record("break_done", {"cycle": self.session.completed_cycles})
        self._schedule_work()

    # ------------------------------------------------------------------
    # Notification helpers
    # ------------------------------------------------------------------

    def _notify(self, title: str, body: str) -> None:
        logger.info("[BreakReminder] %s: %s", title, body)
        if self._ns is not None:
            try:
                self._ns.send_notification(title, body)  # type: ignore[attr-defined]
            except Exception as e:
                logger.debug("notification failed: %s", e)
        if self._notify_func is not None:
            try:
                self._notify_func(title, body)
            except Exception as e:
                logger.debug("notify_func failed: %s", e)
        if self._speak_func is not None:
            try:
                self._speak_func(body)
            except Exception as e:
                logger.debug("speak_func failed: %s", e)

    def _record(self, event: str, extra: Optional[dict] = None) -> None:
        entry = {"event": event, "timestamp": time.time()}
        if extra:
            entry.update(extra)
        self._history.append(entry)


def _load_config_file() -> Optional[dict]:
    """config/plugins/break_reminder.json を読み込む。無い/壊れていれば None。"""
    import json
    import os

    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config", "plugins", "break_reminder.json",
    )
    try:
        with open(config_path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def load_break_reminder(lang: str = "ja", **kwargs) -> BreakReminder:
    """設定ファイル（config/plugins/break_reminder.json）からロードして返す。

    ファイルが存在しない・破損している場合はデフォルト設定で生成する。
    """
    return BreakReminder.from_config(_load_config_file(), lang=lang, **kwargs)


def maybe_start_break_reminder(
    speak_func: Optional[Callable[[str], None]] = None,
    notify_func: Optional[Callable[[str, str], None]] = None,
    lang: str = "ja",
    config: Optional[dict] = None,
) -> Optional[BreakReminder]:
    """設定が許せばブレークリマインダーを生成・開始して返す。無効なら None。

    config に "enabled": false があれば（または明示 config なしでファイルの
    enabled が false なら）開始しない。これにより設定ファイルの enabled フラグが
    実際に機能する。アプリ起動側（自律モード開始時など）から呼ぶ。

    speak_func: アバターに発話させるコールバック（例: tts_queue.put）。
    """
    if config is None:
        config = _load_config_file() or {}
    if not config.get("enabled", True):
        logger.info("BreakReminder is disabled by config; not starting.")
        return None
    reminder = BreakReminder.from_config(
        config, lang=lang, speak_func=speak_func, notify_func=notify_func
    )
    reminder.start()
    return reminder
