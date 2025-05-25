"""
Environment variable handling for Satin configuration
"""
import os
import re
import logging
from typing import Dict, Any, Optional, List, Tuple, Type, TypeVar, Union
from pathlib import Path

logger = logging.getLogger(__name__)

T = TypeVar('T')

# Prefix for all Satin environment variables
ENV_PREFIX = 'SATIN_'

# Mapping of environment variables to config paths
ENV_MAPPING = {
    # Core
    'DEBUG': 'debug',
    'CONFIG_DIR': 'paths.config_dir',
    'DATA_DIR': 'paths.data_dir',
    'CACHE_DIR': 'paths.cache_dir',
    'LOG_DIR': 'paths.log_dir',
    'PLUGIN_DIR': 'paths.plugin_dir',
    'TEMP_DIR': 'paths.temp_dir',
    
    # Logging
    'LOG_LEVEL': 'logging.level',
    'LOG_FILE': 'logging.file',
    'LOG_MAX_SIZE': 'logging.max_size_mb',
    'LOG_BACKUP_COUNT': 'logging.backup_count',
    'LOG_ENABLE_CONSOLE': 'logging.enable_console',
    'LOG_ENABLE_FILE': 'logging.enable_file',
    
    # UI
    'UI_THEME': 'ui.theme',
    'UI_FONT_SIZE': 'ui.font_size',
    'UI_LANGUAGE': 'ui.language',
    'UI_SHOW_TOOLTIPS': 'ui.show_tooltips',
    'UI_ANIMATION_ENABLED': 'ui.animation_enabled',
    
    # Network
    'NETWORK_PROXY': 'network.proxy',
    'NETWORK_TIMEOUT': 'network.timeout',
    'NETWORK_RETRY_ATTEMPTS': 'network.retry_attempts',
    'NETWORK_VERIFY_SSL': 'network.verify_ssl',
}

def get_env_config(prefix: str = ENV_PREFIX) -> Dict[str, Any]:
    """
    Extract configuration from environment variables
    
    Args:
        prefix: Prefix for environment variables
        
    Returns:
        Dictionary with configuration from environment variables
    """
    config = {}
    
    for env_var, config_path in ENV_MAPPING.items():
        full_env_var = f"{prefix}{env_var}"
        if full_env_var in os.environ:
            value = os.environ[full_env_var]
            _set_nested(config, config_path, _parse_env_value(value))
    
    return config

def _parse_env_value(value: str) -> Any:
    """
    Parse environment variable value to appropriate Python type
    
    Args:
        value: Environment variable value as string
        
    Returns:
        Parsed value with appropriate type
    """
    # Handle boolean values
    if value.lower() in ('true', 'yes', '1'):
        return True
    if value.lower() in ('false', 'no', '0'):
        return False
    
    # Handle numeric values
    if value.isdigit():
        return int(value)
    try:
        return float(value)
    except ValueError:
        pass
    
    # Handle lists (comma-separated)
    if ',' in value:
        return [_parse_env_item(v.strip()) for v in value.split(',')]
    
    # Handle JSON-like values
    if value.startswith(('{', '[', '"')):
        try:
            import json
            return json.loads(value)
        except json.JSONDecodeError:
            pass
    
    # Return as string
    return value

def _parse_env_item(value: str) -> Any:
    """Parse a single environment variable value item"""
    value = value.strip()
    
    # Handle quoted strings
    if (value.startswith('"') and value.endswith('"')) or \
       (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    
    # Handle boolean and numeric values
    return _parse_env_value(value)

def _set_nested(config: Dict[str, Any], path: str, value: Any) -> None:
    """
    Set a nested configuration value using dot notation
    
    Args:
        config: Configuration dictionary to update
        path: Dot-separated path to the configuration value
        value: Value to set
    """
    keys = path.split('.')
    current = config
    
    for key in keys[:-1]:
        if key not in current:
            current[key] = {}
        current = current[key]
    
    current[keys[-1]] = value

def apply_env_overrides(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply environment variable overrides to configuration
    
    Args:
        config: Base configuration
        
    Returns:
        Updated configuration with environment overrides
    """
    env_config = get_env_config()
    return _deep_merge(config, env_config)

def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deep merge two dictionaries
    
    Args:
        base: Base dictionary
        override: Dictionary with override values
        
    Returns:
        Merged dictionary
    """
    result = base.copy()
    
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
            
    return result

def get_env_bool(key: str, default: bool = False) -> bool:
    """Get a boolean value from environment variables"""
    value = os.environ.get(key, '').lower()
    return value in ('true', 'yes', '1') if value else default

def get_env_int(key: str, default: int = 0) -> int:
    """Get an integer value from environment variables"""
    try:
        return int(os.environ.get(key, str(default)))
    except (ValueError, TypeError):
        return default

def get_env_float(key: str, default: float = 0.0) -> float:
    """Get a float value from environment variables"""
    try:
        return float(os.environ.get(key, str(default)))
    except (ValueError, TypeError):
        return default

def get_env_str(key: str, default: str = '') -> str:
    """Get a string value from environment variables"""
    return os.environ.get(key, default)

def get_env_list(key: str, delimiter: str = ',', default: Optional[list] = None) -> list:
    """
    Get a list from environment variables
    
    Args:
        key: Environment variable name
        delimiter: Delimiter to split the string
        default: Default value if key is not found
        
    Returns:
        List of values
    """
    if default is None:
        default = []
        
    value = os.environ.get(key, '')
    if not value:
        return default
        
    return [item.strip() for item in value.split(delimiter) if item.strip()]
