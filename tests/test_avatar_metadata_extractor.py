"""
Tests for avatar_metadata_extractor.extract_metadata().

Run: python -m unittest tests.test_avatar_metadata_extractor -v
"""
import os
import sys
import tempfile
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from avatar_metadata_extractor import extract_metadata, save_metadata, SUPPORTED_EXTS  # noqa: E402


class ExtractMetadataTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_file(self, name, content=b"data"):
        path = os.path.join(self._tmp, name)
        with open(path, "wb") as f:
            f.write(content)
        return path

    def test_returns_required_keys(self):
        path = self._make_file("model.vrm", b"x" * 100)
        meta = extract_metadata(path)
        for key in ("filename", "ext", "size_bytes", "modified", "path"):
            self.assertIn(key, meta)

    def test_filename_and_ext(self):
        path = self._make_file("hero.glb", b"glb")
        meta = extract_metadata(path)
        self.assertEqual(meta["filename"], "hero.glb")
        self.assertEqual(meta["ext"], ".glb")

    def test_size_bytes_correct(self):
        path = self._make_file("avatar.fbx", b"x" * 512)
        meta = extract_metadata(path)
        self.assertEqual(meta["size_bytes"], 512)

    def test_path_is_absolute(self):
        path = self._make_file("a.gltf", b"y")
        meta = extract_metadata(path)
        self.assertTrue(os.path.isabs(meta["path"]))

    def test_unsupported_extension_raises(self):
        path = self._make_file("model.obj", b"v 0 0 0")
        with self.assertRaises(ValueError):
            extract_metadata(path)

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            extract_metadata(os.path.join(self._tmp, "nonexistent.vrm"))

    def test_all_supported_extensions_accepted(self):
        for ext in SUPPORTED_EXTS:
            path = self._make_file(f"model{ext}", b"placeholder")
            meta = extract_metadata(path)
            self.assertEqual(meta["ext"], ext)


class SaveMetadataTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_save_and_reload(self):
        import json
        out_path = os.path.join(self._tmp, "meta.json")
        data = {"filename": "hero.vrm", "ext": ".vrm", "size_bytes": 100}
        save_metadata(data, out_path)
        with open(out_path, encoding="utf-8") as f:
            loaded = json.load(f)
        self.assertEqual(loaded, data)


if __name__ == "__main__":
    unittest.main()
