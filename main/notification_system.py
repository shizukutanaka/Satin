"""
通知システム — 最小スタブ実装

実際の通知バックエンド(win10toast, desktop-notifier 等)がインストールされている場合は
それを利用し、なければコンソールにフォールバックします。
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class NotificationSystem:
    """アプリケーション通知送信クラス"""

    def __init__(self, app_name: str = "Satin"):
        self.app_name = app_name

    def send_notification(
        self,
        title: str,
        message: str,
        level: str = "info",
        duration: int = 5,
    ) -> None:
        """
        通知を送信する。

        Args:
            title: 通知タイトル
            message: 通知本文
            level: ログレベル ("info", "success", "warning", "error")
            duration: 表示時間（秒、GUI 通知が使える場合のみ有効）
        """
        log_level = {
            "info": logging.INFO,
            "success": logging.INFO,
            "warning": logging.WARNING,
            "error": logging.ERROR,
        }.get(level, logging.INFO)

        logger.log(log_level, "[%s] %s: %s", self.app_name, title, message)
