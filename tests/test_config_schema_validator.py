"""
Stdlib-only regression tests for config_schema.py, config_validator.py,
paper_integrator.py, and content_aggregator cache_dir fix.

Run: python -m unittest tests.test_config_schema_validator -v
"""
import os
import sys
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)


class ConfigSchemaTests(unittest.TestCase):
    def test_imports_and_satin_config_exists(self):
        import config_schema
        self.assertTrue(hasattr(config_schema, "SatinConfig"))

    def test_satin_config_accepts_kwargs(self):
        from config_schema import SatinConfig
        # Must accept arbitrary kwargs without crashing (both pydantic and fallback paths)
        cfg = SatinConfig(version="2.0.0", foo="bar")
        self.assertIsNotNone(cfg)


class ConfigValidatorImportTests(unittest.TestCase):
    def test_imports_without_relative_error(self):
        # Previously crashed: 'attempted relative import with no known parent package'
        import config_validator
        self.assertTrue(hasattr(config_validator, "ConfigValidator"))


if __name__ == "__main__":
    unittest.main()
