"""
Tests for config_manager_enhanced — ConfigDiff, undo stack, export/import,
schema validation, and poll_reload. Does NOT require Flask or watchdog.
"""
import json
import os
import sys
import tempfile
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from config_manager_enhanced import (  # noqa: E402
    ConfigDiff,
    EnhancedConfigManager,
    _deep_update,
    _validate_against_schema,
    reset_enhanced_config_manager,
    get_enhanced_config_manager,
)


class ConfigDiffTests(unittest.TestCase):
    def test_no_change_is_empty(self):
        d = ConfigDiff({"a": 1}, {"a": 1})
        self.assertTrue(d.is_empty())

    def test_added_key(self):
        d = ConfigDiff({}, {"x": 42})
        self.assertIn("x", d.added)
        self.assertEqual(d.added["x"], 42)
        self.assertFalse(d.is_empty())

    def test_removed_key(self):
        d = ConfigDiff({"x": 42}, {})
        self.assertIn("x", d.removed)

    def test_changed_value(self):
        d = ConfigDiff({"x": 1}, {"x": 2})
        self.assertIn("x", d.changed)
        self.assertEqual(d.changed["x"], (1, 2))

    def test_nested_change(self):
        d = ConfigDiff({"a": {"b": 1}}, {"a": {"b": 2}})
        self.assertIn("a.b", d.changed)

    def test_nested_add(self):
        d = ConfigDiff({"a": {}}, {"a": {"new": 99}})
        self.assertIn("a.new", d.added)

    def test_summary_shows_changes(self):
        d = ConfigDiff({"x": 1}, {"x": 2, "y": 3})
        s = d.summary()
        self.assertIn("x", s)
        self.assertIn("y", s)

    def test_summary_no_change(self):
        d = ConfigDiff({"x": 1}, {"x": 1})
        self.assertIn("no changes", d.summary())


class DeepUpdateTests(unittest.TestCase):
    def test_flat_update(self):
        t = {"a": 1, "b": 2}
        _deep_update(t, {"b": 99, "c": 3})
        self.assertEqual(t, {"a": 1, "b": 99, "c": 3})

    def test_nested_merge(self):
        t = {"a": {"x": 1, "y": 2}}
        _deep_update(t, {"a": {"y": 9, "z": 3}})
        self.assertEqual(t["a"], {"x": 1, "y": 9, "z": 3})

    def test_overwrites_non_dict_with_dict(self):
        t = {"a": 1}
        _deep_update(t, {"a": {"nested": True}})
        self.assertEqual(t["a"], {"nested": True})


class SchemaValidationTests(unittest.TestCase):
    def test_valid_object(self):
        schema = {
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer", "minimum": 0, "maximum": 150},
            }
        }
        errs = _validate_against_schema({"name": "Satin", "age": 3}, schema, "")
        self.assertEqual(errs, [])

    def test_missing_required(self):
        schema = {"type": "object", "required": ["name"]}
        errs = _validate_against_schema({}, schema, "")
        self.assertTrue(any("required" in e for e in errs))

    def test_wrong_type(self):
        errs = _validate_against_schema(42, {"type": "string"}, "field")
        self.assertTrue(any("string" in e for e in errs))

    def test_minimum_violated(self):
        errs = _validate_against_schema(-5, {"type": "integer", "minimum": 0}, "val")
        self.assertTrue(any("minimum" in e for e in errs))

    def test_maximum_violated(self):
        errs = _validate_against_schema(200, {"type": "number", "maximum": 100}, "val")
        self.assertTrue(any("maximum" in e for e in errs))

    def test_min_length(self):
        errs = _validate_against_schema("ab", {"type": "string", "minLength": 5}, "s")
        self.assertTrue(any("minLength" in e for e in errs))

    def test_array_items(self):
        schema = {"type": "array", "items": {"type": "integer"}}
        errs = _validate_against_schema([1, "x", 3], schema, "arr")
        self.assertEqual(len(errs), 1)
        self.assertIn("arr[1]", errs[0])

    def test_valid_nested(self):
        schema = {
            "type": "object",
            "properties": {
                "settings": {
                    "type": "object",
                    "properties": {"volume": {"type": "number", "minimum": 0, "maximum": 1}},
                }
            }
        }
        errs = _validate_against_schema({"settings": {"volume": 0.5}}, schema, "")
        self.assertEqual(errs, [])


class EnhancedManagerUndoTests(unittest.TestCase):
    def _make_manager(self, tmp):
        cfg_path = os.path.join(tmp, "config.json")
        with open(cfg_path, "w") as f:
            json.dump({"v": 0}, f)
        mgr = EnhancedConfigManager(config_path=cfg_path)
        mgr.load()
        return mgr

    def test_undo_after_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = self._make_manager(tmp)
            mgr.save({"v": 1})
            self.assertEqual(mgr.undo_depth(), 1)
            mgr.undo()
            mgr.load()
            self.assertEqual(mgr.current_config.get("v"), 0)

    def test_undo_empty_stack(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = self._make_manager(tmp)
            self.assertFalse(mgr.undo())

    def test_undo_stack_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = self._make_manager(tmp)
            mgr._undo_limit = 3
            for i in range(5):
                mgr.save({"v": i})
            self.assertLessEqual(mgr.undo_depth(), 3)

    def test_change_listener_called_on_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = self._make_manager(tmp)
            received = []
            mgr.add_change_listener(received.append)
            mgr.save({"v": 42})
            self.assertEqual(len(received), 1)
            self.assertIn("v", received[0].changed)

    def test_change_listener_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = self._make_manager(tmp)
            calls = []
            cb = calls.append
            mgr.add_change_listener(cb)
            mgr.remove_change_listener(cb)
            mgr.save({"v": 1})
            self.assertEqual(calls, [])


class EnhancedManagerDiffTests(unittest.TestCase):
    def test_diff_returns_config_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = os.path.join(tmp, "config.json")
            with open(cfg_path, "w") as f:
                json.dump({"a": 1}, f)
            mgr = EnhancedConfigManager(config_path=cfg_path)
            mgr.load()
            d = mgr.diff({"a": 2, "b": 3})
            self.assertIn("a", d.changed)
            self.assertIn("b", d.added)


class EnhancedManagerExportImportTests(unittest.TestCase):
    def test_export_then_import_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = os.path.join(tmp, "config.json")
            with open(cfg_path, "w") as f:
                json.dump({"key": "value", "n": 7}, f)
            mgr = EnhancedConfigManager(config_path=cfg_path)
            mgr.load()

            export_path = os.path.join(tmp, "export.json")
            self.assertTrue(mgr.export_json(export_path))
            self.assertTrue(os.path.exists(export_path))

            # Change config then import
            mgr.save({"key": "changed"})
            self.assertTrue(mgr.import_json(export_path))
            mgr.load()
            self.assertEqual(mgr.current_config.get("key"), "value")

    def test_import_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = os.path.join(tmp, "config.json")
            with open(cfg_path, "w") as f:
                json.dump({"a": 1, "b": 2}, f)
            mgr = EnhancedConfigManager(config_path=cfg_path)
            mgr.load()

            patch_path = os.path.join(tmp, "patch.json")
            with open(patch_path, "w") as f:
                json.dump({"b": 99, "c": 3}, f)

            self.assertTrue(mgr.import_json(patch_path, merge=True))
            mgr.load()
            self.assertEqual(mgr.current_config.get("a"), 1)
            self.assertEqual(mgr.current_config.get("b"), 99)
            self.assertEqual(mgr.current_config.get("c"), 3)

    def test_import_non_dict_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = os.path.join(tmp, "config.json")
            with open(cfg_path, "w") as f:
                json.dump({"x": 1}, f)
            bad_path = os.path.join(tmp, "bad.json")
            with open(bad_path, "w") as f:
                json.dump([1, 2, 3], f)
            mgr = EnhancedConfigManager(config_path=cfg_path)
            mgr.load()
            self.assertFalse(mgr.import_json(bad_path))


class EnhancedManagerSchemaTests(unittest.TestCase):
    def test_validate_schema_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = os.path.join(tmp, "config.json")
            with open(cfg_path, "w") as f:
                json.dump({"name": "Satin", "version": 1}, f)
            mgr = EnhancedConfigManager(config_path=cfg_path)
            mgr.load()
            schema = {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string"},
                    "version": {"type": "integer", "minimum": 1},
                },
            }
            errs = mgr.validate_schema(schema)
            self.assertEqual(errs, [])

    def test_validate_schema_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = os.path.join(tmp, "config.json")
            with open(cfg_path, "w") as f:
                json.dump({"version": -1}, f)
            mgr = EnhancedConfigManager(config_path=cfg_path)
            mgr.load()
            schema = {
                "type": "object",
                "required": ["name"],
                "properties": {"version": {"type": "integer", "minimum": 0}},
            }
            errs = mgr.validate_schema(schema)
            self.assertTrue(len(errs) >= 2)  # missing name + version out of range


class EnhancedManagerPollReloadTests(unittest.TestCase):
    def test_poll_reload_false_on_first_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = os.path.join(tmp, "config.json")
            with open(cfg_path, "w") as f:
                json.dump({"v": 0}, f)
            mgr = EnhancedConfigManager(config_path=cfg_path)
            mgr.load()
            self.assertFalse(mgr.poll_reload())

    def test_poll_reload_true_after_file_change(self):
        import time
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = os.path.join(tmp, "config.json")
            with open(cfg_path, "w") as f:
                json.dump({"v": 0}, f)
            mgr = EnhancedConfigManager(config_path=cfg_path)
            mgr.load()
            mgr.poll_reload()  # prime the mtime

            # Write file with a later mtime
            time.sleep(0.05)
            with open(cfg_path, "w") as f:
                json.dump({"v": 1}, f)
            # Force mtime change
            new_mtime = os.path.getmtime(cfg_path) + 1
            os.utime(cfg_path, (new_mtime, new_mtime))

            result = mgr.poll_reload()
            self.assertTrue(result)


class SingletonTests(unittest.TestCase):
    def tearDown(self):
        reset_enhanced_config_manager()

    def test_singleton_returns_same_instance(self):
        a = get_enhanced_config_manager()
        b = get_enhanced_config_manager()
        self.assertIs(a, b)

    def test_reset_gives_new_instance(self):
        a = get_enhanced_config_manager()
        reset_enhanced_config_manager()
        b = get_enhanced_config_manager()
        self.assertIsNot(a, b)


if __name__ == "__main__":
    unittest.main()
