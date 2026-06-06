"""
Regression tests for the import-time / shadowing fixes:
- error_handling.handle_error must be the decorator factory (was shadowed by a
  second definition that returned a dict -> '@handle_error(...)' raised
  TypeError: 'dict' object is not callable).
- async_integrator / youtube_integrator / web_integrator must import.

Run: python -m unittest tests.test_error_handling -v
"""
import os
import sys
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)


class HandleErrorDecoratorTests(unittest.TestCase):
    def test_handle_error_is_decorator_factory(self):
        import error_handling as eh
        from error_handling import handle_error, RetryStrategy

        @handle_error(RetryStrategy(max_retries=2))
        def add(a, b):
            return a + b

        # If handle_error were the shadowing dict-returning function, defining the
        # decorated function above would have raised TypeError at decoration time.
        self.assertEqual(add(2, 3), 5)
        # The renamed global helper still exists.
        self.assertTrue(hasattr(eh, "handle_global_error"))

    def test_handle_error_retries_then_succeeds(self):
        from error_handling import handle_error, RetryStrategy

        state = {"calls": 0}

        @handle_error(RetryStrategy(max_retries=3))
        def flaky():
            state["calls"] += 1
            if state["calls"] < 2:
                raise ValueError("transient")
            return "ok"

        self.assertEqual(flaky(), "ok")
        self.assertGreaterEqual(state["calls"], 2)


class IntegratorImportTests(unittest.TestCase):
    def test_async_integrator_imports_without_httpx(self):
        import async_integrator  # noqa: F401  (was NameError: httpx)

    def test_web_integrator_imports(self):
        import web_integrator  # noqa: F401  (was TypeError: 'dict' not callable)

    def test_youtube_integrator_imports(self):
        import youtube_integrator  # noqa: F401  (was ImportError: ErrorContext)


if __name__ == "__main__":
    unittest.main()
