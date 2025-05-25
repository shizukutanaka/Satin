"""
Configuration utilities for Satin
"""
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional, TypeVar, Type, Union
import shutil
from datetime import datetime

logger = logging.getLogger(__name__)

T = TypeVar('T')

def ensure_config_dirs(config_path: Union[str, Path]) -> Path:
    """
    Ensure configuration directories exist
    
    Args:
        config_path: Path to the configuration file
        
    Returns:
        Path: Absolute path to the config file
    """
    config_path = Path(config_path).expanduser().absolute()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Create backup directory
    backup_dir = config_path.parent / 'backups'
    backup_dir.mkdir(exist_ok=True)
    
    return config_path

def load_config_file(
    config_path: Union[str, Path],
    config_class: Optional[Type[T]] = None,
    create_default: bool = True
) -> Dict[str, Any]:
    """
    Load configuration from a JSON file
    
    Args:
        config_path: Path to the configuration file
        config_class: Optional model class to validate against
        create_default: Whether to create a default config if it doesn't exist
        
    Returns:
        Dictionary containing the configuration
    """
    config_path = Path(config_path).expanduser().absolute()
    
    # Create default config if it doesn't exist
    if not config_path.exists():
        if create_default and config_class is not None:
            default_config = config_class().dict()
            save_config_file(config_path, default_config)
            return default_config
        return {}
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
            
        # Validate against schema if provided
        if config_class is not None:
            return config_class(**config).dict()
            
        return config
        
    except Exception as e:
        logger.error(f"Error loading config from {config_path}: {e}")
        if create_default and config_class is not None:
            return config_class().dict()
        return {}

def save_config_file(
    config_path: Union[str, Path],
    config: Dict[str, Any],
    create_backup: bool = True
) -> bool:
    """
    Save configuration to a file
    
    Args:
        config_path: Path to save the configuration
        config: Configuration dictionary
        create_backup: Whether to create a backup of existing config
        
    Returns:
        bool: True if successful, False otherwise
    """
    config_path = Path(config_path).expanduser().absolute()
    
    try:
        # Create backup if requested and file exists
        if create_backup and config_path.exists():
            backup_dir = config_path.parent / 'backups'
            backup_dir.mkdir(exist_ok=True)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = backup_dir / f"{config_path.stem}_{timestamp}{config_path.suffix}"
            
            shutil.copy2(config_path, backup_file)
            
            # Clean up old backups (keep last 5)
            backups = sorted(backup_dir.glob(f"{config_path.stem}_*{config_path.suffix}"))
            for old_backup in backups[:-5]:
                old_backup.unlink()
        
        # Write to temporary file first
        temp_file = f"{config_path}.tmp"
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        
        # Atomic replace
        if os.name == 'nt':  # Windows
            # On Windows, we need to remove the destination first
            if config_path.exists():
                os.unlink(config_path)
            os.rename(temp_file, config_path)
        else:  # Unix-like
            os.replace(temp_file, config_path)
            
        return True
        
    except Exception as e:
        logger.error(f"Error saving config to {config_path}: {e}")
        # Clean up temp file if it exists
        if 'temp_file' in locals() and os.path.exists(temp_file):
            os.unlink(temp_file)
        return False

def merge_configs(
    base_config: Dict[str, Any], 
    override_config: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Recursively merge two configuration dictionaries
    
    Args:
        base_config: Base configuration
        override_config: Configuration with override values
        
    Returns:
        Merged configuration
    """
    result = base_config.copy()
    
    for key, value in override_config.items():
        if (key in result and isinstance(result[key], dict) 
                and isinstance(value, dict)):
            result[key] = merge_configs(result[key], value)
        else:
            result[key] = value
            
    return result

def get_config_value(
    config: Dict[str, Any], 
    key_path: str, 
    default: Any = None,
    delimiter: str = '.'
) -> Any:
    """
    Get a nested configuration value using dot notation
    
    Args:
        config: Configuration dictionary
        key_path: Dot-separated path to the configuration value
        default: Default value if key is not found
        delimiter: Delimiter for key path
        
    Returns:
        The configuration value or default if not found
    """
    keys = key_path.split(delimiter)
    value = config
    
    try:
        for key in keys:
            if isinstance(value, dict):
                value = value[key]
            else:
                return default
        return value
    except (KeyError, TypeError):
        return default

def set_config_value(
    config: Dict[str, Any], 
    key_path: str, 
    value: Any,
    delimiter: str = '.'
) -> Dict[str, Any]:
    """
    Set a nested configuration value using dot notation
    
    Args:
        config: Configuration dictionary to update
        key_path: Dot-separated path to the configuration value
        value: Value to set
        delimiter: Delimiter for key path
        
    Returns:
        Updated configuration dictionary
    """
    keys = key_path.split(delimiter)
    current = config
    
    for i, key in enumerate(keys[:-1]):
        if key not in current or not isinstance(current[key], dict):
            current[key] = {}
        current = current[key]
    
    current[keys[-1]] = value
    return config
