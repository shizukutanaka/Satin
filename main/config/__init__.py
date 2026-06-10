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
    
    def _load_defaults(self) -> None:
        """Load default configuration values from defaults.json"""
        try:
            if self.defaults_file.exists():
                with open(self.defaults_file, 'r', encoding='utf-8') as f:
                    defaults = json.load(f)
                self._defaults.update(defaults)
                logger.debug(f"Loaded {len(defaults)} defaults from {self.defaults_file}")
        except Exception as e:
            logger.warning(f"Failed to load defaults: {e}")

    def reload(self) -> None:
        """Reload configuration from disk"""
        with self._lock:
            if not self.config_file.exists():
                for key, value in self._defaults.items():
                    self._config.setdefault(key, ConfigValue(value=value, source=ConfigSource.DEFAULT))
                return
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for key, value in data.items():
                    old_cv = self._config.get(key)
                    self._config[key] = ConfigValue(value=value, source=ConfigSource.FILE)
                    if old_cv is not None and old_cv.value != value:
                        self._notify_listeners(key, old_cv.value, value)
                logger.debug(f"Loaded configuration from {self.config_file}")
            except Exception as e:
                logger.error(f"Failed to reload config: {e}")

    def start_watching(self) -> None:
        """Start background thread that reloads config when file changes"""
        if self._running:
            return
        self._running = True
        self._file_watcher = threading.Thread(target=self._watch_file, daemon=True)
        self._file_watcher.start()

    def _watch_file(self) -> None:
        """Reload config when mtime changes (runs in background daemon thread)"""
        last_mtime: Optional[float] = None
        while self._running:
            try:
                if self.config_file.exists():
                    mtime = self.config_file.stat().st_mtime
                    if last_mtime is not None and mtime != last_mtime:
                        logger.info("Config file changed, reloading...")
                        self.reload()
                    last_mtime = mtime
            except Exception as e:
                logger.error(f"File watcher error: {e}")
            time.sleep(1.0)

    def _notify_listeners(self, key: str, old_value: Any, new_value: Any) -> None:
        """Notify registered listeners of a config change"""
        for cb in self._listeners.get(key, []) + self._listeners.get('*', []):
            try:
                cb(key, old_value, new_value)
            except Exception as e:
                logger.error(f"Config listener error for key '{key}': {e}")

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
