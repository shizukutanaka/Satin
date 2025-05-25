"""
クラウドバックアッププラグイン
バージョン: 1.0.0
特徴:
- Google Cloud Storage統合
- 自動バックアップスケジュール
- バックアップファイルの自動クリーンアップ
- バックアップ状態の監視
"""
import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from google.cloud import storage
from config_manager import get_config_manager

logger = logging.getLogger(__name__)

class CloudBackupPlugin:
    """クラウドバックアッププラグインクラス"""
    def __init__(self):
        """初期化"""
        self.config = get_config_manager()
        self.settings = self.config.get_plugin_config("cloud_backup")
        
        if self.settings:
            self.bucket_name = self.settings.get("bucket_name")
            self.schedule = self.settings.get("schedule", "daily")
            self.max_age = self.settings.get("max_age_days", 30)
            self.max_backups = self.settings.get("max_backups", 10)
            
            # Google Cloud Storageクライアントの初期化
            self.client = storage.Client()
            self.bucket = self.client.get_bucket(self.bucket_name)
            
            # スケジュールの設定
            self.schedule_interval = {
                "hourly": timedelta(hours=1),
                "daily": timedelta(days=1),
                "weekly": timedelta(weeks=1),
                "monthly": timedelta(days=30)
            }[self.schedule]
            
            # 最終バックアップ時間の初期化
            self.last_backup_time = self._get_last_backup_time()
            
    def _get_last_backup_time(self) -> datetime:
        """最後のバックアップ時間を取得"""
        try:
            # バックアップ状態ファイルの読み込み
            state_file = self.bucket.blob("backup_state.json")
            if state_file.exists():
                state = json.loads(state_file.download_as_text())
                return datetime.fromisoformat(state.get("last_backup", "2000-01-01T00:00:00"))
            return datetime.now() - self.schedule_interval
        except Exception as e:
            logger.error(f"バックアップ状態の取得に失敗しました: {e}")
            return datetime.now() - self.schedule_interval
    
    def _update_last_backup_time(self) -> None:
        """最後のバックアップ時間を更新"""
        try:
            state = {"last_backup": datetime.now().isoformat()}
            state_file = self.bucket.blob("backup_state.json")
            state_file.upload_from_string(json.dumps(state))
        except Exception as e:
            logger.error(f"バックアップ状態の更新に失敗しました: {e}")
    
    def _cleanup_old_backups(self) -> None:
        """古いバックアップをクリーンアップ"""
        try:
            # バックアップファイルのリストを取得
            backups = []
            for blob in self.bucket.list_blobs():
                if blob.name.endswith(".zip"):
                    backups.append({
                        "blob": blob,
                        "age": datetime.now() - blob.time_created
                    })
            
            # 古いバックアップの削除
            for backup in sorted(backups, key=lambda x: x["age"])[:-self.max_backups]:
                if backup["age"] > timedelta(days=self.max_age):
                    backup["blob"].delete()
                    logger.info(f"古いバックアップを削除しました: {backup['blob'].name}")
        except Exception as e:
            logger.error(f"バックアップのクリーンアップに失敗しました: {e}")
    
    def needs_backup(self) -> bool:
        """
        バックアップが必要かどうかを判断
        
        Returns:
            bool: バックアップが必要かどうか
        """
        return datetime.now() - self.last_backup_time >= self.schedule_interval
    
    def upload_backup(self, backup_file: str) -> bool:
        """
        バックアップファイルをクラウドにアップロード
        
        Args:
            backup_file: アップロードするバックアップファイルのパス
            
        Returns:
            bool: アップロードに成功したかどうか
        """
        try:
            # バックアップファイルのアップロード
            blob = self.bucket.blob(os.path.basename(backup_file))
            blob.upload_from_filename(backup_file)
            
            # バックアップ状態の更新
            self._update_last_backup_time()
            
            # 古いバックアップのクリーンアップ
            self._cleanup_old_backups()
            
            logger.info(f"バックアップをクラウドにアップロードしました: {backup_file}")
            return True
        except Exception as e:
            logger.error(f"クラウドバックアップに失敗しました: {e}")
            return False
    
    def download_backup(self, backup_name: str, target_dir: str) -> bool:
        """
        クラウドからバックアップファイルをダウンロード
        
        Args:
            backup_name: ダウンロードするバックアップファイル名
            target_dir: ダウンロード先ディレクトリ
            
        Returns:
            bool: ダウンロードに成功したかどうか
        """
        try:
            # バックアップファイルのダウンロード
            blob = self.bucket.blob(backup_name)
            if not blob.exists():
                raise FileNotFoundError(f"バックアップファイルが見つかりません: {backup_name}")
            
            target_path = os.path.join(target_dir, backup_name)
            blob.download_to_filename(target_path)
            logger.info(f"バックアップをダウンロードしました: {backup_name} -> {target_dir}")
            return True
        except Exception as e:
            logger.error(f"バックアップのダウンロードに失敗しました: {e}")
            return False
    
    def list_backups(self) -> List[Dict[str, Any]]:
        """
        クラウド上のバックアップファイル一覧を取得
        
        Returns:
            List[Dict[str, Any]]: バックアップファイル情報のリスト
        """
        try:
            backups = []
            for blob in self.bucket.list_blobs():
                if blob.name.endswith(".zip"):
                    backups.append({
                        "name": blob.name,
                        "size": blob.size,
                        "created": blob.time_created.isoformat(),
                        "type": "full" if "full_backup" in blob.name else "incremental"
                    })
            
            return sorted(backups, key=lambda x: x["created"], reverse=True)
        except Exception as e:
            logger.error(f"バックアップ一覧の取得に失敗しました: {e}")
            return []
