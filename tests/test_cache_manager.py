"""
Stdlib-only regression tests for the fixes in main/cache_manager.py and the
config_manager import fix.

cache_manager uses top-level imports (`from config_manager import ...`), so we
put main/ on sys.path and import it as a top-level module.

Run: python -m unittest tests.test_cache_manager -v
"""
import asyncio
import os
import sys
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)


class ConfigManagerImportTests(unittest.TestCase):
    def test_config_manager_imports(self):
        # Previously raised NameError: name 'List' is not defined at import time.
        import config_manager  # noqa: F401
        self.assertTrue(hasattr(config_manager, "ConfigManager"))


class CacheManagerDecoratorTests(unittest.TestCase):
    def setUp(self):
        import cache_manager
        self.cm = cache_manager.CacheManager()
        # Start from a clean slate (disk cache persists across runs now that keys
        # are stable, which would otherwise pre-warm these test values).
        self.cm.clear_cache()

    def tearDown(self):
        self.cm.shutdown(wait=True)

    def test_repeated_hit_does_not_reuse_coroutine(self):
        calls = {"n": 0}

        @self.cm.cache
        async def compute(x):
            calls["n"] += 1
            return x * 2

        async def main():
            first = await compute(5)
            second = await compute(5)  # was RuntimeError with @lru_cache on async
            third = await compute(7)
            return first, second, third

        first, second, third = asyncio.run(main())
        self.assertEqual((first, second, third), (10, 10, 14))
        self.assertEqual(calls["n"], 2)  # x=5 cached, only x=5 and x=7 computed

    def test_cache_key_is_stable(self):
        k1 = self.cm._generate_cache_key("f", (1, "x"), {"a": 1})
        k2 = self.cm._generate_cache_key("f", (1, "x"), {"a": 1})
        self.assertEqual(k1, k2)
        self.assertTrue(k1.startswith("f_"))


class CacheManagerGetSetTests(unittest.TestCase):
    def setUp(self):
        import cache_manager
        self.cm = cache_manager.CacheManager()
        self.cm.clear_cache()

    def tearDown(self):
        self.cm.shutdown(wait=True)

    def test_set_and_get_returns_value(self):
        self.cm.set("key1", "hello")
        self.assertEqual(self.cm.get("key1"), "hello")

    def test_get_missing_key_returns_none(self):
        self.assertIsNone(self.cm.get("nonexistent"))

    def test_set_overwrite_updates_value(self):
        self.cm.set("k", 1)
        self.cm.set("k", 2)
        self.assertEqual(self.cm.get("k"), 2)

    def test_clear_cache_removes_all(self):
        self.cm.set("a", 1)
        self.cm.set("b", 2)
        self.cm.clear_cache()
        self.assertIsNone(self.cm.get("a"))
        self.assertIsNone(self.cm.get("b"))

    def test_per_key_ttl_expires(self):
        self.cm.set("k", "val", ttl=0)  # 0-second TTL expires immediately
        import time; time.sleep(0.01)
        self.assertIsNone(self.cm.get("k"))

    def test_get_cache_stats_returns_dict(self):
        stats = self.cm.get_cache_stats()
        self.assertIsInstance(stats, dict)

    def test_get_cache_summary_has_expected_keys(self):
        summary = self.cm.get_cache_summary()
        for key in ("memory_items", "disk_files"):
            self.assertIn(key, summary)


class CacheStatsTests(unittest.TestCase):
    def setUp(self):
        import cache_manager
        self.stats = cache_manager.CacheStats()

    def test_initial_state(self):
        stats = self.stats.get_stats()
        self.assertEqual(stats["total_requests"], 0)
        self.assertEqual(stats["hit_rate"], 0)

    def test_record_hit_increments(self):
        self.stats.record_hit(5.0)
        self.assertEqual(self.stats.hits, 1)

    def test_record_miss_increments(self):
        self.stats.record_miss(3.0)
        self.assertEqual(self.stats.misses, 1)

    def test_hit_rate_computed(self):
        self.stats.record_hit(1.0)
        self.stats.record_miss(1.0)
        stats = self.stats.get_stats()
        self.assertAlmostEqual(stats["hit_rate"], 50.0)

    def test_zero_total_returns_zero_hit_rate(self):
        stats = self.stats.get_stats()
        self.assertEqual(stats["hit_rate"], 0)

    def test_avg_latency_computed(self):
        self.stats.record_hit(10.0)
        self.stats.record_hit(20.0)
        stats = self.stats.get_stats()
        self.assertAlmostEqual(stats["average_latency"], 15.0)


if __name__ == "__main__":
    unittest.main()
