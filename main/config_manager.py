"""
設定管理クラスモジュール
"""
import copy
import logging
import shutil
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List
from utils_config import get_config, update_config, validate_config, DEFAULT_CONFIG_FILE, _ensure_loaded

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
        # 既定パスは utils_config の解決結果に合わせる（存在しない main/config/
        # config.json を指してバックアップが FileNotFound になるのを防ぐ）。
        self.config_path = config_path or str(DEFAULT_CONFIG_FILE)
        self.backup_dir = Path(self.config_path).parent / "backups"
        # 実効設定のキャッシュ。未読込は None（注釈が無いと mypy に None 型と
        # 推論され、load() 後の .get() が全部エラーになっていた）。
        self.current_config: Optional[Dict[str, Any]] = None
        # update_plugin_config()/save() の read-merge-write 区間を保護する。
        # utils_config.update_config() 自体はロック無しで
        # _ensure_loaded()（読み取り）→ merge_configs()（マージ）→
        # _config_instance 差し替え・save_config()（書き込み）を行うため、
        # 2つのプラグインがほぼ同時に初期化されると、両方が同じベース設定を
        # 読み、互いを知らずにマージして書き込み、後勝ちで片方の変更が
        # 静かに失われるロスト・アップデートが起こりうる。
        self._write_lock = threading.Lock()
        
    def load(self) -> Dict[str, Any]:
        """設定を読み込む"""
        loaded = get_config()
        self.current_config = loaded
        return loaded

    def _loaded(self) -> Dict[str, Any]:
        """current_config を必ず非 None で返す（未読込なら読み込む）。

        `if self.current_config is None: self.load()` を各所で繰り返していたが、
        属性を書き換えるだけなので型の絞り込みが効かず、直後の .get() が
        「None に get は無い」と指摘されていた。取得を 1 箇所に集約する。
        """
        if self.current_config is None:
            return self.load()
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
        return validate_config(self._loaded())
    
    def create_backup(self) -> bool:
        """
        現在の設定のバックアップを作成
        
        Returns:
            bool: バックアップに成功したかどうか
        """
        try:
            # バックアップディレクトリの作成
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            
            # ファイル名の生成 (マイクロ秒まで含め同秒内の上書きを防ぐ)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
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
            max_backups = ((config.get("settings") or {}).get("backup") or {}).get("max_backups", 5)
            
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
        config = self._loaded()

        for plugin in config.get("plugins", []):
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
        cached = self._loaded()

        # 保存は環境変数オーバーレイ抜きのベース設定に対して行う。
        # 以前は self.current_config（load() で取得した get_config() 由来の
        # 実効設定、SATIN_* 環境変数オーバーレイ込み）をそのまま save() へ
        # 渡していた。utils_config.update_config() 内部の
        # merge_configs(base, new_config) は override 側の値を優先するため、
        # new_config 全体が実効設定だと、対象プラグイン以外のフィールド
        # （log_level 等）まで含めて実行時の環境変数値がまるごとファイルへ
        # 焼き付いてしまう。utils_config.py 自身は update_config() の
        # 直接呼び出しに対してこれを意図的に防いでいる
        # （_ensure_loaded() でベース設定を使う設計、コメント参照）が、
        # ConfigManager 経由の呼び出しはこの保護を素通りしていた。
        # _ensure_loaded() が返す共有シングルトンを直接書き換えないよう
        # deepcopy してから操作する。
        with self._write_lock:
            base = copy.deepcopy(_ensure_loaded())

            found = False
            for plugin in base.get("plugins", []):
                if plugin.get("name") == plugin_name:
                    plugin["settings"] = settings
                    found = True
                    break

            if not found:
                logger.error(f"プラグインの設定が見つかりません: {plugin_name}")
                return False

            # current_config（実効設定のキャッシュ）も同期し、直後の
            # get_plugin_config() が古い値を返さないようにする。
            for plugin in cached.get("plugins", []):
                if plugin.get("name") == plugin_name:
                    plugin["settings"] = settings
                    break

            return self.save(base)

# シングルトンインスタンス
_config_manager = None
_config_manager_lock = threading.Lock()
def get_config_manager() -> ConfigManager:
    """ConfigManagerのシングルトンインスタンスを取得（スレッドセーフ）。

    ダブルチェックロックで初期化競合を防ぐ。ロックが無いと 2 つのスレッドが
    同時に None を見て別々の ConfigManager を生成し、片方の
    update_plugin_config() の結果が黙って失われる（後勝ちで上書き）。
    """
    global _config_manager
    if _config_manager is None:
        with _config_manager_lock:
            if _config_manager is None:
                _config_manager = ConfigManager()
    return _config_manager
