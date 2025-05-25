from typing import Dict, Any
from abc import ABC, abstractmethod
from .error_handling import PluginError

class PluginBase(ABC):
    """Base class for all plugins"""
    
    def __init__(self):
        """Initialize plugin"""
        self.name = self.__class__.__name__
        self.config = {}
        
    @abstractmethod
    def configure(self, config: Dict[str, Any]) -> None:
        """Configure the plugin with settings"""
        pass
    
    @abstractmethod
    def start(self) -> None:
        """Start the plugin"""
        pass
    
    @abstractmethod
    def stop(self) -> None:
        """Stop the plugin"""
        pass
    
    @abstractmethod
    def process(self, data: Any) -> Any:
        """Process data through the plugin"""
        pass
    
    def validate_config(self, config: Dict[str, Any], required_keys: List[str]) -> None:
        """Validate plugin configuration"""
        for key in required_keys:
            if key not in config:
                raise PluginError(f"Missing required config key: {key}")
                
    def get_config(self) -> Dict[str, Any]:
        """Get current configuration"""
        return self.config.copy()
