"""
Regression tests for plugin_manager.py.

Key bug fixed: _load_plugin() referenced PluginBase without importing it,
causing NameError: name 'PluginBase' is not defined on every plugin load.

Run: python -m unittest tests.test_plugin_manager -v
"""
import os
import sys
import tempfile
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from plugin_manager import PluginManager  # noqa: E402
from plugin_base import PluginBase  # noqa: E402
from logging_manager import LoggingManager  # noqa: E402


class _StubLogger:
    """Minimal logger stub matching the interface PluginManager expects."""
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


class PluginManagerImportTests(unittest.TestCase):
    def test_plugin_base_importable_in_plugin_manager(self):
        """PluginBase must be reachable from plugin_manager (was NameError before fix)."""
        import plugin_manager as pm
        self.assertTrue(hasattr(pm, 'PluginBase'))

    def test_load_plugin_nonexistent_file_raises_plugin_error(self):
        """_load_plugin on a nonexistent file raises PluginError, not NameError."""
        from error_handling import PluginError
        from pathlib import Path
        pm = PluginManager(_StubLogger())
        with self.assertRaises(PluginError):
            pm._load_plugin(Path("/nonexistent/my_plugin.py"))

    def test_load_plugins_no_nameerror_on_missing_dir(self):
        """load_plugins on a missing plugin dir raises PluginError, not NameError."""
        from error_handling import PluginError
        pm = PluginManager(_StubLogger())
        pm.plugin_directory = type('P', (), {'exists': lambda s: False,
                                             '__fspath__': lambda s: 'plugins'})()
        with self.assertRaises(PluginError):
            pm.load_plugins()

    def test_get_plugin_raises_for_unknown(self):
        from error_handling import PluginError
        pm = PluginManager(_StubLogger())
        with self.assertRaises(PluginError):
            pm.get_plugin("nonexistent")

    def test_plugin_base_is_abstract(self):
        """PluginBase cannot be instantiated directly (it has abstract methods)."""
        with self.assertRaises(TypeError):
            PluginBase()

    def test_load_valid_plugin_file(self):
        """Loading a valid plugin file instantiates the concrete subclass."""
        from pathlib import Path

        # Write a plugin that imports PluginBase from the same sys.path as plugin_manager
        plugin_src = f"""\
import sys
sys.path.insert(0, {_MAIN!r})
from plugin_base import PluginBase

class MyPlugin(PluginBase):
    def configure(self, config): self.config = config
    def start(self): pass
    def stop(self): pass
    def process(self, data): return data
"""
        with tempfile.TemporaryDirectory() as d:
            plugin_path = os.path.join(d, "my_plugin.py")
            with open(plugin_path, "w") as f:
                f.write(plugin_src)

            pm = PluginManager(_StubLogger())
            pm.plugin_directory = Path(d)
            pm._load_plugin_config = lambda: None
            pm.plugin_config = {}

            pm._load_plugin(Path(plugin_path))
            self.assertIn("my_plugin", pm.plugins)


class PluginBaseValidationTests(unittest.TestCase):
    def test_validate_config_passes_with_required_keys(self):
        class ConcretePlugin(PluginBase):
            def configure(self, cfg): pass
            def start(self): pass
            def stop(self): pass
            def process(self, data): return data

        p = ConcretePlugin()
        p.validate_config({"a": 1, "b": 2}, ["a", "b"])  # must not raise

    def test_validate_config_raises_on_missing_key(self):
        from error_handling import PluginError

        class ConcretePlugin(PluginBase):
            def configure(self, cfg): pass
            def start(self): pass
            def stop(self): pass
            def process(self, data): return data

        p = ConcretePlugin()
        with self.assertRaises(PluginError):
            p.validate_config({"a": 1}, ["a", "missing_key"])


if __name__ == "__main__":
    unittest.main()
