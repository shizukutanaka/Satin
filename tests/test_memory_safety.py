"""
Stdlib-only regression tests for the fixes in main/memory_safety.py.

Run: python -m unittest tests.test_memory_safety -v
"""
import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main.memory_safety import (  # noqa: E402
    MemoryWatcher, WeakReferencedCache, manage_resources,
    ResourceManager, GarbageCollectionOptimizer,
    MemorySafeBatchProcessor,
)


class _Obj:
    """A weak-referenceable object (str/int are not)."""


class MemoryWatcherThresholdTests(unittest.TestCase):
    def setUp(self):
        self.w = MemoryWatcher(warning_threshold=0.8, critical_threshold=0.95)

    def test_below_warning_returns_none(self):
        # 50% usage must NOT warn (previously fired CRITICAL because 50 >= 0.95).
        self.assertIsNone(self.w.check_memory({"percent": 50.0}))

    def test_warning_band(self):
        warning = self.w.check_memory({"percent": 85.0})
        self.assertIsNotNone(warning)
        self.assertEqual(warning.level, "WARNING")

    def test_critical_band(self):
        warning = self.w.check_memory({"percent": 97.0})
        self.assertIsNotNone(warning)
        self.assertEqual(warning.level, "CRITICAL")


class WeakReferencedCacheTtlTests(unittest.TestCase):
    def test_orphaned_ttl_entries_are_pruned(self):
        cache = WeakReferencedCache(max_size=100)
        # Simulate a value that was GC'd from the weak _cache but left a TTL key.
        cache._ttl_map["orphan"] = datetime.now() + timedelta(seconds=60)
        held = _Obj()
        cache.set("real", held)
        self.assertNotIn("orphan", cache._ttl_map)  # pruned -> no leak
        self.assertIn("real", cache._ttl_map)
        # _ttl_map must not exceed the live cache size by accumulation
        self.assertLessEqual(len(cache._ttl_map), len(cache._cache) + 0)


class ManageResourcesDecoratorTests(unittest.TestCase):
    """Regression: manage_resources used to be a no-op (never registered handlers)."""

    def test_cleanup_called_on_success(self):
        log = []

        @manage_resources({'conn': lambda c: log.append(('close', c))})
        def work(conn):
            return conn * 2

        result = work(conn=42)
        self.assertEqual(result, 84)
        self.assertEqual(log, [('close', 42)])

    def test_cleanup_called_on_exception(self):
        log = []

        @manage_resources({'conn': lambda c: log.append('cleaned')})
        def failing(conn):
            raise ValueError("boom")

        with self.assertRaises(ValueError):
            failing(conn='x')
        self.assertEqual(log, ['cleaned'])

    def test_no_handler_for_unregistered_kwarg(self):
        log = []

        @manage_resources({'other': lambda x: log.append(x)})
        def work(conn):
            return 1

        work(conn='ignored')
        self.assertEqual(log, [])  # 'conn' not in cleanup_handlers → nothing registered


class WeakReferencedCacheTests(unittest.TestCase):
    class _Obj:
        pass

    def test_set_and_get_returns_value(self):
        cache = WeakReferencedCache(max_size=10)
        obj = self._Obj()
        cache.set("key1", obj)
        self.assertIs(cache.get("key1"), obj)

    def test_get_missing_returns_none(self):
        cache = WeakReferencedCache(max_size=10)
        self.assertIsNone(cache.get("nonexistent"))

    def test_miss_increments_misses(self):
        cache = WeakReferencedCache(max_size=10)
        cache.get("missing")
        stats = cache.get_stats()
        self.assertEqual(stats["misses"], 1)

    def test_hit_increments_hits(self):
        cache = WeakReferencedCache(max_size=10)
        obj = self._Obj()
        cache.set("k", obj)
        cache.get("k")
        stats = cache.get_stats()
        self.assertEqual(stats["hits"], 1)

    def test_clear_resets_cache_and_stats(self):
        cache = WeakReferencedCache(max_size=10)
        obj = self._Obj()
        cache.set("k", obj)
        cache.clear()
        # After clear, size is 0 and counters reset before any get calls
        stats = cache.get_stats()
        self.assertEqual(stats["hits"], 0)
        self.assertEqual(stats["misses"], 0)
        self.assertEqual(stats["size"], 0)
        self.assertIsNone(cache.get("k"))  # get after clear = miss

    def test_get_stats_has_expected_keys(self):
        cache = WeakReferencedCache()
        stats = cache.get_stats()
        for key in ("hits", "misses", "hit_rate", "size", "max_size"):
            self.assertIn(key, stats)

    def test_hit_rate_computed(self):
        cache = WeakReferencedCache(max_size=10)
        obj = self._Obj()
        cache.set("k", obj)
        cache.get("k")  # hit
        cache.get("missing")  # miss
        self.assertAlmostEqual(cache.get_stats()["hit_rate"], 50.0)


class ResourceManagerTests(unittest.TestCase):
    def test_register_returns_resource(self):
        rm = ResourceManager()
        res = object()
        result = rm.register("r1", res, lambda x: None)
        self.assertIs(result, res)

    def test_cleanup_called_on_exit(self):
        log = []
        rm = ResourceManager()
        res = object()
        rm.register("r1", res, lambda x: log.append("cleaned"))
        with rm:
            pass
        self.assertIn("cleaned", log)

    def test_cleanup_called_on_exception(self):
        log = []
        rm = ResourceManager()
        rm.register("r1", object(), lambda x: log.append("cleaned"))
        try:
            with rm:
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        self.assertIn("cleaned", log)

    def test_enter_returns_self(self):
        rm = ResourceManager()
        result = rm.__enter__()
        self.assertIs(result, rm)
        rm.__exit__(None, None, None)


class GarbageCollectionOptimizerTests(unittest.TestCase):
    def test_get_memory_info_returns_dict(self):
        gc_opt = GarbageCollectionOptimizer()
        info = gc_opt.get_memory_info()
        self.assertIsInstance(info, dict)

    def test_disable_during_batch_does_not_raise(self):
        gc_opt = GarbageCollectionOptimizer()
        import gc
        gc.enable()  # ensure enabled before test
        gc_opt.disable_during_batch()  # should not raise
        gc_opt.enable_and_collect()  # restore state

    def test_enable_and_collect_does_not_raise(self):
        gc_opt = GarbageCollectionOptimizer()
        gc_opt.enable_and_collect()  # should not raise


class MemorySafeBatchProcessorTests(unittest.TestCase):
    def test_process_items_returns_results(self):
        processor = MemorySafeBatchProcessor(batch_size=3)
        results = processor.process_items([1, 2, 3], lambda x: x * 2)
        self.assertEqual(sorted(results), [2, 4, 6])

    def test_process_items_empty_returns_empty(self):
        processor = MemorySafeBatchProcessor(batch_size=5)
        results = processor.process_items([], lambda x: x)
        self.assertEqual(results, [])

    def test_process_items_raises_on_exception(self):
        processor = MemorySafeBatchProcessor(batch_size=2)

        def fail(x):
            raise ValueError("processing error")

        with self.assertRaises(ValueError):
            processor.process_items([1], fail)


if __name__ == "__main__":
    unittest.main()
