"""
設定管理クラスモジュール
"""
import os
import json
import logging
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
from utils_config import get_config, update_config, validate_config

logger = logging.getLogger(__name__)

class ConfigManager:
    """
    設定の読み込み、保存、バックアップ、復元を管理するクラス
    """
    def __init__(self, config_path: Optional[str] = None):
        """
        Args:
            config_path: 設定ファイルのパス。Noneの場合はデフォルトパスを使用
        """
        self.config_path = config_path or str(Path(__file__).parent / "config" / "config.json")
        self.backup_dir = Path(self.config_path).parent / "backups"
        self.current_config = None
        
    def load(self) -> Dict[str, Any]:
        """設定を読み込む"""
        self.current_config = get_config()
        return self.current_config
    
    def save(self, new_config: Dict[str, Any]) -> bool:
        """
        設定を保存する
        
        Args:
            new_config: 新しい設定
            
        Returns:
            bool: 保存に成功したかどうか
        """
        return update_config(new_config)
    
    def validate(self) -> Dict[str, List[str]]:
        """設定のバリデーションを実行"""
        if self.current_config is None:
            self.load()
        return validate_config(self.current_config)
    
    def create_backup(self) -> bool:
        """
        現在の設定のバックアップを作成
        
        Returns:
            bool: バックアップに成功したかどうか
        """
        try:
            # バックアップディレクトリの作成
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            
            # ファイル名の生成 (日時を含む)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = self.backup_dir / f"config_backup_{timestamp}.json"
            
            # バックアップの作成
            shutil.copy2(self.config_path, backup_file)
            logger.info(f"設定のバックアップを作成しました: {backup_file}")
            
            # 古いバックアップの削除
            self._cleanup_old_backups()
            return True
        except Exception as e:
            logger.error(f"バックアップの作成に失敗しました: {e}")
            return False
    
    def restore_backup(self, backup_file: str) -> bool:
        """
        バックアップから設定を復元
        
        Args:
            backup_file: 復元するバックアップファイルのパス
            
        Returns:
            bool: 復元に成功したかどうか
        """
        try:
            backup_path = Path(backup_file)
            if not backup_path.exists():
                logger.error(f"バックアップファイルが見つかりません: {backup_file}")
                return False
            
            # 設定ファイルをバックアップ
            self.create_backup()
            
            # バックアップから復元
            shutil.copy2(backup_path, self.config_path)
            logger.info(f"設定を復元しました: {backup_file}")
            
            # 設定の再読み込み
            self.load()
            return True
        except Exception as e:
            logger.error(f"設定の復元に失敗しました: {e}")
            return False
    
    def _cleanup_old_backups(self):
        """古いバックアップファイルを削除"""
        try:
            # 設定から最大バックアップ数を取得
            config = get_config()
            max_backups = config.get("settings", {}).get("backup", {}).get("max_backups", 5)
            
            # バックアップファイルを日付順にソート
            backup_files = sorted(
                self.backup_dir.glob("config_backup_*.json"),
                key=lambda x: x.stat().st_mtime,
                reverse=True
            )
            
            # 古いバックアップを削除
            for file in backup_files[max_backups:]:
                file.unlink()
                logger.info(f"古いバックアップを削除しました: {file}")
        except Exception as e:
            logger.error(f"バックアップのクリーンアップに失敗しました: {e}")
    
    def get_plugin_config(self, plugin_name: str) -> Optional[Dict[str, Any]]:
        """
        プラグインの設定を取得
        
        Args:
            plugin_name: プラグイン名
            
        Returns:
            Optional[Dict[str, Any]]: プラグインの設定（存在しない場合はNone）
        """
        if self.current_config is None:
            self.load()
        
        for plugin in self.current_config.get("plugins", []):
            if plugin.get("name") == plugin_name:
                return plugin.get("settings", {})
        return None
    
    def update_plugin_config(self, plugin_name: str, settings: Dict[str, Any]) -> bool:
        """
        プラグインの設定を更新
        
        Args:
            plugin_name: プラグイン名
            settings: 新しい設定
            
        Returns:
            bool: 更新に成功したかどうか
        """
        if self.current_config is None:
            self.load()
        
        found = False
        for plugin in self.current_config.get("plugins", []):
            if plugin.get("name") == plugin_name:
                plugin["settings"] = settings
                found = True
                break
        
        if not found:
            logger.error(f"プラグインの設定が見つかりません: {plugin_name}")
            return False
        
        return self.save(self.current_config)

# シングルトンインスタンス
_config_manager = None
def get_config_manager() -> ConfigManager:
    """ConfigManagerのシングルトンインスタンスを取得"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager
