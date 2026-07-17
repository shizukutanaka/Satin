"""
バックアップ管理ユーティリティモジュール
バージョン: 2.1.0 (重複メソッド除去・import 修正)
"""
import logging
import shutil
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
            try:
                client = _gcs.Client()
                self._cloud_bucket_obj = client.get_bucket(bucket_name)
            except Exception as e:
                logger.error(f"クラウドバックアップの初期化に失敗しました: {e}")
                self.cloud_enabled = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_backup(self, target_dir: str, backup_name: Optional[str] = None) -> str:
        """ディレクトリの ZIP バックアップを作成して保存パスを返す。

        shutil.make_archive は最終パスへ直接書き込むため、途中でクラッシュすると
        壊れた zip が残り、backup_name を使い回した場合は以前の正常なバックアップ
        まで巻き添えで破壊される。一時ファイルへ書いてから os.replace で
        アトミックに差し替えることで、失敗時も既存の正常なバックアップを保持する。
        """
        try:
            target_path = Path(target_dir)
            if not target_path.exists():
                raise FileNotFoundError(f"対象ディレクトリが見つかりません: {target_dir}")

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            name = backup_name or f"backup_{timestamp}"
            backup_path = self.backup_dir / f"{name}.zip"
            tmp_stem = self.backup_dir / f".{name}.{timestamp}.tmp"

            import os
            archive_path = shutil.make_archive(
                str(tmp_stem),
                "zip",
                target_path,
            )
            os.replace(archive_path, backup_path)

            # バックアップ zip は config/mood.json / user_profile.json / 会話ログ等の
            # 個人データを含み得るため、生成直後に所有者のみ読み書き可へ制限する。
            # umask 既定 (0o644) のままだとマルチユーザー環境で他ユーザーに読まれる。
            try:
                from fsutil import restrict_to_owner
                restrict_to_owner(str(backup_path))
            except Exception:
                # 権限制限は best-effort。失敗してもバックアップ自体は成功扱い。
                pass

            if self._cloud_bucket_obj:
                self._upload_to_cloud(backup_path)

            logger.info(f"バックアップを作成しました: {backup_path}")
            return str(backup_path)
        except Exception as e:
            logger.error(f"バックアップの作成に失敗しました: {e}")
            raise

    def get_latest_backup(self) -> Optional[Path]:
        """最新のバックアップ ZIP を返す。

        backup_scheduler がタイマー/別スレッドから delete_backup を呼びうるため、
        glob() と stat() の間にファイルが消える競合がありうる。list_backups() と
        同様に stat() 失敗（消えたファイル）は無視して継続する。
        """
        entries = []
        for f in self.backup_dir.glob("*.zip"):
            try:
                entries.append((f, f.stat().st_mtime))
            except OSError:
                continue  # 別スレッドが glob 後に削除した
        if not entries:
            return None
        entries.sort(key=lambda pair: pair[1], reverse=True)
        return entries[0][0]

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
                    # create_backup() has no incremental code path — every
                    # backup this class produces is a full zip snapshot.
                    # The old "full_backup" in name check never matched the
                    # real default name (backup_<timestamp>.zip), so every
                    # backup was mislabeled "incremental".
                    "type": "full",
                }
                backups.append(info)
            except Exception as e:
                logger.error(f"バックアップ情報の取得に失敗しました: {backup_file} - {e}")
        return sorted(backups, key=lambda x: x["created"], reverse=True)

    def restore_backup(self, backup_file: str, target_dir: str) -> bool:
        """バックアップを target_dir に展開して復元する。

        Zip Slip 防御: zip 内のエントリ名に ``../`` や絶対パスが含まれていると
        ``shutil.unpack_archive`` (内部で ``zipfile.extractall``) は target_dir
        の外側にファイルを書き出してしまう (任意ファイル書き込み脆弱性)。
        各エントリの解決後パスが ``target_dir`` 配下に収まるか個別に検証する。

        展開失敗時の一貫性: 全エントリをまず一時ステージングディレクトリへ
        展開し、全件成功した場合のみ target_dir へ移す。target_dir へ直接
        書き込むと、途中のエントリで失敗（ディスク満杯・壊れたzip等）した際に
        既に書き込み済みのファイルが target_dir に残り、戻り値 False にも
        関わらず target_dir が部分的に変更されてしまう。
        """
        import os
        import tempfile
        staging_dir = None
        try:
            backup_path = Path(backup_file)
            if not backup_path.exists():
                raise FileNotFoundError(f"バックアップファイルが見つかりません: {backup_file}")

            target_path = Path(target_dir)
            target_path.mkdir(parents=True, exist_ok=True)

            staging_dir = tempfile.mkdtemp(prefix=".restore_staging_", dir=str(self.backup_dir))
            staging_real = os.path.realpath(staging_dir)
            with zipfile.ZipFile(backup_path, "r") as zf:
                for entry in zf.namelist():
                    if entry.endswith("/"):  # ディレクトリエントリは skip
                        continue
                    dest_path = os.path.realpath(os.path.join(staging_real, entry))
                    if (dest_path != staging_real
                            and not dest_path.startswith(staging_real + os.sep)):
                        logger.warning(f"Zip Slip 検出、スキップ: {entry}")
                        continue
                    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                    with zf.open(entry) as src, open(dest_path, "wb") as dst:
                        shutil.copyfileobj(src, dst)

            # 全件展開に成功した場合のみ target_dir へ反映する。
            target_real = os.path.realpath(target_path)
            for root, _dirs, files in os.walk(staging_real):
                rel = os.path.relpath(root, staging_real)
                dest_root = target_real if rel == "." else os.path.join(target_real, rel)
                os.makedirs(dest_root, exist_ok=True)
                for fname in files:
                    os.replace(os.path.join(root, fname), os.path.join(dest_root, fname))

            logger.info(f"バックアップを復元しました: {backup_file} -> {target_dir}")
            return True
        except Exception as e:
            logger.error(f"バックアップの復元に失敗しました: {e}")
            return False
        finally:
            if staging_dir is not None:
                shutil.rmtree(staging_dir, ignore_errors=True)

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
