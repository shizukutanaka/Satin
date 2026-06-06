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


if __name__ == "__main__":
    unittest.main()
