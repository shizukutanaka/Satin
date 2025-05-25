"""
Plugin configuration management for Satin
"""
import os
import importlib
import inspect
import logging
import pkgutil
from pathlib import Path
from typing import Dict, List, Optional, Type, TypeVar, Any, Tuple, Union
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
import json

logger = logging.getLogger(__name__)

T = TypeVar('T')

class PluginType(Enum):
    """Types of plugins"""
    CORE = auto()
    EXTENSION = auto()
    THEME = auto()
    INTEGRATION = auto()
    CUSTOM = auto()

class PluginStatus(Enum):
    """Plugin status"""
    LOADED = "loaded"
    ENABLED = "enabled"
    DISABLED = "disabled"
    ERROR = "error"
    LOADING = "loading"
    UNLOADED = "unloaded"

@dataclass
class PluginDependency:
    """Plugin dependency information"""
    name: str
    version: str
    optional: bool = False

@dataclass
class PluginMetadata:
    """Plugin metadata"""
    name: str
    version: str
    description: str = ""
    author: str = ""
    url: str = ""
    license: str = ""
    type: PluginType = PluginType.EXTENSION
    dependencies: List[PluginDependency] = field(default_factory=list)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PluginMetadata':
        """Create PluginMetadata from dictionary"""
        if 'dependencies' in data:
            deps = []
            for dep in data['dependencies']:
                if isinstance(dep, dict):
                    deps.append(PluginDependency(**dep))
                elif isinstance(dep, (list, tuple)) and len(dep) >= 2:
                    deps.append(PluginDependency(
                        name=dep[0],
                        version=dep[1],
                        optional=dep[2] if len(dep) > 2 else False
                    ))
            data['dependencies'] = deps
        
        if 'type' in data and isinstance(data['type'], str):
            data['type'] = PluginType[data['type'].upper()]
            
        return cls(**data)

@dataclass
class PluginConfig:
    """Plugin configuration"""
    enabled: bool = False
    settings: Dict[str, Any] = field(default_factory=dict)
    metadata: Optional[PluginMetadata] = None
    status: PluginStatus = PluginStatus.UNLOADED
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        data = asdict(self)
        if 'metadata' in data and data['metadata'] is not None:
            data['metadata'] = asdict(data['metadata'])
        if 'status' in data and isinstance(data['status'], PluginStatus):
            data['status'] = data['status'].value
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PluginConfig':
        """Create PluginConfig from dictionary"""
        if 'metadata' in data and data['metadata'] is not None:
            data['metadata'] = PluginMetadata.from_dict(data['metadata'])
        if 'status' in data and isinstance(data['status'], str):
            data['status'] = PluginStatus(data['status'].lower())
        return cls(**data)

class PluginManager:
    """Manages loading and configuration of plugins"""
    
    def __init__(self, plugin_dirs: Optional[List[Union[str, Path]]] = None):
        """
        Initialize plugin manager
        
        Args:
            plugin_dirs: List of directories to search for plugins
        """
        self.plugin_dirs = [Path(d) for d in (plugin_dirs or [])]
        self.plugins: Dict[str, PluginConfig] = {}
        self._loaded_plugins: Dict[str, Any] = {}
        self._discovered_plugins: Dict[str, Dict[str, Any]] = {}
    
    def discover_plugins(self) -> Dict[str, Dict[str, Any]]:
        """
        Discover available plugins in plugin directories
        
        Returns:
            Dictionary of discovered plugins with their metadata
        """
        self._discovered_plugins = {}
        
        for plugin_dir in self.plugin_dirs:
            if not plugin_dir.exists():
                logger.debug(f"Plugin directory not found: {plugin_dir}")
                continue
                
            for entry in plugin_dir.iterdir():
                if entry.is_dir() and (entry / "__init__.py").exists():
                    self._discover_plugin(entry)
                elif entry.suffix == '.py' and entry.stem != '__init__':
                    self._discover_plugin(entry)
        
        return self._discovered_plugins
    
    def _discover_plugin(self, plugin_path: Path) -> Optional[Dict[str, Any]]:
        """Discover a single plugin"""
        try:
            # Determine module name
            if plugin_path.is_dir():
                module_name = plugin_path.name
                module_path = f"{plugin_path.parent.name}.{module_name}" if plugin_path.parent.name else module_name
            else:
                module_name = plugin_path.stem
                module_path = f"{plugin_path.parent.name}.{module_name}" if plugin_path.parent.name else module_name
            
            # Skip already discovered plugins
            if module_name in self._discovered_plugins:
                return self._discovered_plugins[module_name]
            
            # Try to import the module
            try:
                if plugin_path.is_dir():
                    spec = importlib.util.spec_from_file_location(
                        module_path, 
                        plugin_path / "__init__.py"
                    )
                else:
                    spec = importlib.util.spec_from_file_location(
                        module_path, 
                        plugin_path
                    )
                
                if spec is None or spec.loader is None:
                    logger.warning(f"Could not load plugin {module_name}: No module spec found")
                    return None
                
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                
                # Look for plugin metadata
                metadata = self._extract_metadata(module, module_name)
                if not metadata:
                    logger.warning(f"No valid metadata found in plugin {module_name}")
                    return None
                
                # Store plugin info
                plugin_info = {
                    'name': module_name,
                    'module': module,
                    'path': str(plugin_path),
                    'metadata': metadata,
                    'status': PluginStatus.UNLOADED,
                    'error': None
                }
                
                self._discovered_plugins[module_name] = plugin_info
                return plugin_info
                
            except Exception as e:
                logger.error(f"Error discovering plugin {module_name}: {e}", exc_info=True)
                return None
                
        except Exception as e:
            logger.error(f"Unexpected error discovering plugin {plugin_path}: {e}", exc_info=True)
            return None
    
    def _extract_metadata(self, module: Any, module_name: str) -> Optional[PluginMetadata]:
        """Extract plugin metadata from module"""
        # Check for PLUGIN_METADATA attribute
        if hasattr(module, 'PLUGIN_METADATA'):
            metadata = module.PLUGIN_METADATA
            if isinstance(metadata, dict):
                return PluginMetadata.from_dict(metadata)
        
        # Try to get from docstring
        if module.__doc__:
            return PluginMetadata(
                name=module_name,
                version="0.1.0",
                description=module.__doc__.strip()
            )
            
        return None
    
    def load_plugin(self, plugin_name: str, config: Optional[Dict[str, Any]] = None) -> bool:
        """
        Load a plugin
        
        Args:
            plugin_name: Name of the plugin to load
            config: Optional configuration for the plugin
            
        Returns:
            bool: True if the plugin was loaded successfully
        """
        if plugin_name not in self._discovered_plugins:
            logger.error(f"Plugin {plugin_name} not found")
            return False
            
        plugin_info = self._discovered_plugins[plugin_name]
        
        try:
            # Initialize plugin config
            plugin_config = PluginConfig.from_dict(config or {})
            plugin_config.metadata = plugin_info['metadata']
            plugin_config.status = PluginStatus.LOADING
            
            # Check dependencies
            if not self._check_dependencies(plugin_config.metadata.dependencies):
                plugin_config.status = PluginStatus.ERROR
                plugin_config.error = "Dependency check failed"
                return False
            
            # Initialize the plugin
            if hasattr(plugin_info['module'], 'setup_plugin'):
                plugin_instance = plugin_info['module'].setup_plugin()
                if plugin_instance is not None:
                    self._loaded_plugins[plugin_name] = plugin_instance
                    plugin_config.status = PluginStatus.LOADED
                    
                    # Enable if configured to do so
                    if plugin_config.enabled:
                        return self.enable_plugin(plugin_name)
                    
                    return True
            
            # If no setup_plugin function, just mark as loaded
            plugin_config.status = PluginStatus.LOADED
            return True
            
        except Exception as e:
            logger.error(f"Error loading plugin {plugin_name}: {e}", exc_info=True)
            plugin_config.status = PluginStatus.ERROR
            plugin_config.error = str(e)
            return False
    
    def enable_plugin(self, plugin_name: str) -> bool:
        """
        Enable a loaded plugin
        
        Args:
            plugin_name: Name of the plugin to enable
            
        Returns:
            bool: True if the plugin was enabled successfully
        """
        if plugin_name not in self._loaded_plugins:
            logger.error(f"Plugin {plugin_name} is not loaded")
            return False
            
        plugin_info = self._discovered_plugins.get(plugin_name, {})
        plugin_config = self.plugins.get(plugin_name, PluginConfig())
        
        try:
            # Call plugin's enable method if it exists
            plugin_instance = self._loaded_plugins[plugin_name]
            if hasattr(plugin_instance, 'enable'):
                if not plugin_instance.enable():
                    logger.error(f"Plugin {plugin_name} failed to enable")
                    return False
            
            plugin_config.status = PluginStatus.ENABLED
            plugin_config.enabled = True
            self.plugins[plugin_name] = plugin_config
            logger.info(f"Enabled plugin: {plugin_name}")
            return True
            
        except Exception as e:
            logger.error(f"Error enabling plugin {plugin_name}: {e}", exc_info=True)
            plugin_config.status = PluginStatus.ERROR
            plugin_config.error = str(e)
            return False
    
    def disable_plugin(self, plugin_name: str) -> bool:
        """
        Disable a plugin
        
        Args:
            plugin_name: Name of the plugin to disable
            
        Returns:
            bool: True if the plugin was disabled successfully
        """
        if plugin_name not in self._loaded_plugins:
            logger.warning(f"Plugin {plugin_name} is not loaded")
            return False
            
        plugin_instance = self._loaded_plugins[plugin_name]
        plugin_config = self.plugins.get(plugin_name, PluginConfig())
        
        try:
            # Call plugin's disable method if it exists
            if hasattr(plugin_instance, 'disable'):
                plugin_instance.disable()
            
            plugin_config.status = PluginStatus.LOADED
            plugin_config.enabled = False
            self.plugins[plugin_name] = plugin_config
            logger.info(f"Disabled plugin: {plugin_name}")
            return True
            
        except Exception as e:
            logger.error(f"Error disabling plugin {plugin_name}: {e}", exc_info=True)
            plugin_config.status = PluginStatus.ERROR
            plugin_config.error = str(e)
            return False
    
    def unload_plugin(self, plugin_name: str) -> bool:
        """
        Unload a plugin
        
        Args:
            plugin_name: Name of the plugin to unload
            
        Returns:
            bool: True if the plugin was unloaded successfully
        """
        if plugin_name not in self._loaded_plugins:
            return True  # Already unloaded
            
        # Disable first if enabled
        if plugin_name in self.plugins and self.plugins[plugin_name].enabled:
            self.disable_plugin(plugin_name)
        
        # Remove from loaded plugins
        del self._loaded_plugins[plugin_name]
        
        # Update status
        if plugin_name in self.plugins:
            self.plugins[plugin_name].status = PluginStatus.UNLOADED
        
        logger.info(f"Unloaded plugin: {plugin_name}")
        return True
    
    def get_plugin(self, plugin_name: str) -> Optional[Any]:
        """
        Get a loaded plugin instance
        
        Args:
            plugin_name: Name of the plugin
            
        Returns:
            The plugin instance or None if not found
        """
        return self._loaded_plugins.get(plugin_name)
    
    def get_plugin_config(self, plugin_name: str) -> Optional[PluginConfig]:
        """
        Get plugin configuration
        
        Args:
            plugin_name: Name of the plugin
            
        Returns:
            PluginConfig or None if not found
        """
        return self.plugins.get(plugin_name)
    
    def update_plugin_config(self, plugin_name: str, config: Dict[str, Any]) -> bool:
        """
        Update plugin configuration
        
        Args:
            plugin_name: Name of the plugin
            config: New configuration values
            
        Returns:
            bool: True if the configuration was updated successfully
        """
        if plugin_name not in self.plugins:
            return False
            
        current_config = self.plugins[plugin_name].to_dict()
        current_config.update(config)
        
        # Handle special fields
        if 'enabled' in config:
            if config['enabled'] and not self.plugins[plugin_name].enabled:
                return self.enable_plugin(plugin_name)
            elif not config['enabled'] and self.plugins[plugin_name].enabled:
                return self.disable_plugin(plugin_name)
        
        self.plugins[plugin_name] = PluginConfig.from_dict(current_config)
        return True
    
    def _check_dependencies(self, dependencies: List[PluginDependency]) -> bool:
        """
        Check if all plugin dependencies are satisfied
        
        Args:
            dependencies: List of dependencies to check
            
        Returns:
            bool: True if all dependencies are satisfied
        """
        for dep in dependencies:
            if dep.name not in self._loaded_plugins:
                if not dep.optional:
                    logger.error(f"Missing required dependency: {dep.name}")
                    return False
                else:
                    logger.warning(f"Missing optional dependency: {dep.name}")
            
            # TODO: Add version checking
            
        return True
    
    def get_loaded_plugins(self) -> Dict[str, Any]:
        """
        Get all loaded plugins
        
        Returns:
            Dictionary of loaded plugins
        """
        return self._loaded_plugins.copy()
    
    def get_available_plugins(self) -> Dict[str, Dict[str, Any]]:
        """
        Get all available plugins
        
        Returns:
            Dictionary of available plugins
        """
        return self._discovered_plugins.copy()
    
    def shutdown(self) -> None:
        """Shutdown all plugins and cleanup"""
        # Disable and unload all plugins
        for plugin_name in list(self._loaded_plugins.keys()):
            try:
                self.disable_plugin(plugin_name)
                self.unload_plugin(plugin_name)
            except Exception as e:
                logger.error(f"Error during shutdown of plugin {plugin_name}: {e}", exc_info=True)
        
        self._loaded_plugins.clear()
        self.plugins.clear()
        self._discovered_plugins.clear()

# Global plugin manager instance
_plugin_manager = None

def get_plugin_manager(plugin_dirs: Optional[List[Union[str, Path]]] = None) -> 'PluginManager':
    """
    Get or create the global plugin manager
    
    Args:
        plugin_dirs: Optional list of plugin directories to initialize with
        
    Returns:
        PluginManager instance
    """
    global _plugin_manager
    if _plugin_manager is None:
        _plugin_manager = PluginManager(plugin_dirs)
        _plugin_manager.discover_plugins()
    return _plugin_manager
