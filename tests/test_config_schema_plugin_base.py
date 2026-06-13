"""
Stdlib-only tests for main/config_schema.py and main/plugin_base.py.

Run: python -m unittest tests.test_config_schema_plugin_base -v
"""
import os
import sys
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from config_schema import SatinConfig  # noqa: E402
from plugin_base import PluginBase      # noqa: E402
from error_handling import PluginError  # noqa: E402


class SatinConfigTests(unittest.TestCase):
    def test_instantiation_no_args(self):
        # Should not raise regardless of whether Pydantic is installed
        cfg = SatinConfig()
        self.assertIsNotNone(cfg)

    def test_arbitrary_kwargs_accepted(self):
        # extra="allow" or fallback __init__ — arbitrary kwargs must not raise
        cfg = SatinConfig(custom_key="custom_value")
        self.assertEqual(getattr(cfg, "custom_key"), "custom_value")

    def test_multiple_kwargs_stored(self):
        cfg = SatinConfig(host="localhost", port=8080)
        self.assertEqual(getattr(cfg, "host"), "localhost")
        self.assertEqual(getattr(cfg, "port"), 8080)

    def test_version_kwarg_stored(self):
        cfg = SatinConfig(version="2.0.0")
        self.assertEqual(getattr(cfg, "version"), "2.0.0")


class PluginBaseTests(unittest.TestCase):
    """PluginBase is abstract; test via a minimal concrete subclass."""

    def _make_plugin(self):
        class _ConcretePlugin(PluginBase):
            def configure(self, config):
                self.config = config

            def start(self):
                pass

            def stop(self):
                pass

            def process(self, data):
                return data

        return _ConcretePlugin()

    def test_name_defaults_to_class_name(self):
        plugin = self._make_plugin()
        self.assertEqual(plugin.name, "_ConcretePlugin")

    def test_config_initially_empty(self):
        plugin = self._make_plugin()
        self.assertEqual(plugin.config, {})

    def test_configure_updates_config(self):
        plugin = self._make_plugin()
        plugin.configure({"key": "value"})
        self.assertEqual(plugin.config["key"], "value")

    def test_process_returns_data(self):
        plugin = self._make_plugin()
        result = plugin.process("input")
        self.assertEqual(result, "input")

    def test_get_config_returns_copy(self):
        plugin = self._make_plugin()
        plugin.configure({"k": 1})
        copy = plugin.get_config()
        self.assertEqual(copy, {"k": 1})
        # Mutating the copy should not affect the plugin's config
        copy["extra"] = True
        self.assertNotIn("extra", plugin.config)

    def test_validate_config_passes_when_keys_present(self):
        plugin = self._make_plugin()
        # Should not raise
        plugin.validate_config({"host": "localhost", "port": 8080}, ["host", "port"])

    def test_validate_config_raises_on_missing_key(self):
        plugin = self._make_plugin()
        with self.assertRaises(PluginError):
            plugin.validate_config({"host": "localhost"}, ["host", "port"])

    def test_abstract_plugin_cannot_be_instantiated_directly(self):
        with self.assertRaises(TypeError):
            PluginBase()  # type: ignore


if __name__ == "__main__":
    unittest.main()
