"""
設定ファイルの読み込み・バリデーション・変換を行うユーティリティモジュール
"""
import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List, Union
from dataclasses import dataclass, asdict

try:
    import yaml
except ImportError:  # PyYAML is optional; only needed for .yaml/.yml config files
    yaml = None

try:
    # 環境変数オーバーレイ (12-factor)。config パッケージが import 出来ない環境でも
    # 設定読み込み自体は壊れないよう、失敗時は無効化する。
    from config.env import apply_env_overrides, ENV_SELECTOR_VAR
except Exception:  # pragma: no cover - defensive
    apply_env_overrides = None
    ENV_SELECTOR_VAR = 'SATIN_ENV'

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

def _read_config_file(file_path: Path) -> Dict[str, Any]:
    """単一の設定ファイルを読み込む（環境レイヤーの合成は行わない）。"""
    if not file_path.exists():
        logger.warning(f"設定ファイルが存在しません: {file_path}")
        return {}

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            if file_path.suffix.lower() == '.json':
                return json.load(f) or {}
            elif file_path.suffix.lower() in ('.yaml', '.yml'):
                if yaml is None:
                    logger.error("YAML 設定の読み込みには PyYAML が必要です: pip install pyyaml")
                    return {}
                return yaml.safe_load(f) or {}
            else:
                logger.error(f"サポートされていないファイル形式です: {file_path.suffix}")
                return {}
    except Exception as e:
        logger.error(f"設定ファイルの読み込みに失敗しました: {file_path}\n{str(e)}")
        return {}

def _environment_layer_path(base_path: Path, env_name: str) -> Path:
    """ベース config.json に対する環境レイヤー config.<env>.json のパスを返す。"""
    return base_path.with_name(f"{base_path.stem}.{env_name}{base_path.suffix}")

def load_config(file_path: Union[str, Path] = None) -> Dict[str, Any]:
    """
    設定ファイルを読み込む（レイヤード・マルチ環境対応）。

    ベース設定ファイルを読み込んだ後、環境変数 ``SATIN_ENV`` が設定されていて
    対応する隣接ファイル ``config.<env>.json`` が存在する場合は、それをベース上に
    ディープマージする（Dynaconf / Hydra のレイヤード設定に相当）。
    環境変数によるオーバーレイ（個別キーの上書き）は get_config() 側で更に上に
    適用されるため、優先順位は「実環境変数/.env > 環境レイヤーファイル > ベース」。

    Args:
        file_path: 設定ファイルのパス。Noneの場合はデフォルトパスを使用

    Returns:
        Dict[str, Any]: 設定値の辞書
    """
    if file_path is None:
        file_path = DEFAULT_CONFIG_FILE
    else:
        file_path = Path(file_path)

    config = _read_config_file(file_path)

    env_name = os.environ.get(ENV_SELECTOR_VAR)
    if env_name:
        layer_path = _environment_layer_path(file_path, env_name)
        if layer_path.exists():
            layer = _read_config_file(layer_path)
            config = merge_configs(config, layer)
            logger.info(f"環境レイヤーを適用しました ({env_name}): {layer_path.name}")

    return config

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
                if yaml is None:
                    logger.error("YAML 設定の保存には PyYAML が必要です: pip install pyyaml")
                    return False
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

def _ensure_loaded(reload: bool = False) -> Dict[str, Any]:
    """
    ファイル由来のベース設定（シングルトン）を返す。

    環境変数オーバーレイは含めない。書き戻し（update_config / save_config）が
    実行時の環境変数値をファイルへ永続化してしまうのを防ぐため、ベース設定と
    実効設定を分離している。
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

def get_config(reload: bool = False) -> Dict[str, Any]:
    """
    設定を取得する（シングルトン + 環境変数オーバーレイ）

    ファイルから読み込んだベース設定に、`SATIN_` プレフィックス付き環境変数を
    重ねた実効設定を返す。オーバーレイは読み取り時のみ適用され、ファイルへは
    書き戻されない。

    Args:
        reload: Trueの場合、設定を再読み込みする

    Returns:
        Dict[str, Any]: 設定の辞書（環境変数オーバーレイ適用済み）
    """
    base = _ensure_loaded(reload)

    if apply_env_overrides is None:
        return base
    return apply_env_overrides(base)

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

    # 先にマージし、最終的な設定をバリデーションする。
    # （部分更新で version/settings を毎回渡さなくて済むよう、マージ後に検証する。
    #   以前は部分的な new_config を検証していたため必須フィールド欠落で常に失敗していた。）
    # ベース設定を使う（環境変数オーバーレイ込みの get_config() ではない）。
    # そうしないと実行時の環境変数値がファイルに永続化されてしまう。
    current_config = _ensure_loaded()
    merged_config = merge_configs(current_config, new_config)

    errors = validate_config(merged_config)
    if errors:
        logger.error("設定の更新に失敗しました。バリデーションエラーがあります:")
        for field, msgs in errors.items():
            for msg in msgs:
                logger.error(f"  - {field}: {msg}")
        return False

    _config_instance = merged_config

    # ファイルに保存
    if save_to_file:
        return save_config(_config_instance)

    return True
