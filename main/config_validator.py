import json
import os
from typing import Dict, Any
from .config_schema import SatinConfig
from .error_handling import ConfigurationError

class ConfigValidator:
    """Configuration validator for Satin"""
    
    def __init__(self, config_path: str):
        """Initialize validator with configuration path"""
        self.config_path = config_path
        self.config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from file"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            raise ConfigurationError(f"Configuration file not found: {self.config_path}")
        except json.JSONDecodeError:
            raise ConfigurationError("Invalid JSON format in configuration file")
    
    def validate(self) -> None:
        """Validate configuration against schema"""
        try:
            # Validate against Pydantic model
            SatinConfig(**self.config)
            
            # Additional custom validations
            self._validate_logging()
            self._validate_ui()
            self._validate_network()
            
            print("Configuration validation successful")
            
        except Exception as e:
            raise ConfigurationError(f"Configuration validation failed: {str(e)}")
    
    def _validate_logging(self) -> None:
        """Validate logging configuration"""
        logging_config = self.config.get('logging', {})
        if not logging_config.get('level') in ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']:
            raise ConfigurationError("Invalid logging level")
    
    def _validate_ui(self) -> None:
        """Validate UI configuration"""
        ui_config = self.config.get('ui', {})
        if not isinstance(ui_config.get('theme'), str):
            raise ConfigurationError("Invalid UI theme configuration")
    
    def _validate_network(self) -> None:
        """Validate network configuration"""
        network_config = self.config.get('network', {})
        if not isinstance(network_config.get('port'), int):
            raise ConfigurationError("Invalid network port configuration")
