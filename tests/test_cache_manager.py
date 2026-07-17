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


class CacheManagerDeleteTests(unittest.TestCase):
    """Tests for the new CacheManager.delete() method."""

    def setUp(self):
        import cache_manager
        self.cm = cache_manager.CacheManager()
        self.cm.clear_cache()

    def tearDown(self):
        self.cm.shutdown(wait=True)

    def test_delete_removes_existing_entry(self):
        self.cm.set("to_delete", "value")
        self.cm.delete("to_delete")
        self.assertIsNone(self.cm.get("to_delete"))

    def test_delete_nonexistent_key_does_not_raise(self):
        try:
            self.cm.delete("no_such_key")
        except Exception as exc:
            self.fail(f"delete() on missing key raised {exc}")

    def test_delete_does_not_affect_other_keys(self):
        self.cm.set("keep", "safe")
        self.cm.set("remove", "gone")
        self.cm.delete("remove")
        self.assertEqual(self.cm.get("keep"), "safe")


class CleanupDiskCacheTests(unittest.TestCase):
    """_cleanup_disk_cache must not call stat() after unlink() (FileNotFoundError)."""

    def setUp(self):
        import cache_manager
        self.cm = cache_manager.CacheManager()
        self.cm.clear_cache()

    def tearDown(self):
        self.cm.shutdown(wait=True)

    def test_cleanup_does_not_raise_on_size_eviction(self):
        """Regression: stat() after unlink() used to raise FileNotFoundError
        when a cache file was evicted because total size exceeded disk_cache_size."""
        import json, time
        # Write two small cache files manually into the cache dir.
        for i in range(3):
            p = self.cm.cache_dir / f"test_file_{i}.json"
            p.write_text(json.dumps({"value": "x" * 100,
                                     "timestamp": "2099-01-01T00:00:00"}),
                         encoding="utf-8")

        # Set a tiny limit so the cleanup loop deletes files by size.
        orig = self.cm.disk_cache_size
        self.cm.disk_cache_size = 1  # 1 byte — forces eviction
        try:
            # Must not raise FileNotFoundError
            self.cm._cleanup_disk_cache()
        finally:
            self.cm.disk_cache_size = orig


class ThreadSafetyTests(unittest.TestCase):
    """Regression: memory_cache / _ttl_overrides were mutated by the cleanup
    daemon thread and the main thread without a lock, causing KeyError /
    'dictionary changed size during iteration' under concurrency."""

    def setUp(self):
        import cache_manager
        self.cm = cache_manager.CacheManager()
        self.cm.clear_cache()

    def tearDown(self):
        self.cm.shutdown(wait=True)

    def test_concurrent_set_get_clear_does_not_raise(self):
        import threading

        errors = []

        def writer():
            try:
                for i in range(500):
                    self.cm.set(f"k{i % 50}", i, ttl=1)
            except Exception as e:  # pragma: no cover - failure path
                errors.append(("writer", e))

        def reader():
            try:
                for i in range(500):
                    self.cm.get(f"k{i % 50}")
            except Exception as e:  # pragma: no cover
                errors.append(("reader", e))

        def cleaner():
            try:
                for _ in range(50):
                    self.cm._cleanup_memory_cache()
                    self.cm.clear_expired_cache()
            except Exception as e:  # pragma: no cover
                errors.append(("cleaner", e))

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=cleaner),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(errors, [], f"concurrent access raised: {errors}")

    def test_cache_lock_exists(self):
        import threading as _t
        self.assertIsInstance(self.cm._cache_lock, type(_t.Lock()))


if __name__ == "__main__":
    unittest.main()
