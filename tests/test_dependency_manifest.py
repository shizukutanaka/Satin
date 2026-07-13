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


class RequirementsTxtSyncTests(unittest.TestCase):
    """setup/requirements.txt must actually install every package the manifest
    declares (research: commercial-quality packaging audit). Regression for a
    real gap found in the audit — PyQt5/PyOpenGL power the flagship 3D avatar
    GUI (dependency_manifest.OPTIONAL_PACKAGES + 10+ main/ modules import
    OpenGL) but were missing from setup/requirements.txt, so following
    `pip install -r setup/requirements.txt` from the README left the GUI
    unusable. This asserts every manifest package name (derived from its pip
    hint) appears in requirements.txt, so the two can't silently drift again."""

    @classmethod
    def setUpClass(cls):
        req_path = os.path.join(_ROOT, "setup", "requirements.txt")
        with open(req_path, encoding="utf-8") as f:
            cls._requirements_text = f.read().lower()

    def _pip_names_from_manifest(self):
        names = []
        for _import_name, hint, _purpose in M.OPTIONAL_PACKAGES:
            prefix = "pip install "
            self.assertTrue(hint.startswith(prefix), f"unexpected pip hint format: {hint}")
            names.append(hint[len(prefix):].strip())
        return names

    def test_every_optional_package_listed_in_requirements_txt(self):
        missing = [
            name for name in self._pip_names_from_manifest()
            if name.lower() not in self._requirements_text
        ]
        self.assertEqual(missing, [], f"manifest packages missing from setup/requirements.txt: {missing}")

    def test_pyqt5_and_pyopengl_present(self):
        # The flagship 3D avatar GUI's two core deps, named explicitly so a
        # future refactor of the generic check above still catches this case.
        self.assertIn("pyqt5", self._requirements_text)
        self.assertIn("pyopengl", self._requirements_text)


class StalePlatformRequirementsRemovedTests(unittest.TestCase):
    """setup/win/requirements.txt and setup/mac/requirements.txt used to list
    `tkinter`, which is not a PyPI package — `pip install -r` on either file
    always failed. They duplicated (and drifted from) setup/requirements.txt,
    so they were removed in favor of the single root file. Regression: they
    must not silently reappear."""

    def test_stale_per_os_requirements_files_absent(self):
        for rel in ("setup/win/requirements.txt", "setup/mac/requirements.txt"):
            self.assertFalse(
                os.path.exists(os.path.join(_ROOT, rel)),
                f"{rel} should not exist — it duplicated setup/requirements.txt "
                f"and listed non-pip-installable 'tkinter'",
            )


if __name__ == "__main__":
    unittest.main()
