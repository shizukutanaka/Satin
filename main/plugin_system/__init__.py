"""
Lightweight plugin system for Satin
"""
import importlib
import inspect
from pathlib import Path
from typing import Dict, List, Type, Optional, Any
import sys

class PluginInfo:
    def __init__(self, name: str, version: str = "1.0.0"):
        self.name = name
        self.version = version
        self.enabled = True

class BasePlugin:
    PLUGIN_INFO = PluginInfo("unnamed_plugin")
    
    def on_load(self) -> None:
        pass
    
    def on_enable(self) -> None:
        pass
    
    def on_disable(self) -> None:
        pass

class PluginManager:
    def __init__(self, plugin_dirs: List[str]):
        self.plugin_dirs = [Path(d) for d in plugin_dirs]
        self.plugins: Dict[str, BasePlugin] = {}
        self.modules = {}
    
    def discover_plugins(self) -> List[str]:
        """Find all Python files in plugin directories"""
        plugins = []
        for d in self.plugin_dirs:
            for f in d.glob('**/*.py'):
                if f.name.startswith('_'):
                    continue
                rel = f.relative_to(d).with_suffix('')
                plugins.append(str(rel).replace('\\', '.'))
        return plugins
    
    def load_plugin(self, name: str) -> bool:
        """Load a single plugin"""
        if name in self.plugins:
            return True
            
        try:
            # Import the module
            if name in sys.modules:
                module = importlib.reload(sys.modules[name])
            else:
                module = importlib.import_module(name)
            
            # Find plugin class
            for _, obj in inspect.getmembers(module, inspect.isclass):
                if (issubclass(obj, BasePlugin) and 
                    obj != BasePlugin and 
                    obj.__module__ == module.__name__):
                    
                    # Create and initialize plugin
                    plugin = obj()
                    plugin.on_load()
                    if plugin.PLUGIN_INFO.enabled:
                        plugin.on_enable()
                    
                    self.plugins[name] = plugin
                    self.modules[name] = module
                    return True
            
            return False
            
        except Exception as e:
            print(f"Error loading plugin {name}: {e}")
            return False
    
    def unload_plugin(self, name: str) -> bool:
        """Unload a plugin"""
        if name not in self.plugins:
            return False
            
        try:
            plugin = self.plugins[name]
            plugin.on_disable()
            del self.plugins[name]
            
            # Remove from sys.modules
            if name in sys.modules:
                del sys.modules[name]
            
            return True
            
        except Exception as e:
            print(f"Error unloading plugin {name}: {e}")
            return False
    
    def get_plugin(self, name: str) -> Optional[BasePlugin]:
        """Get a loaded plugin"""
        return self.plugins.get(name)

# Global instance
_plugin_manager = None

def get_plugin_manager(plugin_dirs=None):
    global _plugin_manager
    if _plugin_manager is None:
        if plugin_dirs is None:
            plugin_dirs = ['plugins']
        _plugin_manager = PluginManager(plugin_dirs)
    return _plugin_manager
