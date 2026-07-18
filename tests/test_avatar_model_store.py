"""
Tests for avatar_model_store — the persistence/resolution layer that lets the
--avatar-loader file picker hand a chosen avatar to the main 3D GUI.

Before this store existed, avatar_loader.py wrote a cwd-relative
avatar_history.json that no module ever read, so a user's avatar selection
went nowhere (commercial-quality audit W7 residue). These tests cover the
canonical path, atomic save, robust load, and extension/existence-aware
resolution.
"""
import json
import os
import sys
import tempfile
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import avatar_model_store as store  # noqa: E402


class _StoreTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._hist = os.path.join(self._tmp, "avatar_history.json")
        self._legacy = os.path.join(self._tmp, "legacy_cwd.json")
        self._orig_hist = store.history_path
        self._orig_legacy = store._legacy_cwd_path
        store.history_path = lambda: self._hist
        store._legacy_cwd_path = lambda: self._legacy

    def tearDown(self):
        store.history_path = self._orig_hist
        store._legacy_cwd_path = self._orig_legacy
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _touch(self, name):
        p = os.path.join(self._tmp, name)
        open(p, "wb").close()
        return p


class LoadHistoryTests(_StoreTestBase):
    def test_missing_returns_empty(self):
        self.assertEqual(store.load_history(), [])

    def test_reads_canonical_list(self):
        with open(self._hist, "w", encoding="utf-8") as f:
            json.dump(["/a.glb", "/b.glb"], f)
        self.assertEqual(store.load_history(), ["/a.glb", "/b.glb"])

    def test_corrupt_json_returns_empty(self):
        with open(self._hist, "w", encoding="utf-8") as f:
            f.write("{ not json")
        self.assertEqual(store.load_history(), [])

    def test_non_list_json_returns_empty(self):
        with open(self._hist, "w", encoding="utf-8") as f:
            json.dump({"not": "a list"}, f)
        self.assertEqual(store.load_history(), [])

    def test_falls_back_to_legacy_when_canonical_absent(self):
        with open(self._legacy, "w", encoding="utf-8") as f:
            json.dump(["/legacy.glb"], f)
        self.assertEqual(store.load_history(), ["/legacy.glb"])

    def test_canonical_preferred_over_legacy(self):
        with open(self._hist, "w", encoding="utf-8") as f:
            json.dump(["/canonical.glb"], f)
        with open(self._legacy, "w", encoding="utf-8") as f:
            json.dump(["/legacy.glb"], f)
        self.assertEqual(store.load_history(), ["/canonical.glb"])


class SaveSelectionTests(_StoreTestBase):
    def test_saves_and_reads_back(self):
        store.save_selection("/a.glb")
        self.assertEqual(store.load_history(), ["/a.glb"])

    def test_newest_first(self):
        store.save_selection("/a.glb")
        store.save_selection("/b.glb")
        self.assertEqual(store.load_history(), ["/b.glb", "/a.glb"])

    def test_dedup_moves_to_front(self):
        store.save_selection("/a.glb")
        store.save_selection("/b.glb")
        store.save_selection("/a.glb")
        self.assertEqual(store.load_history(), ["/a.glb", "/b.glb"])

    def test_caps_at_five(self):
        for i in range(8):
            store.save_selection(f"/m{i}.glb")
        hist = store.load_history()
        self.assertEqual(len(hist), 5)
        self.assertEqual(hist[0], "/m7.glb")

    def test_empty_path_is_noop(self):
        store.save_selection("/a.glb")
        store.save_selection("")
        self.assertEqual(store.load_history(), ["/a.glb"])

    def test_creates_parent_dir(self):
        nested = os.path.join(self._tmp, "sub", "dir", "avatar_history.json")
        store.history_path = lambda: nested
        store.save_selection("/a.glb")
        self.assertTrue(os.path.exists(nested))

    def test_no_tmp_files_left_behind(self):
        store.save_selection("/a.glb")
        leftovers = [f for f in os.listdir(self._tmp) if f.endswith(".tmp")]
        self.assertEqual(leftovers, [])


class ResolveSelectedAvatarTests(_StoreTestBase):
    def test_none_when_empty(self):
        self.assertIsNone(store.resolve_selected_avatar())

    def test_none_when_files_do_not_exist(self):
        store.save_selection("/does/not/exist.glb")
        self.assertIsNone(store.resolve_selected_avatar())

    def test_returns_newest_existing_supported(self):
        real = self._touch("model.glb")
        store.save_selection(real)
        self.assertEqual(store.resolve_selected_avatar(), real)

    def test_skips_unsupported_extension(self):
        fbx = self._touch("model.fbx")
        store.save_selection(fbx)
        self.assertIsNone(store.resolve_selected_avatar())

    def test_skips_missing_and_returns_next_existing(self):
        real = self._touch("real.gltf")
        store.save_selection(real)
        store.save_selection("/missing.glb")  # newest, but doesn't exist
        self.assertEqual(store.resolve_selected_avatar(), real)

    def test_vrm_supported(self):
        vrm = self._touch("avatar.vrm")
        store.save_selection(vrm)
        self.assertEqual(store.resolve_selected_avatar(), vrm)

    def test_extension_case_insensitive(self):
        upper = self._touch("MODEL.GLB")
        store.save_selection(upper)
        self.assertEqual(store.resolve_selected_avatar(), upper)


class ClearTests(_StoreTestBase):
    def test_removes_canonical_history(self):
        store.save_selection("/a.glb")
        self.assertTrue(os.path.exists(self._hist))
        self.assertTrue(store.clear())
        self.assertFalse(os.path.exists(self._hist))
        self.assertEqual(store.load_history(), [])

    def test_removes_legacy_history_too(self):
        with open(self._legacy, "w", encoding="utf-8") as f:
            json.dump(["/legacy.glb"], f)
        self.assertTrue(store.clear())
        self.assertFalse(os.path.exists(self._legacy))

    def test_returns_false_when_nothing_to_remove(self):
        self.assertFalse(store.clear())


if __name__ == "__main__":
    unittest.main()
