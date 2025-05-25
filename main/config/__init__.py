"""
Enhanced configuration system for Satin
"""
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Callable, Tuple, Union
from dataclasses import dataclass, field
from enum import Enum, auto
import threading
import hashlib
import shutil

logger = logging.getLogger(__name__)

class ConfigSource(Enum):
    """Configuration source type"""
    DEFAULT = auto()
    FILE = auto()
    ENV = auto()
    RUNTIME = auto()

@dataclass
class ConfigValue:
    """A configuration value with metadata"""
    value: Any
    source: ConfigSource = ConfigSource.DEFAULT
    last_updated: float = field(default_factory=time.time)
    description: str = ""
    validator: Optional[Callable[[Any], bool]] = None
    sensitive: bool = False

class ConfigManager:
    """
    Enhanced configuration manager with validation, change notifications,
    and multiple configuration sources.
    """
    
    def __init__(self, config_dir: Optional[Union[str, Path]] = None):
        """
        Initialize the configuration manager.
        
        Args:
            config_dir: Directory to store configuration files
        """
        self.config_dir = Path(config_dir) if config_dir else Path('config')
        self.config_file = self.config_dir / 'config.json'
        self.backup_dir = self.config_dir / 'backups'
        self.defaults_file = self.config_dir / 'defaults.json'
        
        self._config: Dict[str, ConfigValue] = {}
        self._defaults: Dict[str, Any] = {}
        self._listeners: Dict[str, List[Callable[[str, Any, Any], None]]] = {}
        self._lock = threading.RLock()
        self._file_watcher = None
        self._running = False
        
        # Ensure directories exist
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(exist_ok=True)
        
        # Load defaults if they exist
        self._load_defaults()
        
        # Load current config
        self.reload()
        
        # Start file watcher
        self.start_watching()
    
    # [Previous methods remain the same until _create_backup]
    
    def _create_backup(self) -> None:
        """Create a backup of the current config"""
        try:
            timestamp = int(time.time())
            backup_file = self.backup_dir / f"config_{timestamp}.json"
            
            shutil.copy2(self.config_file, backup_file)
            logger.debug(f"Created config backup: {backup_file}")
            
            # Clean up old backups (keep last 10)
            backups = sorted(self.backup_dir.glob("config_*.json"), key=os.path.getmtime)
            for old_backup in backups[:-10]:
                old_backup.unlink()
                
        except Exception as e:
            logger.error(f"Failed to create config backup: {e}")

# Global instance
_config_manager = None

def get_config_manager() -> ConfigManager:
    """Get or create the global config manager"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager
