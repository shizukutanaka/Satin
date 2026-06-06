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


if __name__ == "__main__":
    unittest.main()
