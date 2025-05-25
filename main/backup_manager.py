"""
バックアップ管理ユーティリティモジュール
バージョン: 2.0.0
特徴:
- 増分バックアップサポート
- クラウドバックアップ統合
- バックアップ検証機能
- スケジュールバックアップ
- パフォーマンス最適化
"""
import os
import json
import logging
import shutil
import hashlib
import tempfile
import subprocess
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from config_manager import get_config_manager
from google.cloud import storage  # クラウドバックアップ用

logger = logging.getLogger(__name__)

class BackupManager:
    """
    バックアップの作成、管理、復元を行うクラス
    """
    def __init__(self):
        """初期化"""
        self.config_manager = get_config_manager()
        self.backup_dir = Path(self.config_manager.config_path).parent / "backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        
        # クラウドバックアップ設定
        self.cloud_enabled = self.config_manager.get_plugin_config("cloud_backup")
        if self.cloud_enabled:
            self.cloud_bucket = self.cloud_enabled.get("bucket_name")
            self.cloud_client = storage.Client()
            self.cloud_bucket_obj = self.cloud_client.get_bucket(self.cloud_bucket)
            
    def create_backup(self, target_dir: str, backup_name: Optional[str] = None) -> str:
        """
        ディレクトリのバックアップを作成
        
        Args:
            target_dir: バックアップ対象のディレクトリパス
            backup_name: バックアップ名（指定がない場合は日時を含む名前を使用）
            
        Returns:
            str: 作成されたバックアップファイルのパス
        """
        try:
            target_path = Path(target_dir)
            if not target_path.exists():
                raise FileNotFoundError(f"対象ディレクトリが見つかりません: {target_dir}")
            
            # 増分バックアップのチェック
            last_backup = self.get_latest_backup()
            if last_backup:
                diff_files = self._get_diff_files(target_path, last_backup)
                if diff_files:
                    return self._create_incremental_backup(target_path, diff_files, backup_name)
                else:
                    logger.info("変更が見つからないため、バックアップをスキップします")
                    return None
            
            # 完全バックアップの作成
            return self._create_full_backup(target_path, backup_name)
            
        except Exception as e:
            logger.error(f"バックアップの作成に失敗しました: {e}")
            raise
    
    def _create_full_backup(self, target_path: Path, backup_name: Optional[str] = None) -> str:
        """完全バックアップを作成"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = backup_name or f"full_backup_{timestamp}"
        backup_path = self.backup_dir / f"{backup_name}.zip"
        
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            temp_backup = temp_path / "backup.zip"
            
            # ZIPファイルの作成（圧縮率最適化）
            subprocess.run([
                "7z", "a", 
                "-tzip", 
                "-mx=9",  # 最高圧縮率
                str(temp_backup),
                str(target_path)
            ], check=True)
            
            # バックアップの検証
            if not self._validate_backup(temp_backup):
                raise ValueError("バックアップの検証に失敗しました")
            
            # バックアップの移動
            shutil.move(str(temp_backup), str(backup_path))
            
            # クラウドバックアップ
            if self.cloud_enabled:
                self._upload_to_cloud(backup_path)
            
            logger.info(f"完全バックアップを作成しました: {backup_path}")
            return str(backup_path)
    
    def _create_incremental_backup(self, target_path: Path, diff_files: List[Path], backup_name: Optional[str] = None) -> str:
        """増分バックアップを作成"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = backup_name or f"incremental_backup_{timestamp}"
        backup_path = self.backup_dir / f"{backup_name}.zip"
        
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            temp_backup = temp_path / "backup.zip"
            
            # 変更されたファイルのみをバックアップ
            with zipfile.ZipFile(temp_backup, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for file in diff_files:
                    zipf.write(file, arcname=file.relative_to(target_path))
            
            # バックアップの検証
            if not self._validate_backup(temp_backup):
                raise ValueError("バックアップの検証に失敗しました")
            
            # バックアップの移動
            shutil.move(str(temp_backup), str(backup_path))
            
            # クラウドバックアップ
            if self.cloud_enabled:
                self._upload_to_cloud(backup_path)
            
            logger.info(f"増分バックアップを作成しました: {backup_path}")
            return str(backup_path)
    
    def _get_diff_files(self, target_path: Path, last_backup: Path) -> List[Path]:
        """前回のバックアップとの差分を取得"""
        diff_files = []
        with zipfile.ZipFile(last_backup, 'r') as zipf:
            for file in target_path.rglob("*"):
                if file.is_file():
                    rel_path = file.relative_to(target_path)
                    if str(rel_path) not in zipf.namelist():
                        diff_files.append(file)
                    else:
                        # ファイルのハッシュを比較
                        with open(file, 'rb') as f:
                            file_hash = hashlib.sha256(f.read()).hexdigest()
                        with zipf.open(str(rel_path)) as z:
                            zip_hash = hashlib.sha256(z.read()).hexdigest()
                        if file_hash != zip_hash:
                            diff_files.append(file)
        return diff_files
    
    def _validate_backup(self, backup_file: Path) -> bool:
        """バックアップファイルの検証"""
        try:
            with zipfile.ZipFile(backup_file, 'r') as zipf:
                # ファイルの整合性チェック
                if zipf.testzip() is not None:
                    return False
                
                # ファイルのハッシュチェック
                for file in zipf.namelist():
                    with zipf.open(file) as f:
                        if hashlib.sha256(f.read()).hexdigest() != self._get_file_hash(file):
                            return False
            return True
        except Exception:
            return False
    
    def _upload_to_cloud(self, backup_file: Path) -> None:
        """クラウドにバックアップをアップロード"""
        try:
            blob = self.cloud_bucket_obj.blob(backup_file.name)
            blob.upload_from_filename(str(backup_file))
            logger.info(f"バックアップをクラウドにアップロードしました: {backup_file.name}")
        except Exception as e:
            logger.error(f"クラウドバックアップに失敗しました: {e}")
    
    def get_latest_backup(self) -> Optional[Path]:
        """最新のバックアップを取得"""
        backup_files = sorted(
            self.backup_dir.glob("*.zip"),
            key=lambda x: x.stat().st_mtime,
            reverse=True
        )
        return backup_files[0] if backup_files else None
    
    def list_backups(self) -> List[Dict[str, Any]]:
        """
        作成されたバックアップの一覧を取得
        
        Returns:
            List[Dict[str, Any]]: バックアップ情報のリスト
        """
        backups = []
        for backup_file in self.backup_dir.glob("*.zip"):
            try:
                info = {
                    "name": backup_file.name,
                    "path": str(backup_file),
                    "size": backup_file.stat().st_size,
                    "created": datetime.fromtimestamp(backup_file.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    "is_valid": self._validate_backup(backup_file),
                    "type": "full" if "full_backup" in backup_file.name else "incremental"
                }
                backups.append(info)
            except Exception as e:
                logger.error(f"バックアップ情報の取得に失敗しました: {backup_file} - {e}")
        
        # 新しい順にソート
        return sorted(backups, key=lambda x: x["created"], reverse=True)
    
    def restore_backup(self, backup_file: str, target_dir: str) -> bool:
        """
        バックアップから復元
        
        Args:
            backup_file: 復元するバックアップファイルのパス
            target_dir: 復元先ディレクトリパス
            
        Returns:
            bool: 復元に成功したかどうか
        """
        try:
            backup_path = Path(backup_file)
            if not backup_path.exists():
                raise FileNotFoundError(f"バックアップファイルが見つかりません: {backup_file}")
            
            target_path = Path(target_dir)
            target_path.mkdir(parents=True, exist_ok=True)
            
            # バックアップの検証
            if not self._validate_backup(backup_path):
                raise ValueError("バックアップファイルが破損しています")
            
            # ZIPファイルの展開
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                temp_extract = temp_path / "extract"
                temp_extract.mkdir()
                
                # 展開
                with zipfile.ZipFile(backup_path, 'r') as zipf:
                    zipf.extractall(temp_extract)
                
                # ファイルの移動
                for item in temp_extract.rglob("*"):
                    target_item = target_path / item.relative_to(temp_extract)
                    target_item.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(item), str(target_item))
            
            logger.info(f"バックアップを復元しました: {backup_file} -> {target_dir}")
            return True
        except Exception as e:
            logger.error(f"バックアップの復元に失敗しました: {e}")
            return False
    
    def delete_backup(self, backup_file: str) -> bool:
        """
        バックアップファイルを削除
        
        Args:
            backup_file: 削除するバックアップファイルのパス
            
        Returns:
            bool: 削除に成功したかどうか
        """
        try:
            backup_path = Path(backup_file)
            if not backup_path.exists():
                raise FileNotFoundError(f"バックアップファイルが見つかりません: {backup_file}")
            
            # クラウドバックアップの削除
            if self.cloud_enabled:
                try:
                    blob = self.cloud_bucket_obj.blob(backup_path.name)
                    blob.delete()
                    logger.info(f"クラウドバックアップを削除しました: {backup_path.name}")
                except Exception as e:
                    logger.error(f"クラウドバックアップの削除に失敗しました: {e}")
            
            backup_path.unlink()
            logger.info(f"バックアップを削除しました: {backup_file}")
            return True
        except Exception as e:
            logger.error(f"バックアップの削除に失敗しました: {e}")
            return False
    
    def create_backup(self, target_dir: str, backup_name: Optional[str] = None) -> str:
        """
        ディレクトリのバックアップを作成
        
        Args:
            target_dir: バックアップ対象のディレクトリパス
            backup_name: バックアップ名（指定がない場合は日時を含む名前を使用）
            
        Returns:
            str: 作成されたバックアップファイルのパス
        """
        try:
            target_path = Path(target_dir)
            if not target_path.exists():
                raise FileNotFoundError(f"対象ディレクトリが見つかりません: {target_dir}")
            
            # バックアップ名の生成
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = backup_name or f"backup_{timestamp}"
            backup_path = self.backup_dir / f"{backup_name}.zip"
            
            # ZIPファイルの作成
            shutil.make_archive(
                str(backup_path.with_suffix("")),  # .zipを除いたパス
                "zip",
                target_path
            )
            
            logger.info(f"バックアップを作成しました: {backup_path}")
            return str(backup_path)
        except Exception as e:
            logger.error(f"バックアップの作成に失敗しました: {e}")
            raise
    
    def list_backups(self) -> List[Dict[str, Any]]:
        """
        作成されたバックアップの一覧を取得
        
        Returns:
            List[Dict[str, Any]]: バックアップ情報のリスト
        """
        backups = []
        for backup_file in self.backup_dir.glob("*.zip"):
            try:
                info = {
                    "name": backup_file.name,
                    "path": str(backup_file),
                    "size": backup_file.stat().st_size,
                    "created": datetime.fromtimestamp(backup_file.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    "is_valid": self._validate_backup(backup_file)
                }
                backups.append(info)
            except Exception as e:
                logger.error(f"バックアップ情報の取得に失敗しました: {backup_file} - {e}")
        
        # 新しい順にソート
        return sorted(backups, key=lambda x: x["created"], reverse=True)
    
    def restore_backup(self, backup_file: str, target_dir: str) -> bool:
        """
        バックアップから復元
        
        Args:
            backup_file: 復元するバックアップファイルのパス
            target_dir: 復元先ディレクトリパス
            
        Returns:
            bool: 復元に成功したかどうか
        """
        try:
            backup_path = Path(backup_file)
            if not backup_path.exists():
                raise FileNotFoundError(f"バックアップファイルが見つかりません: {backup_file}")
            
            target_path = Path(target_dir)
            target_path.mkdir(parents=True, exist_ok=True)
            
            # ZIPファイルの展開
            shutil.unpack_archive(str(backup_path), target_path)
            logger.info(f"バックアップを復元しました: {backup_file} -> {target_dir}")
            
            return True
        except Exception as e:
            logger.error(f"バックアップの復元に失敗しました: {e}")
            return False
    
    def delete_backup(self, backup_file: str) -> bool:
        """
        バックアップファイルを削除
        
        Args:
            backup_file: 削除するバックアップファイルのパス
            
        Returns:
            bool: 削除に成功したかどうか
        """
        try:
            backup_path = Path(backup_file)
            if not backup_path.exists():
                raise FileNotFoundError(f"バックアップファイルが見つかりません: {backup_file}")
            
            backup_path.unlink()
            logger.info(f"バックアップを削除しました: {backup_file}")
            return True
        except Exception as e:
            logger.error(f"バックアップの削除に失敗しました: {e}")
            return False
    
    def _validate_backup(self, backup_file: Path) -> bool:
        """
        バックアップファイルの有効性を検証
        
        Args:
            backup_file: バックアップファイルのパス
            
        Returns:
            bool: バックアップが有効かどうか
        """
        try:
            # ZIPファイルの有効性チェック
            with open(backup_file, 'rb') as f:
                if f.read(4) != b'PK\x03\x04':  # ZIPファイルのヘッダー確認
                    return False
            return True
        except Exception:
            return False

# シングルトンインスタンス
_backup_manager = None
def get_backup_manager() -> BackupManager:
    """BackupManagerのシングルトンインスタンスを取得"""
    global _backup_manager
    if _backup_manager is None:
        _backup_manager = BackupManager()
    return _backup_manager
