"""
Sample plugin for Satin
"""
from plugin_system import BasePlugin, PluginInfo

class SamplePlugin(BasePlugin):
    """A sample plugin that demonstrates plugin functionality"""
    
    # Plugin metadata
    PLUGIN_INFO = PluginInfo(
        name="sample_plugin",
        version="1.0.0",
    )
    
    def on_load(self):
        """Called when the plugin is loaded"""
        print("SamplePlugin: Loaded!")
    
    def on_enable(self):
        """Called when the plugin is enabled"""
        print("SamplePlugin: Enabled!")
    
    def on_disable(self):
        """Called when the plugin is disabled"""
        print("SamplePlugin: Disabled!")
    
    def hello(self, name: str = "World") -> str:
        """A sample method that can be called from other components"""
        return f"Hello, {name}! This is a sample plugin."
