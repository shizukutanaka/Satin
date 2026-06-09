"""
Environment variable handling for Satin configuration
"""
import os
import re
import logging
from typing import Dict, Any, Optional, List, Tuple, Type, TypeVar, Union
from pathlib import Path

logger = logging.getLogger(__name__)

T = TypeVar('T')

# Prefix for all Satin environment variables
ENV_PREFIX = 'SATIN_'

# Double underscore separates nesting levels, following the de-facto convention
# used by Dynaconf and Pydantic-Settings. Example:
#   SATIN_SETTINGS__BACKUP__MAX_BACKUPS=10  ->  settings.backup.max_backups = 10
NESTED_DELIMITER = '__'

# Environment variable that selects the active config layer (e.g. "production"),
# used to load a sibling overlay file config.<env>.json over the base config.
ENV_SELECTOR_VAR = 'SATIN_ENV'

# Prefixed vars that are *control* knobs consumed directly by Satin rather than
# generic config overrides. They are excluded from the dynamic SECTION__KEY
# overlay so they never inject spurious top-level keys into the config.
#   SATIN_ENV            -> selects the environment layer (handled in load_config)
#   SATIN_DISABLE_DOTENV -> opt out of .env auto-loading
#   SATIN_LANG           -> i18n language selector (consumed by i18n.py)
CONTROL_KEYS = frozenset({'ENV', 'DISABLE_DOTENV', 'LANG'})

# Guards one-time auto-loading of a ./.env file on first config read.
_DOTENV_AUTOLOADED = False

# Mapping of environment variables to config paths
ENV_MAPPING = {
    # Core
    'DEBUG': 'debug',
    'CONFIG_DIR': 'paths.config_dir',
    'DATA_DIR': 'paths.data_dir',
    'CACHE_DIR': 'paths.cache_dir',
    'LOG_DIR': 'paths.log_dir',
    'PLUGIN_DIR': 'paths.plugin_dir',
    'TEMP_DIR': 'paths.temp_dir',
    
    # Logging
    'LOG_LEVEL': 'logging.level',
    'LOG_FILE': 'logging.file',
    'LOG_MAX_SIZE': 'logging.max_size_mb',
    'LOG_BACKUP_COUNT': 'logging.backup_count',
    'LOG_ENABLE_CONSOLE': 'logging.enable_console',
    'LOG_ENABLE_FILE': 'logging.enable_file',
    
    # UI
    'UI_THEME': 'ui.theme',
    'UI_FONT_SIZE': 'ui.font_size',
    'UI_LANGUAGE': 'ui.language',
    'UI_SHOW_TOOLTIPS': 'ui.show_tooltips',
    'UI_ANIMATION_ENABLED': 'ui.animation_enabled',
    
    # Network
    'NETWORK_PROXY': 'network.proxy',
    'NETWORK_TIMEOUT': 'network.timeout',
    'NETWORK_RETRY_ATTEMPTS': 'network.retry_attempts',
    'NETWORK_VERIFY_SSL': 'network.verify_ssl',
}

def get_dynamic_env_config(prefix: str = ENV_PREFIX) -> Dict[str, Any]:
    """
    Build a config overlay from *any* prefixed environment variable.

    Unlike the legacy ENV_MAPPING whitelist, this lets callers override any
    nested config key without pre-registering it. The portion after the prefix
    is split on the nesting delimiter ("__") and each segment is lower-cased to
    match the JSON config key convention (settings, log_level, max_backups...).

        SATIN_SETTINGS__LOG_LEVEL=DEBUG       -> {'settings': {'log_level': 'DEBUG'}}
        SATIN_SETTINGS__BACKUP__MAX_BACKUPS=10 -> {'settings': {'backup': {'max_backups': 10}}}

    Args:
        prefix: Prefix for environment variables

    Returns:
        Nested dictionary built from prefixed environment variables
    """
    config: Dict[str, Any] = {}
    plen = len(prefix)

    for env_var, raw in os.environ.items():
        if not env_var.startswith(prefix):
            continue
        remainder = env_var[plen:]
        # Skip (a) keys handled by the explicit ENV_MAPPING alias table — applied
        # separately and taking precedence — and (b) control vars consumed
        # directly by Satin, so neither injects spurious top-level config keys.
        if not remainder or remainder in ENV_MAPPING or remainder in CONTROL_KEYS:
            continue

        segments = [seg.lower() for seg in remainder.split(NESTED_DELIMITER) if seg != '']
        if not segments:
            continue

        _set_nested(config, '.'.join(segments), _parse_env_value(raw))

    return config

def parse_dotenv(text: str) -> Dict[str, str]:
    """
    Parse the contents of a ``.env`` file into a dict of string values.

    Supported syntax (a practical subset of the python-dotenv format):
      - ``KEY=VALUE`` one per line
      - blank lines and lines whose first non-space char is ``#`` are ignored
      - an optional leading ``export `` is stripped
      - surrounding matching single/double quotes are removed; inside double
        quotes ``\\n`` / ``\\t`` escapes are expanded

    Values are intentionally kept literal otherwise (no inline-comment
    stripping) so that values legitimately containing ``#`` are preserved.

    Args:
        text: Raw file contents

    Returns:
        Mapping of KEY -> raw string value
    """
    result: Dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[len('export '):].lstrip()
        if '=' not in line:
            continue
        key, _, value = line.partition('=')
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            quote = value[0]
            value = value[1:-1]
            if quote == '"':
                value = value.replace('\\n', '\n').replace('\\t', '\t')
        result[key] = value
    return result

def load_dotenv(path: Optional[Union[str, Path]] = None, override: bool = False) -> Dict[str, str]:
    """
    Load a ``.env`` file into ``os.environ``.

    Mirrors python-dotenv's default precedence: an already-set real environment
    variable is NOT replaced unless ``override=True``. This keeps real env vars
    authoritative over file-provided defaults.

    Args:
        path: Path to the .env file (defaults to ``./.env``)
        override: When True, .env values replace existing environment variables

    Returns:
        Mapping of the keys that were actually applied to the environment
    """
    env_path = Path(path) if path else Path('.env')
    if not env_path.exists():
        return {}

    try:
        text = env_path.read_text(encoding='utf-8')
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(f".env の読み込みに失敗しました: {env_path}: {e}")
        return {}

    applied: Dict[str, str] = {}
    for key, value in parse_dotenv(text).items():
        if not override and key in os.environ:
            continue
        os.environ[key] = value
        applied[key] = value
    return applied

def _maybe_autoload_dotenv() -> None:
    """Auto-load ``./.env`` exactly once on first config read (opt-out via
    ``SATIN_DISABLE_DOTENV``). Never overrides real environment variables."""
    global _DOTENV_AUTOLOADED
    if _DOTENV_AUTOLOADED:
        return
    _DOTENV_AUTOLOADED = True
    if os.environ.get('SATIN_DISABLE_DOTENV'):
        return
    load_dotenv()

def get_env_config(prefix: str = ENV_PREFIX) -> Dict[str, Any]:
    """
    Extract configuration from environment variables.

    Combines the dynamic ``SECTION__KEY`` overlay with the explicit
    ENV_MAPPING alias table. Explicit aliases take precedence over dynamic keys
    so the documented short names remain authoritative. A ``./.env`` file is
    auto-loaded once on first call.

    Args:
        prefix: Prefix for environment variables

    Returns:
        Dictionary with configuration from environment variables
    """
    _maybe_autoload_dotenv()
    config = get_dynamic_env_config(prefix)

    for env_var, config_path in ENV_MAPPING.items():
        full_env_var = f"{prefix}{env_var}"
        if full_env_var in os.environ:
            value = os.environ[full_env_var]
            _set_nested(config, config_path, _parse_env_value(value))

    return config

def _parse_env_value(value: str) -> Any:
    """
    Parse environment variable value to appropriate Python type
    
    Args:
        value: Environment variable value as string
        
    Returns:
        Parsed value with appropriate type
    """
    # Handle boolean values
    if value.lower() in ('true', 'yes', '1'):
        return True
    if value.lower() in ('false', 'no', '0'):
        return False
    
    # Handle numeric values (int first, including negatives, then float)
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    
    # Handle lists (comma-separated)
    if ',' in value:
        return [_parse_env_item(v.strip()) for v in value.split(',')]
    
    # Handle JSON-like values
    if value.startswith(('{', '[', '"')):
        try:
            import json
            return json.loads(value)
        except json.JSONDecodeError:
            pass
    
    # Return as string
    return value

def _parse_env_item(value: str) -> Any:
    """Parse a single environment variable value item"""
    value = value.strip()
    
    # Handle quoted strings
    if (value.startswith('"') and value.endswith('"')) or \
       (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    
    # Handle boolean and numeric values
    return _parse_env_value(value)

def _set_nested(config: Dict[str, Any], path: str, value: Any) -> None:
    """
    Set a nested configuration value using dot notation
    
    Args:
        config: Configuration dictionary to update
        path: Dot-separated path to the configuration value
        value: Value to set
    """
    keys = path.split('.')
    current = config
    
    for key in keys[:-1]:
        if key not in current:
            current[key] = {}
        current = current[key]
    
    current[keys[-1]] = value

def apply_env_overrides(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply environment variable overrides to configuration
    
    Args:
        config: Base configuration
        
    Returns:
        Updated configuration with environment overrides
    """
    env_config = get_env_config()
    return _deep_merge(config, env_config)

def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deep merge two dictionaries
    
    Args:
        base: Base dictionary
        override: Dictionary with override values
        
    Returns:
        Merged dictionary
    """
    result = base.copy()
    
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
            
    return result

def get_env_bool(key: str, default: bool = False) -> bool:
    """Get a boolean value from environment variables"""
    value = os.environ.get(key, '').lower()
    return value in ('true', 'yes', '1') if value else default

def get_env_int(key: str, default: int = 0) -> int:
    """Get an integer value from environment variables"""
    try:
        return int(os.environ.get(key, str(default)))
    except (ValueError, TypeError):
        return default

def get_env_float(key: str, default: float = 0.0) -> float:
    """Get a float value from environment variables"""
    try:
        return float(os.environ.get(key, str(default)))
    except (ValueError, TypeError):
        return default

def get_env_str(key: str, default: str = '') -> str:
    """Get a string value from environment variables"""
    return os.environ.get(key, default)

def get_env_list(key: str, delimiter: str = ',', default: Optional[list] = None) -> list:
    """
    Get a list from environment variables
    
    Args:
        key: Environment variable name
        delimiter: Delimiter to split the string
        default: Default value if key is not found
        
    Returns:
        List of values
    """
    if default is None:
        default = []
        
    value = os.environ.get(key, '')
    if not value:
        return default
        
    return [item.strip() for item in value.split(delimiter) if item.strip()]
