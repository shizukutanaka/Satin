"""
Stdlib-only tests for layered multi-environment config loading.

Like Dynaconf/Hydra, a base config file can be overlaid by an environment
specific sibling file selected via SATIN_ENV:

    config.json            (base)
    config.production.json (overlay, applied when SATIN_ENV=production)

Precedence (low -> high): base file < environment layer < env-var overlay.

Run: python -m unittest tests.test_config_layered_env -v
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import utils_config as uc  # noqa: E402
from config import env as cenv  # noqa: E402


class _EnvSandbox(unittest.TestCase):
    def setUp(self):
        self._saved = {k: v for k, v in os.environ.items() if k.startswith("SATIN_")}
        for k in self._saved:
            del os.environ[k]
        self._dir = tempfile.mkdtemp()
        self.base = os.path.join(self._dir, "config.json")
        self._write(self.base, {
            "version": "1.0.0",
            "settings": {"log_level": "INFO", "debug_mode": True,
                         "backup": {"max_backups": 5}},
            "plugins": [],
        })

    def tearDown(self):
        for k in [k for k in os.environ if k.startswith("SATIN_")]:
            del os.environ[k]
        os.environ.update(self._saved)

    @staticmethod
    def _write(path, data):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)


class LayeredLoadTests(_EnvSandbox):
    def test_no_env_loads_base_only(self):
        cfg = uc.load_config(self.base)
        self.assertEqual(cfg["settings"]["log_level"], "INFO")
        self.assertEqual(cfg["settings"]["backup"]["max_backups"], 5)

    def test_environment_layer_is_deep_merged(self):
        self._write(os.path.join(self._dir, "config.production.json"),
                    {"settings": {"log_level": "WARNING",
                                  "backup": {"max_backups": 20}}})
        os.environ["SATIN_ENV"] = "production"
        cfg = uc.load_config(self.base)
        # overridden keys
        self.assertEqual(cfg["settings"]["log_level"], "WARNING")
        self.assertEqual(cfg["settings"]["backup"]["max_backups"], 20)
        # untouched keys preserved from base
        self.assertIs(cfg["settings"]["debug_mode"], True)
        self.assertEqual(cfg["version"], "1.0.0")

    def test_missing_layer_file_is_a_noop(self):
        os.environ["SATIN_ENV"] = "staging"  # no config.staging.json
        cfg = uc.load_config(self.base)
        self.assertEqual(cfg["settings"]["log_level"], "INFO")

    def test_layer_path_derivation(self):
        p = uc._environment_layer_path(Path("/x/config.json"), "production")
        self.assertEqual(p, Path("/x/config.production.json"))

    def test_layer_path_preserves_suffix(self):
        p = uc._environment_layer_path(Path("/x/config.yaml"), "dev")
        self.assertEqual(p, Path("/x/config.dev.yaml"))


class ControlVarNonPollutionTests(_EnvSandbox):
    """Control vars must never leak into the dynamic config overlay."""

    def test_satin_env_not_in_overlay(self):
        os.environ["SATIN_ENV"] = "production"
        self.assertEqual(cenv.get_dynamic_env_config(), {})

    def test_disable_dotenv_not_in_overlay(self):
        os.environ["SATIN_DISABLE_DOTENV"] = "1"
        self.assertEqual(cenv.get_dynamic_env_config(), {})

    def test_lang_not_in_overlay(self):
        os.environ["SATIN_LANG"] = "ja"
        self.assertEqual(cenv.get_dynamic_env_config(), {})

    def test_real_config_key_still_works_alongside_control_vars(self):
        os.environ["SATIN_ENV"] = "production"
        os.environ["SATIN_SETTINGS__LOG_LEVEL"] = "DEBUG"
        overlay = cenv.get_dynamic_env_config()
        self.assertEqual(overlay, {"settings": {"log_level": "DEBUG"}})


class EnvLayerPlusOverlayPrecedenceTests(_EnvSandbox):
    """Env-var overlay (highest precedence) wins over the environment file."""

    def setUp(self):
        super().setUp()
        self._write(os.path.join(self._dir, "config.production.json"),
                    {"settings": {"log_level": "WARNING"}})
        uc._config_instance = None

    def tearDown(self):
        uc._config_instance = None
        super().tearDown()

    def test_env_var_overrides_environment_layer(self):
        os.environ["SATIN_ENV"] = "production"
        os.environ["SATIN_SETTINGS__LOG_LEVEL"] = "ERROR"
        # Seed the singleton from our layered base+production file.
        uc._config_instance = uc.load_config(self.base)
        cfg = uc.get_config()
        # file layer said WARNING, env var says ERROR -> ERROR wins
        self.assertEqual(cfg["settings"]["log_level"], "ERROR")


if __name__ == "__main__":
    unittest.main()
