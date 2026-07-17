"""
Regression tests for the relative-import / missing-name fixes in:
- error_handling.py  (added PluginError / ConfigError / ConfigurationError)
- plugin_base.py, plugin_manager.py, config_version_manager.py
  (relative imports -> top-level; missing typing names added)

Run: python -m unittest tests.test_plugin_config_imports -v
"""
import os
import sys
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)


class ErrorHandlingExceptionTests(unittest.TestCase):
    def test_new_exception_classes_exist_and_subclass_satin_error(self):
        from error_handling import (
            SatinError, PluginError, ConfigError, ConfigurationError,
        )
        for exc in (PluginError, ConfigError, ConfigurationError):
            self.assertTrue(issubclass(exc, SatinError))
        # ConfigurationError is a specialization of ConfigError.
        self.assertTrue(issubclass(ConfigurationError, ConfigError))
        # Constructable with just a message (as used by callers).
        self.assertEqual(str(ConfigError("boom")), "boom")


class ModuleImportTests(unittest.TestCase):
    def test_plugin_base_imports(self):
        import plugin_base  # noqa: F401  (was relative-import + NameError: List)

    def test_plugin_manager_imports(self):
        import plugin_manager  # noqa: F401  (was relative-import + missing Logger)

    def test_config_version_manager_imports(self):
        import config_version_manager  # noqa: F401  (was relative-import + NameError: Any)

    def test_plugin_manager_has_json_imported(self):
        # plugin_manager.load_config uses json.load(); json must be importable
        # (was missing -> NameError at runtime when loading plugin config).
        import plugin_manager
        self.assertTrue(hasattr(plugin_manager, "json"))


class VersionCheckTests(unittest.TestCase):
    """Tests for _parse_version and _version_satisfies in config/plugins.py."""

    def setUp(self):
        import sys, os
        config_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "main", "config",
        )
        if config_dir not in sys.path:
            sys.path.insert(0, config_dir)
        from plugins import _parse_version, _version_satisfies
        self._parse = _parse_version
        self._satisfies = _version_satisfies

    def test_parse_simple_version(self):
        self.assertEqual(self._parse("1.2.3"), (1, 2, 3))

    def test_parse_single_digit(self):
        self.assertEqual(self._parse("2"), (2,))

    def test_parse_two_part(self):
        self.assertEqual(self._parse("0.1"), (0, 1))

    def test_parse_non_numeric_part_becomes_zero(self):
        self.assertEqual(self._parse("1.alpha.3"), (1, 0, 3))

    def test_satisfies_equal_versions(self):
        self.assertTrue(self._satisfies("1.0.0", "1.0.0"))

    def test_satisfies_higher_patch(self):
        self.assertTrue(self._satisfies("1.0.1", "1.0.0"))

    def test_satisfies_higher_minor(self):
        self.assertTrue(self._satisfies("1.1.0", "1.0.0"))

    def test_satisfies_higher_major(self):
        self.assertTrue(self._satisfies("2.0.0", "1.9.9"))

    def test_not_satisfies_lower_patch(self):
        self.assertFalse(self._satisfies("1.0.0", "1.0.1"))

    def test_not_satisfies_lower_minor(self):
        self.assertFalse(self._satisfies("1.0.5", "1.1.0"))

    def test_not_satisfies_lower_major(self):
        self.assertFalse(self._satisfies("0.9.9", "1.0.0"))

    def test_empty_required_always_satisfied(self):
        self.assertTrue(self._satisfies("1.0.0", ""))

    def test_empty_installed_not_satisfied_if_required(self):
        self.assertFalse(self._satisfies("", "1.0.0"))


if __name__ == "__main__":
    unittest.main()
