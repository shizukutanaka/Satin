"""
Configuration schema and validation for Satin
"""
from typing import Dict, Any, List, Optional, Union
from enum import Enum
from pydantic import BaseModel, Field, validator, root_validator
from pathlib import Path

# Enums for configuration options
class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

class ThemeMode(str, Enum):
    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"

# Sub-models
class LoggingConfig(BaseModel):
    """Logging configuration"""
    level: LogLevel = LogLevel.INFO
    file: Optional[Path] = None
    max_size_mb: int = Field(10, ge=1, le=100)
    backup_count: int = Field(5, ge=0, le=50)
    enable_console: bool = True
    enable_file: bool = False

class UIConfig(BaseModel):
    """UI configuration"""
    theme: ThemeMode = ThemeMode.SYSTEM
    font_size: int = Field(14, ge=8, le=32)
    language: str = "en"
    show_tooltips: bool = True
    animation_enabled: bool = True

class NetworkConfig(BaseModel):
    """Network configuration"""
    proxy: Optional[str] = None
    timeout: int = Field(30, ge=5, le=300)
    retry_attempts: int = Field(3, ge=0, le=10)
    verify_ssl: bool = True

class PluginConfig(BaseModel):
    """Plugin configuration"""
    enabled: bool = True
    settings: Dict[str, Any] = {}

class PathsConfig(BaseModel):
    """Path configuration"""
    data_dir: Path = Path("data")
    cache_dir: Path = Path("cache")
    log_dir: Path = Path("logs")
    plugin_dir: Path = Path("plugins")
    temp_dir: Path = Path("temp")

# Main configuration model
class SatinConfig(BaseModel):
    """Main configuration model"""
    version: str = "1.0.0"
    debug: bool = False
    logging: LoggingConfig = LoggingConfig()
    ui: UIConfig = UIConfig()
    network: NetworkConfig = NetworkConfig()
    plugins: Dict[str, PluginConfig] = {}
    paths: PathsConfig = PathsConfig()
    
    class Config:
        json_encoders = {
            Path: lambda v: str(v)
        }
    
    @validator('version')
    def validate_version(cls, v):
        """Validate version format"""
        from packaging import version
        try:
            version.parse(v)
            return v
        except version.InvalidVersion:
            raise ValueError(f"Invalid version format: {v}")
    
    @root_validator
    def validate_paths(cls, values):
        """Ensure paths are absolute"""
        paths = values.get('paths', {})
        for field in paths.__fields__:
            path = getattr(paths, field)
            if path and not path.is_absolute():
                setattr(paths, field, Path.cwd() / path)
        return values

def create_default_config() -> Dict[str, Any]:
    """Create a default configuration dictionary"""
    return SatinConfig().dict()

def validate_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate configuration against schema
    
    Args:
        config: Configuration dictionary to validate
        
    Returns:
        Validated configuration
        
    Raises:
        ValueError: If configuration is invalid
    """
    try:
        return SatinConfig(**config).dict()
    except Exception as e:
        raise ValueError(f"Configuration validation failed: {e}") from e

def upgrade_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Upgrade configuration from older versions
    
    Args:
        config: Current configuration
        
    Returns:
        Upgraded configuration
    """
    # Get current version or assume oldest
    current_version = config.get('version', '0.1.0')
    
    # Create a copy to modify
    upgraded = config.copy()
    
    # Version-specific upgrade paths
    if current_version == '0.1.0':
        # Add new fields introduced in 1.0.0
        if 'ui' not in upgraded:
            upgraded['ui'] = {}
        if 'theme' not in upgraded.get('ui', {}):
            upgraded['ui']['theme'] = 'system'
        upgraded['version'] = '1.0.0'
    
    return upgraded
