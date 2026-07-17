"""
バックアップスケジューラー (重複メソッド除去・import 修正)

schedule パッケージが未インストールの場合は ImportError を起こさず
scheduler 機能を無効化して gracefully に動作します。
"""
from __future__ import annotations

import threading
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
        max_backups: Optional[int] = None,
    ):
        self.backup_manager = backup_manager
        self.notification_system = notification_system
        self.backup_target_dir = backup_target_dir
        self.running = False
        self._stop_event = threading.Event()
        self.backup_history: List[Dict[str, Any]] = []
        self.max_history = 30
        # 自動保持件数の上限（None = 無効・既存の挙動を維持）。add_daily_backup /
        # add_weekly_backup で定期実行を設定しても、これまで古いバックアップ
        # ファイルを自動削除する経路が一切無く、無人運用（スケジューラの本来の
        # 目的）でディスクを際限なく消費し続けていた。既存利用者の挙動を変えない
        # よう既定は無効のままとし、明示的に指定した場合のみ有効にする。
        self.max_backups = max_backups

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
            raise BackupError(f"Failed to schedule daily backup: {e}") from e

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
            raise BackupError(f"Failed to schedule weekly backup: {e}") from e

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """スケジューラーのメインループを開始する (ブロッキング)。"""
        if self.running:
            raise BackupError("Backup scheduler is already running")
        if self._scheduler is None:
            raise BackupError("schedule パッケージが必要です: pip install schedule")

        # Clear any set-from-a-previous-stop() flag so this run's wait() actually
        # blocks for 60s instead of returning immediately (busy-spin) on restart.
        self._stop_event.clear()
        self.running = True
        self.notification_system.send_notification(
            title="Backup Scheduler", message="Backup scheduler started", level="info"
        )
        try:
            while self.running:
                self._scheduler.run_pending()
                # Use event.wait so stop() wakes this loop in <1s instead of ≤60s.
                self._stop_event.wait(60)
        except Exception as e:
            msg = f"Error in backup scheduler: {e}"
            self.notification_system.send_notification(
                title="Backup Scheduler Error", message=msg, level="error"
            )
            raise BackupError(msg) from e
        finally:
            # Always reset running on exit so a crashed loop doesn't wedge the
            # scheduler in a permanent "already running" state.
            self.running = False

    def stop(self) -> None:
        """スケジューラーを停止する。"""
        self.running = False
        self._stop_event.set()
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
            # exc_info=True で例外のスタックトレースをログに残す。バックアップ失敗の
            # 根本原因は ZIP 書き込み・権限・ディスクフル・I/O 等多岐にわたるため、
            # メッセージだけだと運用復旧時の切り分けが困難になる (Qiita 既知の落とし穴)。
            logger.error(f"Backup failed: {e}", exc_info=True)

        if success and self.max_backups is not None:
            self._enforce_retention()

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

    def _enforce_retention(self) -> None:
        """max_backups を超えた分の最古のバックアップファイルを削除する。

        list_backups() は新しい順（降順）を返す前提（BackupManager の実装通り）。
        1 件の削除失敗が残りの削除を止めないよう、個別に例外を握り潰す。
        """
        try:
            backups = self.backup_manager.list_backups()
        except Exception as e:
            logger.warning(f"バックアップ保持ポリシーの適用に失敗しました（一覧取得エラー）: {e}")
            return
        if len(backups) <= self.max_backups:
            return
        for old in backups[self.max_backups:]:
            try:
                self.backup_manager.delete_backup(old["path"])
            except Exception as e:
                logger.warning(f"古いバックアップの削除に失敗しました: {old.get('path')}: {e}")
