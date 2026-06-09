"""
Stdlib-only regression tests for the fixes in main/memory_safety.py.

Run: python -m unittest tests.test_memory_safety -v
"""
import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main.memory_safety import MemoryWatcher, WeakReferencedCache, manage_resources  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
