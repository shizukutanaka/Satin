"""
Plugin System Demo for Satin
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from plugin_system import get_plugin_manager

def main():
    # Initialize plugin manager
    plugin_manager = get_plugin_manager(['plugins'])
    
    # Discover available plugins
    print("Discovering plugins...")
    plugins = plugin_manager.discover_plugins()
    print(f"Found plugins: {plugins}")
    
    # Load and use a sample plugin
    if plugins:
        print("\nLoading sample plugin...")
        if plugin_manager.load_plugin(plugins[0]):
            print("Plugin loaded successfully!")
            
            # Get the plugin instance
            plugin = plugin_manager.get_plugin(plugins[0])
            if plugin:
                # Call a method on the plugin
                print(plugin.hello("Satin User"))
            
            # Unload the plugin
            print("\nUnloading plugin...")
            if plugin_manager.unload_plugin(plugins[0]):
                print("Plugin unloaded successfully!")
    else:
        print("No plugins found. Please create a plugin in the 'plugins' directory.")

if __name__ == "__main__":
    main()
