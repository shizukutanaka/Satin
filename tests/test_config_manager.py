"""
Tests for ConfigManager key behaviors.

Run: python -m unittest tests.test_config_manager -v
"""
import json
import os
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
        # Patch utils_config.get_config to return our sample config
        self._patcher = patch("config_manager.get_config",
                              return_value=_SAMPLE_CONFIG)
        self._patcher.start()
        self.cm.load()

    def tearDown(self):
        self._patcher.stop()
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


if __name__ == "__main__":
    unittest.main()
