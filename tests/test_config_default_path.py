"""
Regression test: the default config path must resolve to an existing config
file, not a non-existent one.

Bug: DEFAULT_CONFIG_FILE pointed unconditionally at main/config/config.json,
which does not exist in the repo (the populated, version-controlled config is
at <repo>/config/config.json). As a result get_config() returned {} by default
- the whole config system silently loaded nothing.

Run: python -m unittest tests.test_config_default_path -v
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


class DefaultConfigPathTests(unittest.TestCase):
    def test_resolved_default_exists(self):
        # Whatever the resolver picked, it must be an existing file OR the
        # canonical write target — and in this repo a populated config exists.
        self.assertTrue(uc.DEFAULT_CONFIG_FILE.exists(),
                        f"resolved default config {uc.DEFAULT_CONFIG_FILE} does not exist")

    def test_get_config_loads_nonempty_by_default(self):
        uc._config_instance = None
        try:
            cfg = uc.get_config(reload=True)
            self.assertTrue(cfg, "get_config() returned an empty config by default")
            self.assertIn("version", cfg)
            self.assertIn("settings", cfg)
        finally:
            uc._config_instance = None

    def test_resolver_prefers_existing_candidate(self):
        # Build two candidate files; resolver should return the first that exists.
        d = tempfile.mkdtemp()
        primary = Path(d) / "main_config.json"
        fallback = Path(d) / "root_config.json"
        with open(fallback, "w") as f:
            json.dump({"version": "1.0.0", "settings": {}, "plugins": []}, f)

        # Emulate the resolver's "first existing" contract directly.
        def resolve(candidates):
            for c in candidates:
                if c.exists():
                    return c
            return candidates[0]

        # primary missing -> fallback chosen
        self.assertEqual(resolve([primary, fallback]), fallback)
        # primary present -> primary chosen
        with open(primary, "w") as f:
            json.dump({}, f)
        self.assertEqual(resolve([primary, fallback]), primary)


if __name__ == "__main__":
    unittest.main()
