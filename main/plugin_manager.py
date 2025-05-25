import os
import importlib
from typing import Dict, Any, List, Type
from pathlib import Path
from .error_handling import PluginError
from .logging_manager import Logger

class PluginManager:
    """Manage and load plugins"""
    
    def __init__(self, logger: Logger):
        """Initialize plugin manager"""
        self.logger = logger
        self.plugins: Dict[str, Any] = {}
        self.plugin_config: Dict[str, Any] = {}
        self.plugin_directory = Path("plugins")
        
    def load_plugins(self) -> None:
        """Load all available plugins"""
        try:
            if not self.plugin_directory.exists():
                raise PluginError(f"Plugin directory not found: {self.plugin_directory}")
                
            # Load plugin configuration
            self._load_plugin_config()
            
            # Load each plugin
            for plugin_file in self.plugin_directory.glob("*.py"):
                self._load_plugin(plugin_file)
                
            self.logger.info(f"Loaded {len(self.plugins)} plugins")
            
        except Exception as e:
            self.logger.error(f"Error loading plugins: {str(e)}")
            raise PluginError(f"Failed to load plugins: {str(e)}")
    
    def _load_plugin_config(self) -> None:
        """Load plugin configuration"""
        try:
            config_file = self.plugin_directory / "config.json"
            if config_file.exists():
                with open(config_file, 'r', encoding='utf-8') as f:
                    self.plugin_config = json.load(f)
            else:
                self.logger.warning("No plugin configuration found")
                self.plugin_config = {}
                
        except Exception as e:
            self.logger.error(f"Error loading plugin config: {str(e)}")
            raise PluginError(f"Failed to load plugin configuration: {str(e)}")
    
    def _load_plugin(self, plugin_file: Path) -> None:
        """Load a single plugin"""
        try:
            # Get plugin name from filename
            plugin_name = plugin_file.stem
            
            # Skip __init__.py
            if plugin_name == "__init__":
                return
                
            # Import plugin module
            spec = importlib.util.spec_from_file_location(plugin_name, plugin_file)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            # Find plugin classes
            plugin_class = None
            for name, obj in module.__dict__.items():
                if isinstance(obj, type) and issubclass(obj, PluginBase):
                    plugin_class = obj
                    break
            
            if plugin_class:
                # Create plugin instance
                plugin = plugin_class()
                self.plugins[plugin_name] = plugin
                
                # Configure plugin if needed
                plugin_config = self.plugin_config.get(plugin_name, {})
                plugin.configure(plugin_config)
                
                self.logger.info(f"Loaded plugin: {plugin_name}")
            else:
                self.logger.warning(f"No plugin class found in {plugin_name}")
                
        except Exception as e:
            self.logger.error(f"Error loading plugin {plugin_name}: {str(e)}")
            raise PluginError(f"Failed to load plugin {plugin_name}: {str(e)}")
    
    def get_plugin(self, name: str) -> Any:
        """Get a plugin by name"""
        if name not in self.plugins:
            raise PluginError(f"Plugin not found: {name}")
        return self.plugins[name]
    
    def get_all_plugins(self) -> Dict[str, Any]:
        """Get all loaded plugins"""
        return self.plugins.copy()
    
    def reload_plugin(self, name: str) -> None:
        """Reload a specific plugin"""
        try:
            if name not in self.plugins:
                raise PluginError(f"Plugin not found: {name}")
                
            plugin = self.plugins[name]
            plugin_file = self.plugin_directory / f"{name}.py"
            self._load_plugin(plugin_file)
            
            self.logger.info(f"Reloaded plugin: {name}")
            
        except Exception as e:
            self.logger.error(f"Error reloading plugin {name}: {str(e)}")
            raise PluginError(f"Failed to reload plugin {name}: {str(e)}")
    
    def reload_all_plugins(self) -> None:
        """Reload all plugins"""
        try:
            self.plugins.clear()
            self.load_plugins()
            self.logger.info("Reloaded all plugins")
            
        except Exception as e:
            self.logger.error(f"Error reloading all plugins: {str(e)}")
            raise PluginError(f"Failed to reload all plugins: {str(e)}")
