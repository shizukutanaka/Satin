"""
Tests for dependency_manifest — the single source of truth for Satin's
optional/required dependency declarations, and that satin_launcher sources
its dep-check lists from it (no hardcoded duplicate).

Run: python -m unittest tests.test_dependency_manifest -v
"""
import importlib
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MAIN = os.path.join(_ROOT, "main")
sys.path.insert(0, _MAIN)
sys.path.insert(0, _ROOT)

import dependency_manifest as M  # noqa: E402


class ManifestShapeTests(unittest.TestCase):
    def test_optional_entries_are_3_tuples(self):
        self.assertTrue(M.OPTIONAL_PACKAGES)
        for entry in M.OPTIONAL_PACKAGES:
            self.assertEqual(len(entry), 3, f"expected (name, hint, purpose): {entry}")
            name, hint, purpose = entry
            self.assertTrue(name and isinstance(name, str))
            self.assertTrue(hint and isinstance(hint, str))
            self.assertTrue(purpose and isinstance(purpose, str))

    def test_required_entries_are_2_tuples(self):
        self.assertTrue(M.REQUIRED_PACKAGES)
        for entry in M.REQUIRED_PACKAGES:
            self.assertEqual(len(entry), 2)

    def test_no_duplicate_import_names(self):
        names = [n for n, _h, _p in M.OPTIONAL_PACKAGES]
        self.assertEqual(len(names), len(set(names)), "duplicate optional import names")

    def test_check_lists_are_2_tuples(self):
        for name, hint in M.optional_check_list():
            self.assertIsInstance(name, str)
            self.assertIsInstance(hint, str)
        self.assertEqual(M.required_check_list(), list(M.REQUIRED_PACKAGES))

    def test_check_list_matches_manifest_length(self):
        self.assertEqual(len(M.optional_check_list()), len(M.OPTIONAL_PACKAGES))

    def test_manifest_does_not_import_heavy_deps(self):
        """The manifest must stay import-cheap: importing it must not pull in
        numpy/cv2/PyQt5 etc. (those belong to optional_deps)."""
        before = set(sys.modules)
        importlib.reload(M)
        newly = set(sys.modules) - before
        for heavy in ("numpy", "cv2", "PyQt5", "OpenGL", "mediapipe"):
            self.assertNotIn(heavy, newly,
                             f"manifest must not import {heavy} as a side effect")


class LauncherSourcesManifestTests(unittest.TestCase):
    def test_launcher_optional_matches_manifest(self):
        import satin_launcher as L
        self.assertEqual(L._OPTIONAL_DEPS, M.optional_check_list())

    def test_launcher_required_matches_manifest(self):
        import satin_launcher as L
        self.assertEqual(L._REQUIRED_DEPS, M.required_check_list())


if __name__ == "__main__":
    unittest.main()
