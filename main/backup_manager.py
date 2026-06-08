"""
バックアップ管理ユーティリティモジュール
バージョン: 2.1.0 (重複メソッド除去・import 修正)
"""
import logging
import shutil
import hashlib
import zipfile
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional
from config_manager import get_config_manager

try:
    from google.cloud import storage as _gcs
except ImportError:
    _gcs = None  # type: ignore

logger = logging.getLogger(__name__)


class BackupManager:
    """バックアップの作成、管理、復元を行うクラス"""

    def __init__(self):
        self.config_manager = get_config_manager()
        self.backup_dir = Path(self.config_manager.config_path).parent / "backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        self.cloud_enabled = self.config_manager.get_plugin_config("cloud_backup")
        self._cloud_bucket_obj = None
        if self.cloud_enabled and _gcs is not None:
            bucket_name = self.cloud_enabled.get("bucket_name")
            client = _gcs.Client()
            self._cloud_bucket_obj = client.get_bucket(bucket_name)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_backup(self, target_dir: str, backup_name: Optional[str] = None) -> str:
        """ディレクトリの ZIP バックアップを作成して保存パスを返す。"""
        try:
            target_path = Path(target_dir)
            if not target_path.exists():
                raise FileNotFoundError(f"対象ディレクトリが見つかりません: {target_dir}")

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            name = backup_name or f"backup_{timestamp}"
            backup_path = self.backup_dir / f"{name}.zip"

            shutil.make_archive(
                str(backup_path.with_suffix("")),
                "zip",
                target_path,
            )

            if self._cloud_bucket_obj:
                self._upload_to_cloud(backup_path)

            logger.info(f"バックアップを作成しました: {backup_path}")
            return str(backup_path)
        except Exception as e:
            logger.error(f"バックアップの作成に失敗しました: {e}")
            raise

    def get_latest_backup(self) -> Optional[Path]:
        """最新のバックアップ ZIP を返す。"""
        files = sorted(
            self.backup_dir.glob("*.zip"),
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        )
        return files[0] if files else None

    def list_backups(self) -> List[Dict[str, Any]]:
        """バックアップ一覧を新しい順で返す。"""
        backups = []
        for backup_file in self.backup_dir.glob("*.zip"):
            try:
                info = {
                    "name": backup_file.name,
                    "path": str(backup_file),
                    "size": backup_file.stat().st_size,
                    "created": datetime.fromtimestamp(
                        backup_file.stat().st_mtime
                    ).strftime("%Y-%m-%d %H:%M:%S"),
                    "is_valid": self._validate_backup(backup_file),
                    "type": "full" if "full_backup" in backup_file.name else "incremental",
                }
                backups.append(info)
            except Exception as e:
                logger.error(f"バックアップ情報の取得に失敗しました: {backup_file} - {e}")
        return sorted(backups, key=lambda x: x["created"], reverse=True)

    def restore_backup(self, backup_file: str, target_dir: str) -> bool:
        """バックアップを target_dir に展開して復元する。"""
        try:
            backup_path = Path(backup_file)
            if not backup_path.exists():
                raise FileNotFoundError(f"バックアップファイルが見つかりません: {backup_file}")

            target_path = Path(target_dir)
            target_path.mkdir(parents=True, exist_ok=True)
            shutil.unpack_archive(str(backup_path), target_path)

            logger.info(f"バックアップを復元しました: {backup_file} -> {target_dir}")
            return True
        except Exception as e:
            logger.error(f"バックアップの復元に失敗しました: {e}")
            return False

    def delete_backup(self, backup_file: str) -> bool:
        """バックアップファイルを削除する。"""
        try:
            backup_path = Path(backup_file)
            if not backup_path.exists():
                raise FileNotFoundError(f"バックアップファイルが見つかりません: {backup_file}")

            if self._cloud_bucket_obj:
                try:
                    blob = self._cloud_bucket_obj.blob(backup_path.name)
                    blob.delete()
                except Exception as e:
                    logger.error(f"クラウドバックアップの削除に失敗しました: {e}")

            backup_path.unlink()
            logger.info(f"バックアップを削除しました: {backup_file}")
            return True
        except Exception as e:
            logger.error(f"バックアップの削除に失敗しました: {e}")
            return False

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _validate_backup(self, backup_file: Path) -> bool:
        """ZIP マジックバイトと内部整合性で検証する。"""
        try:
            with open(backup_file, "rb") as f:
                if f.read(4) != b"PK\x03\x04":
                    return False
            with zipfile.ZipFile(backup_file, "r") as zf:
                return zf.testzip() is None
        except Exception:
            return False

    def _upload_to_cloud(self, backup_file: Path) -> None:
        """クラウドバケットにバックアップをアップロードする。"""
        try:
            blob = self._cloud_bucket_obj.blob(backup_file.name)
            blob.upload_from_filename(str(backup_file))
            logger.info(f"クラウドにアップロードしました: {backup_file.name}")
        except Exception as e:
            logger.error(f"クラウドバックアップに失敗しました: {e}")


# シングルトン
_backup_manager: Optional[BackupManager] = None


def get_backup_manager() -> BackupManager:
    global _backup_manager
    if _backup_manager is None:
        _backup_manager = BackupManager()
    return _backup_manager
