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
        """REQUIRED_PACKAGES may legitimately be empty (see
        test_required_packages_is_launcher_mode_agnostic below) — but any
        entry it does have must be a well-formed 2-tuple."""
        for entry in M.REQUIRED_PACKAGES:
            self.assertEqual(len(entry), 2)
            name, message = entry
            self.assertTrue(name and isinstance(name, str))
            self.assertTrue(message and isinstance(message, str))

    def test_required_packages_is_launcher_mode_agnostic(self):
        """Regression: tkinter used to sit in REQUIRED_PACKAGES, which
        satin_launcher._check_deps() enforces unconditionally before
        dispatching to ANY mode. tkinter is only ever imported by
        avatar_loader.py (the default GUI mode), which already guards its
        own import in a try/except with a clear error message — so the
        blanket check made --chat ("headless CLI" per its own --help text),
        --dashboard, --manage, and --validate all refuse to start on a
        machine without tkinter, even though none of those modes touch it.
        REQUIRED_PACKAGES must only ever hold packages every single launch
        mode genuinely needs (currently none)."""
        mode_specific_only = {"tkinter"}
        required_names = {name for name, _msg in M.REQUIRED_PACKAGES}
        self.assertEqual(
            required_names & mode_specific_only, set(),
            "these packages are only needed by specific launch modes and "
            "must not block every mode via REQUIRED_PACKAGES",
        )

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
