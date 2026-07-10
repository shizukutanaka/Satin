"""
Tests for ConfigManager key behaviors.

Run: python -m unittest tests.test_config_manager -v
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from config_manager import ConfigManager  # noqa: E402


_SAMPLE_CONFIG = {
    "version": "1.0.0",
    "settings": {"backup": {"max_backups": 3}},
    "plugins": [
        {"name": "plugin_a", "settings": {"key": "value_a"}},
        {"name": "plugin_b", "settings": {"key": "value_b"}},
    ]
}


class ConfigManagerPluginTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.config_path = os.path.join(self._tmp, "config.json")
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(_SAMPLE_CONFIG, f)

        self.cm = ConfigManager(config_path=self.config_path)
        # Patch utils_config.get_config (effective, env-overlaid config) to
        # return our sample config. update_plugin_config() also reads
        # _ensure_loaded() (the base, non-overlaid config) directly for its
        # save path — patch it too, consistent with get_config(): with no
        # env overrides active, get_config() == _ensure_loaded() in the real
        # (unmocked) implementation.
        self._patcher = patch("config_manager.get_config",
                              return_value=_SAMPLE_CONFIG)
        self._patcher.start()
        self._base_patcher = patch("config_manager._ensure_loaded",
                                   return_value=_SAMPLE_CONFIG)
        self._base_patcher.start()
        self.cm.load()

    def tearDown(self):
        self._patcher.stop()
        self._base_patcher.stop()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_get_plugin_config_returns_settings(self):
        result = self.cm.get_plugin_config("plugin_a")
        self.assertEqual(result, {"key": "value_a"})

    def test_get_plugin_config_unknown_returns_none(self):
        result = self.cm.get_plugin_config("nonexistent")
        self.assertIsNone(result)

    def test_update_plugin_config_modifies_settings(self):
        new_settings = {"key": "updated"}
        with patch("config_manager.update_config", return_value=True) as mock_save:
            result = self.cm.update_plugin_config("plugin_a", new_settings)
        self.assertTrue(result)
        # Config dict must have been updated in memory
        self.assertEqual(self.cm.get_plugin_config("plugin_a"), new_settings)

    def test_update_plugin_config_unknown_returns_false(self):
        with patch("config_manager.update_config", return_value=True):
            result = self.cm.update_plugin_config("ghost_plugin", {"k": "v"})
        self.assertFalse(result)

    def test_validate_returns_dict(self):
        with patch("config_manager.validate_config", return_value={"errors": [], "warnings": []}):
            result = self.cm.validate()
        self.assertIsInstance(result, dict)


class ConfigManagerBackupTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.config_path = os.path.join(self._tmp, "config.json")
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump({"test": True}, f)
        self.cm = ConfigManager(config_path=self.config_path)
        self._patcher = patch("config_manager.get_config", return_value={"test": True,
                                                                         "settings": {}})
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_create_backup_returns_true_and_creates_file(self):
        result = self.cm.create_backup()
        self.assertTrue(result)
        backups = list(Path(self.cm.backup_dir).glob("config_backup_*.json"))
        self.assertEqual(len(backups), 1)

    def test_restore_backup_missing_file_returns_false(self):
        result = self.cm.restore_backup("/nonexistent/backup.json")
        self.assertFalse(result)

    def test_restore_backup_roundtrip(self):
        """Create a backup, modify config, then restore — verifies restore overwrites."""
        self.cm.create_backup()
        backups = list(Path(self.cm.backup_dir).glob("config_backup_*.json"))
        self.assertEqual(len(backups), 1)

        # Overwrite config with different content
        with open(self.config_path, "w") as f:
            json.dump({"test": False, "modified": True}, f)

        # Restore
        with patch("config_manager.get_config", return_value={"test": True,
                                                              "settings": {}}):
            result = self.cm.restore_backup(str(backups[0]))
        self.assertTrue(result)

        with open(self.config_path, encoding="utf-8") as f:
            restored = json.load(f)
        self.assertTrue(restored.get("test"))
        self.assertNotIn("modified", restored)


class CleanupNullSettingsTests(unittest.TestCase):
    """_cleanup_old_backups must not crash when settings/backup keys are null."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.config_path = os.path.join(self.tmp, "config.json")
        with open(self.config_path, "w") as f:
            json.dump({}, f)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_null_settings_does_not_crash_cleanup(self):
        """settings: null in JSON must not AttributeError during backup cleanup."""
        cm = ConfigManager(config_path=self.config_path)
        try:
            with patch("config_manager.get_config", return_value={"settings": None}):
                cm._cleanup_old_backups()
        except AttributeError:
            self.fail("_cleanup_old_backups raised AttributeError on null settings")

    def test_null_backup_nested_does_not_crash_cleanup(self):
        """settings.backup: null must not AttributeError during backup cleanup."""
        cm = ConfigManager(config_path=self.config_path)
        try:
            with patch("config_manager.get_config",
                       return_value={"settings": {"backup": None}}):
                cm._cleanup_old_backups()
        except AttributeError:
            self.fail("_cleanup_old_backups raised AttributeError on null backup key")


class SingletonThreadSafetyTests(unittest.TestCase):
    """Regression: get_config_manager() had no lock, so concurrent first calls
    could create multiple ConfigManager instances (last-write-wins on the global),
    silently dropping config updates made on the abandoned instance."""

    def setUp(self):
        import config_manager
        self._cm_mod = config_manager
        self._orig = config_manager._config_manager
        config_manager._config_manager = None

    def tearDown(self):
        self._cm_mod._config_manager = self._orig

    def test_concurrent_get_returns_same_instance(self):
        import threading
        instances = []
        barrier = threading.Barrier(8)

        def grab():
            barrier.wait()  # maximize the chance of a simultaneous None check
            instances.append(self._cm_mod.get_config_manager())

        threads = [threading.Thread(target=grab) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(len(instances), 8)
        first = instances[0]
        for inst in instances[1:]:
            self.assertIs(inst, first,
                          "get_config_manager() must return one shared instance")

    def test_lock_object_exists(self):
        import threading as _t
        self.assertIsInstance(self._cm_mod._config_manager_lock, type(_t.Lock()))


class UpdatePluginConfigEnvPersistenceTests(unittest.TestCase):
    """Regression: update_plugin_config() saved self.current_config (the
    get_config() effective view, env-overlay included) directly.
    utils_config.update_config()'s merge_configs(base, new_config) lets the
    override side win, so passing the full effective config as new_config
    baked every env-overridden leaf value into the base config written to
    disk — including fields having nothing to do with the plugin being
    updated (e.g. settings.log_level). utils_config.py itself deliberately
    avoids this by using _ensure_loaded() (base-only) rather than
    get_config() for its own update_config() calls; ConfigManager bypassed
    that protection entirely. Isolates utils_config._config_instance
    directly (matching test_config_env_overrides.py's pattern) so no real
    config file is ever touched.
    """

    def setUp(self):
        import config_manager as cm_mod
        import utils_config as uc
        self._cm_mod = cm_mod
        self._uc = uc
        self._orig_instance = uc._config_instance
        uc._config_instance = {
            "version": "1.0.0",
            "settings": {"log_level": "INFO", "backup": {"max_backups": 5}},
            "plugins": [{"name": "demo", "settings": {"foo": "original"}}],
        }
        self._saved_env = {k: v for k, v in os.environ.items() if k.startswith("SATIN_")}
        for k in self._saved_env:
            del os.environ[k]

    def tearDown(self):
        self._uc._config_instance = self._orig_instance
        for k in [k for k in os.environ if k.startswith("SATIN_")]:
            del os.environ[k]
        os.environ.update(self._saved_env)

    def test_env_overridden_field_is_not_persisted_via_update_plugin_config(self):
        os.environ["SATIN_SETTINGS__LOG_LEVEL"] = "DEBUG"
        cm = self._cm_mod.ConfigManager(config_path="/tmp/unused-not-written.json")
        cm.load()  # current_config now has log_level == "DEBUG" (env overlay)
        self.assertEqual(cm.current_config["settings"]["log_level"], "DEBUG")

        with patch("config_manager.update_config", return_value=True) as mock_update:
            ok = cm.update_plugin_config("demo", {"foo": "changed"})

        self.assertTrue(ok)
        self.assertEqual(mock_update.call_count, 1)
        saved_config = mock_update.call_args[0][0]
        # The env-overridden value must NOT appear in what gets persisted —
        # only the base file value ("INFO") should flow through to save().
        self.assertEqual(saved_config["settings"]["log_level"], "INFO",
                         "env var value leaked into the persisted config")
        # The actual intended change must still be present.
        for plugin in saved_config["plugins"]:
            if plugin["name"] == "demo":
                self.assertEqual(plugin["settings"], {"foo": "changed"})
                break
        else:
            self.fail("plugin 'demo' missing from saved config")

    def test_current_config_cache_reflects_the_update_immediately(self):
        cm = self._cm_mod.ConfigManager(config_path="/tmp/unused-not-written.json")
        cm.load()
        with patch("config_manager.update_config", return_value=True):
            cm.update_plugin_config("demo", {"foo": "changed"})
        # get_plugin_config() must see the fresh value without a reload.
        self.assertEqual(cm.get_plugin_config("demo"), {"foo": "changed"})

    def test_unrelated_base_field_untouched_when_no_env_override_active(self):
        """Sanity check: with no env vars set, the persisted config must
        still equal the base — this isn't a regression in the common case."""
        cm = self._cm_mod.ConfigManager(config_path="/tmp/unused-not-written.json")
        cm.load()
        with patch("config_manager.update_config", return_value=True) as mock_update:
            cm.update_plugin_config("demo", {"foo": "changed"})
        saved_config = mock_update.call_args[0][0]
        self.assertEqual(saved_config["settings"]["log_level"], "INFO")
        self.assertEqual(saved_config["settings"]["backup"]["max_backups"], 5)


class UpdatePluginConfigConcurrencyTests(unittest.TestCase):
    """Regression: update_plugin_config()'s read-merge-write had no lock,
    so two near-simultaneous calls could both read the same base config,
    merge independently, and the second writer's result would silently
    discard the first writer's change (lost update)."""

    def setUp(self):
        import config_manager as cm_mod
        import utils_config as uc
        self._cm_mod = cm_mod
        self._uc = uc
        self._orig_instance = uc._config_instance
        uc._config_instance = {
            "version": "1.0.0",
            "settings": {},
            "plugins": [
                {"name": "a", "settings": {}},
                {"name": "b", "settings": {}},
            ],
        }

    def tearDown(self):
        self._uc._config_instance = self._orig_instance

    def test_write_lock_exists(self):
        cm = self._cm_mod.ConfigManager(config_path="/tmp/unused-not-written.json")
        import threading as _t
        self.assertIsInstance(cm._write_lock, type(_t.Lock()))

    def test_concurrent_updates_to_different_plugins_both_succeed(self):
        import threading
        cm = self._cm_mod.ConfigManager(config_path="/tmp/unused-not-written.json")
        cm.load()
        results = []

        def update_a():
            with patch("config_manager.update_config", return_value=True):
                results.append(cm.update_plugin_config("a", {"x": 1}))

        def update_b():
            with patch("config_manager.update_config", return_value=True):
                results.append(cm.update_plugin_config("b", {"y": 2}))

        threads = [threading.Thread(target=update_a) for _ in range(4)] + \
                  [threading.Thread(target=update_b) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertTrue(all(results), f"every concurrent update must report success: {results}")


if __name__ == "__main__":
    unittest.main()
