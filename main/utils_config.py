"""
設定ファイルの読み込み・バリデーション・変換を行うユーティリティモジュール
"""
import os
import json
import yaml
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List, Union
from dataclasses import dataclass, asdict

# ロガーの設定
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# 設定ファイルのデフォルトパス
DEFAULT_CONFIG_DIR = Path(__file__).parent / "config"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.json"

@dataclass
class ConfigSchema:
    """設定ファイルのスキーマ定義"""
    version: str
    settings: Dict[str, Any]
    plugins: List[Dict[str, Any]]
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ConfigSchema':
        """辞書からConfigSchemaオブジェクトを生成"""
        return cls(
            version=data.get("version", "1.0.0"),
            settings=data.get("settings", {}),
            plugins=data.get("plugins", [])
        )

def load_config(file_path: Union[str, Path] = None) -> Dict[str, Any]:
    """
    設定ファイルを読み込む
    
    Args:
        file_path: 設定ファイルのパス。Noneの場合はデフォルトパスを使用
        
    Returns:
        Dict[str, Any]: 設定値の辞書
    """
    if file_path is None:
        file_path = DEFAULT_CONFIG_FILE
    else:
        file_path = Path(file_path)
    
    if not file_path.exists():
        logger.warning(f"設定ファイルが存在しません: {file_path}")
        return {}
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            if file_path.suffix.lower() == '.json':
                return json.load(f)
            elif file_path.suffix.lower() in ('.yaml', '.yml'):
                return yaml.safe_load(f)
            else:
                logger.error(f"サポートされていないファイル形式です: {file_path.suffix}")
                return {}
    except Exception as e:
        logger.error(f"設定ファイルの読み込みに失敗しました: {file_path}\n{str(e)}")
        return {}

def save_config(config: Dict[str, Any], file_path: Union[str, Path] = None) -> bool:
    """
    設定をファイルに保存する
    
    Args:
        config: 保存する設定の辞書
        file_path: 保存先ファイルパス。Noneの場合はデフォルトパスを使用
        
    Returns:
        bool: 保存に成功したかどうか
    """
    if file_path is None:
        file_path = DEFAULT_CONFIG_FILE
    else:
        file_path = Path(file_path)
    
    try:
        # 親ディレクトリが存在しない場合は作成
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            if file_path.suffix.lower() == '.json':
                json.dump(config, f, ensure_ascii=False, indent=2)
            elif file_path.suffix.lower() in ('.yaml', '.yml'):
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
            else:
                logger.error(f"サポートされていないファイル形式です: {file_path.suffix}")
                return False
        return True
    except Exception as e:
        logger.error(f"設定ファイルの保存に失敗しました: {file_path}\n{str(e)}")
        return False

def validate_config(config: Dict[str, Any], schema: Dict[str, Any] = None) -> Dict[str, List[str]]:
    """
    設定値のバリデーションを行う
    
    Args:
        config: 検証する設定の辞書
        schema: バリデーションスキーマ。Noneの場合はデフォルトのスキーマを使用
        
    Returns:
        Dict[str, List[str]]: エラーメッセージの辞書
    """
    errors = {}
    
    # デフォルトのバリデーションルール
    default_schema = {
        "version": {"type": str, "required": True},
        "settings": {
            "type": dict,
            "required": True,
            "schema": {
                "log_level": {"type": str, "allowed": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]},
                "language": {"type": str, "default": "ja"},
                "debug_mode": {"type": bool, "default": False}
            }
        },
        "plugins": {"type": list, "required": False, "default": []}
    }
    
    schema = schema or default_schema
    
    def _validate(data, rules, path=""):
        if isinstance(rules, dict) and "type" in rules:
            if rules.get("required", False) and data is None:
                errors.setdefault(path, []).append("必須フィールドがありません")
                return
                
            if data is not None:
                if not isinstance(data, rules["type"]):
                    errors.setdefault(path, []).append(
                        f"型が不正です (期待: {rules['type'].__name__}, 実際: {type(data).__name__})"
                    )
                
                if "allowed" in rules and data not in rules["allowed"]:
                    errors.setdefault(path, []).append(
                        f"許可されていない値です (許可: {rules['allowed']})"
                    )
                
                if "schema" in rules and isinstance(rules["schema"], dict) and isinstance(data, dict):
                    for k, v in rules["schema"].items():
                        _validate(data.get(k), v, f"{path}.{k}" if path else k)
        
        elif isinstance(data, dict) and isinstance(rules, dict):
            for k, v in rules.items():
                _validate(data.get(k), v, f"{path}.{k}" if path else k)
    
    _validate(config, schema)
    return errors

def merge_configs(base_config: Dict[str, Any], override_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    2つの設定をマージする（上書きあり）
    
    Args:
        base_config: ベースとなる設定
        override_config: 上書きする設定
        
    Returns:
        Dict[str, Any]: マージされた設定
    """
    result = base_config.copy()
    
    for key, value in override_config.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_configs(result[key], value)
        else:
            result[key] = value
    
    return result

# 設定のシングルトンインスタンス
_config_instance = None

def get_config(reload: bool = False) -> Dict[str, Any]:
    """
    設定を取得する（シングルトンパターン）
    
    Args:
        reload: Trueの場合、設定を再読み込みする
        
    Returns:
        Dict[str, Any]: 設定の辞書
    """
    global _config_instance
    
    if _config_instance is None or reload:
        _config_instance = load_config()
        
        # 設定のバリデーション
        errors = validate_config(_config_instance)
        if errors:
            logger.warning("設定に問題があります:")
            for field, msgs in errors.items():
                for msg in msgs:
                    logger.warning(f"  - {field}: {msg}")
    
    return _config_instance

def update_config(new_config: Dict[str, Any], save_to_file: bool = True) -> bool:
    """
    設定を更新する
    
    Args:
        new_config: 新しい設定
        save_to_file: ファイルにも保存するかどうか
        
    Returns:
        bool: 更新に成功したかどうか
    """
    global _config_instance
    
    # バリデーション
    errors = validate_config(new_config)
    if errors:
        logger.error("設定の更新に失敗しました。バリデーションエラーがあります:")
        for field, msgs in errors.items():
            for msg in msgs:
                logger.error(f"  - {field}: {msg}")
        return False
    
    # マージ
    current_config = get_config()
    _config_instance = merge_configs(current_config, new_config)
    
    # ファイルに保存
    if save_to_file:
        return save_config(_config_instance)
    
    return True
