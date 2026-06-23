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


class FindHandlerMROTests(unittest.TestCase):
    """Regression: _find_handler must walk exc_type.__mro__ so subclass-specific
    handlers are reached before their parent class handlers.

    Before the fix, ErrorHandler._handlers was iterated in insertion order and
    the first issubclass() match was returned.  SatinError was registered before
    RetryableError/ValidationError, so those subclass handlers were dead code.
    """

    def setUp(self):
        from error_handling import ErrorHandler, SatinError, RetryableError, ValidationError
        self.eh = ErrorHandler.__new__(ErrorHandler)
        self.eh.log_file = "/dev/null"
        self.eh._handlers = {}
        # Register handlers in parent-first order (reproduces pre-fix registration order)
        self.eh.register_handler(SatinError, lambda e: "satin")
        self.eh.register_handler(RetryableError, lambda e: "retryable")
        self.eh.register_handler(ValidationError, lambda e: "validation")
        self.eh.register_handler(Exception, lambda e: "generic")

    def test_retryable_error_uses_specific_handler(self):
        from error_handling import RetryableError
        result = self.eh._find_handler(RetryableError)
        self.assertEqual(result(None), "retryable",
                         "_find_handler must pick RetryableError handler, not SatinError handler")

    def test_validation_error_uses_specific_handler(self):
        from error_handling import ValidationError
        result = self.eh._find_handler(ValidationError)
        self.assertEqual(result(None), "validation",
                         "_find_handler must pick ValidationError handler, not SatinError handler")

    def test_satin_error_uses_satin_handler(self):
        from error_handling import SatinError
        result = self.eh._find_handler(SatinError)
        self.assertEqual(result(None), "satin")

    def test_unknown_exception_falls_back_to_generic(self):
        from error_handling import ErrorHandler
        result = self.eh._find_handler(FileNotFoundError)
        # FileNotFoundError -> OSError -> Exception -> object; Exception is registered
        self.assertEqual(result(None), "generic")

    def test_unregistered_exc_returns_default_generic_handler(self):
        """If no ancestor is registered at all, returns _handle_generic_error fallback."""
        from error_handling import ErrorHandler
        eh = ErrorHandler.__new__(ErrorHandler)
        eh._handlers = {}
        handler = eh._find_handler(ValueError)
        self.assertTrue(callable(handler))


class IntegratorImportTests(unittest.TestCase):
    def test_async_integrator_imports_without_httpx(self):
        import async_integrator  # noqa: F401  (was NameError: httpx)

    def test_web_integrator_imports(self):
        import web_integrator  # noqa: F401  (was TypeError: 'dict' not callable)

    def test_youtube_integrator_imports(self):
        import youtube_integrator  # noqa: F401  (was ImportError: ErrorContext)


if __name__ == "__main__":
    unittest.main()
