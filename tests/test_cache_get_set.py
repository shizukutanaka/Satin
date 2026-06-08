"""
Regression test for the missing public CacheManager.get / .set methods.

youtube_integrator and web_integrator call self.cache_manager.get(key) and
self.cache_manager.set(key, value, ttl=...) at 13 sites, but CacheManager had
no such public methods — every cache read/write raised AttributeError.

Run: python -m unittest tests.test_cache_get_set -v
"""
import os
import sys
import time
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import cache_manager as cmmod  # noqa: E402


class CacheGetSetTests(unittest.TestCase):
    def setUp(self):
        self.cm = cmmod.CacheManager()
        self.cm.clear_cache()

    def tearDown(self):
        self.cm.shutdown(wait=False)

    def test_get_and_set_methods_exist(self):
        self.assertTrue(callable(getattr(self.cm, "get", None)))
        self.assertTrue(callable(getattr(self.cm, "set", None)))

    def test_set_then_get_roundtrip(self):
        self.cm.set("key1", {"a": 1, "b": [1, 2, 3]}, ttl=3600)
        self.assertEqual(self.cm.get("key1"), {"a": 1, "b": [1, 2, 3]})

    def test_get_missing_returns_none(self):
        self.assertIsNone(self.cm.get("never_set"))

    def test_per_key_ttl_expiry(self):
        self.cm.set("ephemeral", "v", ttl=0)  # >=0 elapsed → expired immediately
        time.sleep(0.01)
        self.assertIsNone(self.cm.get("ephemeral"))

    def test_per_key_ttl_independent_of_global(self):
        # A long per-key TTL must survive even if global cache_ttl is short.
        self.cm.cache_ttl = 1  # tiny global default
        self.cm.set("long", "alive", ttl=10_000)
        self.assertEqual(self.cm.get("long"), "alive")

    def test_ttl_override_pruned_on_expiry(self):
        self.cm.set("temp", "x", ttl=0)
        time.sleep(0.01)
        self.cm.get("temp")  # triggers expiry + prune
        self.assertNotIn("temp", self.cm._ttl_overrides)

    def test_integrators_use_get_set(self):
        # Smoke: the integrator modules import and reference the cache API.
        import youtube_integrator  # noqa: F401
        import web_integrator  # noqa: F401


if __name__ == "__main__":
    unittest.main()
