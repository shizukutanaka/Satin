"""
バックアップスケジューラー (重複メソッド除去・import 修正)

schedule パッケージが未インストールの場合は ImportError を起こさず
scheduler 機能を無効化して gracefully に動作します。
"""
from __future__ import annotations

import time
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    import schedule as _schedule
except ImportError:
    _schedule = None  # type: ignore

from backup_manager import BackupManager
from error_handling import BackupError
from notification_system import NotificationSystem

logger = logging.getLogger(__name__)


class BackupScheduler:
    """定期バックアップのスケジューリングと通知を管理するクラス"""

    def __init__(
        self,
        backup_manager: BackupManager,
        notification_system: NotificationSystem,
        backup_target_dir: str = ".",
    ):
        self.backup_manager = backup_manager
        self.notification_system = notification_system
        self.backup_target_dir = backup_target_dir
        self.running = False
        self.backup_history: List[Dict[str, Any]] = []
        self.max_history = 30

        if _schedule is not None:
            self._scheduler = _schedule.Scheduler()
        else:
            self._scheduler = None
            logger.warning(
                "schedule パッケージが見つかりません。スケジュール機能は無効です。"
                " pip install schedule でインストールしてください。"
            )

    # ------------------------------------------------------------------
    # Schedule registration
    # ------------------------------------------------------------------

    def add_daily_backup(self, hour: int, minute: int) -> None:
        """毎日指定時刻にバックアップを実行するジョブを追加する。"""
        if self._scheduler is None:
            raise BackupError("schedule パッケージが必要です: pip install schedule")
        try:
            self._scheduler.every().day.at(f"{hour:02d}:{minute:02d}").do(
                self._run_backup, "daily"
            )
            self.notification_system.send_notification(
                title="Backup Scheduler",
                message=f"Daily backup scheduled at {hour:02d}:{minute:02d}",
                level="info",
            )
        except Exception as e:
            raise BackupError(f"Failed to schedule daily backup: {e}")

    def add_weekly_backup(self, day: str, hour: int, minute: int) -> None:
        """毎週指定曜日・時刻にバックアップを実行するジョブを追加する。"""
        if self._scheduler is None:
            raise BackupError("schedule パッケージが必要です: pip install schedule")
        try:
            day_jobs = {
                "monday": self._scheduler.every().monday,
                "tuesday": self._scheduler.every().tuesday,
                "wednesday": self._scheduler.every().wednesday,
                "thursday": self._scheduler.every().thursday,
                "friday": self._scheduler.every().friday,
                "saturday": self._scheduler.every().saturday,
                "sunday": self._scheduler.every().sunday,
            }
            if day.lower() not in day_jobs:
                raise BackupError(f"Invalid day: {day}")
            day_jobs[day.lower()].at(f"{hour:02d}:{minute:02d}").do(
                self._run_backup, "weekly"
            )
            self.notification_system.send_notification(
                title="Backup Scheduler",
                message=f"Weekly backup on {day} at {hour:02d}:{minute:02d}",
                level="info",
            )
        except BackupError:
            raise
        except Exception as e:
            raise BackupError(f"Failed to schedule weekly backup: {e}")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """スケジューラーのメインループを開始する (ブロッキング)。"""
        if self.running:
            raise BackupError("Backup scheduler is already running")
        if self._scheduler is None:
            raise BackupError("schedule パッケージが必要です: pip install schedule")

        self.running = True
        self.notification_system.send_notification(
            title="Backup Scheduler", message="Backup scheduler started", level="info"
        )
        try:
            while self.running:
                self._scheduler.run_pending()
                time.sleep(60)
        except Exception as e:
            msg = f"Error in backup scheduler: {e}"
            self.notification_system.send_notification(
                title="Backup Scheduler Error", message=msg, level="error"
            )
            raise BackupError(msg)

    def stop(self) -> None:
        """スケジューラーを停止する。"""
        self.running = False
        self.notification_system.send_notification(
            title="Backup Scheduler", message="Backup scheduler stopped", level="info"
        )

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def get_backup_history(self) -> List[Dict[str, Any]]:
        return self.backup_history.copy()

    def clear_backup_history(self) -> None:
        self.backup_history.clear()
        self.notification_system.send_notification(
            title="Backup Scheduler", message="Backup history cleared", level="info"
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_backup(self, backup_type: str) -> None:
        """バックアップを実行して履歴とステータス通知を更新する。"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        self.notification_system.send_notification(
            title="Backup Started",
            message=f"{backup_type.title()} backup started at {backup_time}",
            level="info",
        )

        success = False
        error_msg: Optional[str] = None
        try:
            self.backup_manager.create_backup(self.backup_target_dir)
            success = True
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Backup failed: {e}")

        history_entry: Dict[str, Any] = {
            "timestamp": timestamp,
            "type": backup_type,
            "time": backup_time,
            "success": success,
            "error": error_msg,
        }
        self.backup_history.append(history_entry)
        if len(self.backup_history) > self.max_history:
            self.backup_history.pop(0)

        if success:
            self.notification_system.send_notification(
                title="Backup Completed",
                message=f"{backup_type.title()} backup completed successfully",
                level="success",
            )
        else:
            self.notification_system.send_notification(
                title="Backup Failed",
                message=f"{backup_type.title()} backup failed: {error_msg}",
                level="error",
            )
