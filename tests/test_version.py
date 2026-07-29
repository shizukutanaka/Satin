"""
Tests for the version single-source (W-03).

There must be exactly one code-side version declaration (main/version.py),
it must be a valid semver, and it must match config/config.json "version"
so the two never drift.
"""
import json
import os
import re
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MAIN = os.path.join(_ROOT, "main")
sys.path.insert(0, _MAIN)
sys.path.insert(0, _ROOT)

import version  # noqa: E402


class VersionTests(unittest.TestCase):
    def test_version_is_semver(self):
        self.assertRegex(version.__version__, r"^\d+\.\d+\.\d+$")

    def test_get_version_matches_constant(self):
        self.assertEqual(version.get_version(), version.__version__)

    def test_matches_config_json(self):
        with open(os.path.join(_ROOT, "config", "config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        self.assertEqual(
            cfg.get("version"), version.__version__,
            "main/version.py and config/config.json version drifted apart",
        )


class LauncherVersionFlagTests(unittest.TestCase):
    def test_version_flag_prints_and_exits(self):
        import satin_launcher
        from unittest import mock
        with mock.patch("sys.argv", ["satin_launcher", "--version"]):
            with self.assertRaises(SystemExit) as cm:
                satin_launcher.main()
            # argparse's version action exits 0
            self.assertEqual(cm.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
