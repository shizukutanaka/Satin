"""
Stdlib-only tests for the environment-variable override layer.

Brings Satin's config loading in line with the 12-factor / Dynaconf /
Pydantic-Settings convention: any nested config key can be overridden via a
prefixed env var using ``__`` to denote nesting, e.g.

    SATIN_SETTINGS__LOG_LEVEL=DEBUG  ->  settings.log_level = "DEBUG"

Two behaviours are pinned down here:
  1. config.env builds the correct nested overlay with type casting.
  2. utils_config.get_config() applies the overlay at read time WITHOUT
     persisting env values back to the base (file) config.

Run: python -m unittest tests.test_config_env_overrides -v
"""
import os
import sys
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from config import env as cenv  # noqa: E402
import utils_config as uc  # noqa: E402


class _EnvSandbox(unittest.TestCase):
    """Removes any SATIN_-prefixed env var around each test for isolation."""

    def setUp(self):
        self._saved = {k: v for k, v in os.environ.items() if k.startswith(cenv.ENV_PREFIX)}
        for k in self._saved:
            del os.environ[k]

    def tearDown(self):
        for k in [k for k in os.environ if k.startswith(cenv.ENV_PREFIX)]:
            del os.environ[k]
        os.environ.update(self._saved)


class DynamicEnvConfigTests(_EnvSandbox):
    def test_single_level_key(self):
        os.environ["SATIN_DEBUG_MODE"] = "true"
        cfg = cenv.get_dynamic_env_config()
        self.assertEqual(cfg, {"debug_mode": True})

    def test_nested_key_via_double_underscore(self):
        os.environ["SATIN_SETTINGS__LOG_LEVEL"] = "DEBUG"
        cfg = cenv.get_dynamic_env_config()
        self.assertEqual(cfg, {"settings": {"log_level": "DEBUG"}})

    def test_deeply_nested_key_with_type_casting(self):
        os.environ["SATIN_SETTINGS__BACKUP__MAX_BACKUPS"] = "10"
        cfg = cenv.get_dynamic_env_config()
        self.assertEqual(cfg, {"settings": {"backup": {"max_backups": 10}}})
        self.assertIsInstance(cfg["settings"]["backup"]["max_backups"], int)

    def test_unprefixed_vars_are_ignored(self):
        os.environ["NOT_SATIN_FOO"] = "bar"
        os.environ["PATH_SHOULD_NOT_LEAK"] = "x"
        cfg = cenv.get_dynamic_env_config()
        self.assertEqual(cfg, {})

    def test_explicit_mapping_keys_skipped_by_dynamic(self):
        # LOG_LEVEL is an ENV_MAPPING alias; dynamic must not also emit a bare
        # top-level 'log_level' key for it.
        os.environ["SATIN_LOG_LEVEL"] = "DEBUG"
        cfg = cenv.get_dynamic_env_config()
        self.assertNotIn("log_level", cfg)


class ParseEnvValueTests(unittest.TestCase):
    def test_bool_true_variants(self):
        for v in ("true", "yes", "1", "TRUE", "Yes"):
            self.assertIs(cenv._parse_env_value(v), True, v)

    def test_bool_false_variants(self):
        for v in ("false", "no", "0", "FALSE", "No"):
            self.assertIs(cenv._parse_env_value(v), False, v)

    def test_positive_int(self):
        self.assertEqual(cenv._parse_env_value("42"), 42)
        self.assertIsInstance(cenv._parse_env_value("42"), int)

    def test_negative_int_is_int_not_float(self):
        # Regression: "-5".isdigit() is False, so the old code returned -5.0.
        result = cenv._parse_env_value("-5")
        self.assertEqual(result, -5)
        self.assertIsInstance(result, int)

    def test_float(self):
        self.assertEqual(cenv._parse_env_value("3.14"), 3.14)
        self.assertIsInstance(cenv._parse_env_value("3.14"), float)

    def test_plain_string(self):
        self.assertEqual(cenv._parse_env_value("voicevox"), "voicevox")


class GetConfigOverlayTests(_EnvSandbox):
    """get_config() overlays env vars without mutating/persisting the base."""

    def setUp(self):
        super().setUp()
        uc._config_instance = {
            "version": "1.0.0",
            "settings": {"log_level": "INFO", "backup": {"max_backups": 5}},
            "plugins": [],
        }

    def tearDown(self):
        uc._config_instance = None
        super().tearDown()

    def test_overlay_applied_on_read(self):
        os.environ["SATIN_SETTINGS__LOG_LEVEL"] = "DEBUG"
        cfg = uc.get_config()
        self.assertEqual(cfg["settings"]["log_level"], "DEBUG")

    def test_base_singleton_not_mutated_by_overlay(self):
        os.environ["SATIN_SETTINGS__LOG_LEVEL"] = "DEBUG"
        uc.get_config()
        self.assertEqual(uc._config_instance["settings"]["log_level"], "INFO")

    def test_env_values_not_persisted_through_update(self):
        # An env override active during update_config must NOT be baked into the
        # base config that gets saved.
        os.environ["SATIN_SETTINGS__LOG_LEVEL"] = "DEBUG"
        ok = uc.update_config({"settings": {"language": "en"}}, save_to_file=False)
        self.assertTrue(ok)
        self.assertEqual(uc._config_instance["settings"]["log_level"], "INFO")
        self.assertEqual(uc._config_instance["settings"]["language"], "en")

    def test_no_env_vars_returns_base_equivalent(self):
        cfg = uc.get_config()
        self.assertEqual(cfg["settings"]["log_level"], "INFO")
        self.assertEqual(cfg["settings"]["backup"]["max_backups"], 5)


class SetNestedTests(unittest.TestCase):
    """Unit tests for _set_nested — specifically the scalar-overwrite fix."""

    def test_basic_nested_set(self):
        d: dict = {}
        cenv._set_nested(d, "a.b.c", 42)
        self.assertEqual(d, {"a": {"b": {"c": 42}}})

    def test_scalar_intermediate_is_replaced_with_dict(self):
        # Bug: if an intermediate key holds a scalar, _set_nested used to crash
        # with TypeError when trying to subscript the scalar.
        d = {"a": "existing_scalar"}
        cenv._set_nested(d, "a.b", "new_value")
        self.assertEqual(d, {"a": {"b": "new_value"}})

    def test_existing_dict_intermediate_is_preserved(self):
        d = {"a": {"existing": 1}}
        cenv._set_nested(d, "a.b", 2)
        self.assertEqual(d, {"a": {"existing": 1, "b": 2}})

    def test_top_level_set(self):
        d = {"x": 10}
        cenv._set_nested(d, "y", 20)
        self.assertEqual(d, {"x": 10, "y": 20})


if __name__ == "__main__":
    unittest.main()
