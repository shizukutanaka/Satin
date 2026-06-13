"""
通知システム。

優先順位でバックエンドを試みる:
  1. plyer（クロスプラットフォーム: macOS / Windows / Linux）
  2. notify2（Linux libnotify ラッパー）
  3. logging にフォールバック（常に動作）

通知履歴を最大 _HISTORY_LIMIT 件メモリに保持する。
`get_history()` で取得可能。
"""
from __future__ import annotations

import logging
import time
from collections import deque
from typing import Deque, Dict, List, Optional

logger = logging.getLogger(__name__)

_HISTORY_LIMIT = 100

try:
    from plyer import notification as _plyer_notify
    _PLYER_AVAILABLE = True
except Exception:
    _plyer_notify = None
    _PLYER_AVAILABLE = False

try:
    import notify2 as _notify2
    _NOTIFY2_AVAILABLE = True
except Exception:
    _notify2 = None  # type: ignore
    _NOTIFY2_AVAILABLE = False


class NotificationSystem:
    """アプリケーション通知送信クラス。

    GUI バックエンドが利用できない環境でも logging へのフォールバックで
    常に動作する。
    """

    def __init__(self, app_name: str = "Satin"):
        self.app_name = app_name
        self._history: Deque[Dict] = deque(maxlen=_HISTORY_LIMIT)
        self._notify2_inited = False

    def send_notification(
        self,
        title: str,
        message: str,
        level: str = "info",
        duration: int = 5,
    ) -> bool:
        """通知を送信する。

        Args:
            title: 通知タイトル
            message: 通知本文
            level: "info" | "success" | "warning" | "error"
            duration: 表示時間（秒、GUI 通知が使える場合のみ有効）

        Returns:
            True if a desktop notification was shown, False if only logged.
        """
        entry: Dict = {
            "timestamp": time.time(),
            "title": title,
            "message": message,
            "level": level,
        }
        self._history.append(entry)

        shown = self._try_desktop(title, message, duration)
        self._log(title, message, level)
        return shown

    # ------------------------------------------------------------------
    # Desktop notification backends
    # ------------------------------------------------------------------

    def _try_desktop(self, title: str, message: str, duration: int) -> bool:
        if _PLYER_AVAILABLE:
            return self._try_plyer(title, message, duration)
        if _NOTIFY2_AVAILABLE:
            return self._try_notify2(title, message, duration)
        return False

    def _try_plyer(self, title: str, message: str, duration: int) -> bool:
        try:
            _plyer_notify.notify(
                title=title,
                message=message,
                app_name=self.app_name,
                timeout=duration,
            )
            return True
        except Exception as exc:
            logger.debug("plyer notification failed: %s", exc)
            return False

    def _try_notify2(self, title: str, message: str, duration: int) -> bool:
        try:
            if not self._notify2_inited:
                _notify2.init(self.app_name)
                self._notify2_inited = True
            n = _notify2.Notification(title, message)
            n.set_timeout(duration * 1000)
            n.show()
            return True
        except Exception as exc:
            logger.debug("notify2 notification failed: %s", exc)
            return False

    def _log(self, title: str, message: str, level: str) -> None:
        log_level = {
            "info": logging.INFO,
            "success": logging.INFO,
            "warning": logging.WARNING,
            "error": logging.ERROR,
        }.get(level, logging.INFO)
        logger.log(log_level, "[%s] %s: %s", self.app_name, title, message)

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def get_history(self, n: int = _HISTORY_LIMIT) -> List[Dict]:
        """最近 n 件の通知履歴を返す（新しい順）。"""
        items = list(self._history)
        return items[-n:][::-1]

    def clear_history(self) -> None:
        self._history.clear()

    @property
    def history_count(self) -> int:
        return len(self._history)

    # ------------------------------------------------------------------
    # Backend availability query
    # ------------------------------------------------------------------

    @staticmethod
    def available_backends() -> List[str]:
        backends = ["logging"]
        if _NOTIFY2_AVAILABLE:
            backends.insert(0, "notify2")
        if _PLYER_AVAILABLE:
            backends.insert(0, "plyer")
        return backends
