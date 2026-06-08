"""
Regression test for the missing LoggingManager.get_logger classmethod.

async_integrator / content_aggregator / web_integrator / youtube_integrator all
call LoggingManager.get_logger("name") at instantiation. Before the fix this
raised AttributeError because the method did not exist on the class.

Run: python -m unittest tests.test_logging_manager_get_logger -v
"""
import logging
import os
import sys
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)


class GetLoggerTests(unittest.TestCase):
    def test_get_logger_exists_and_returns_logger(self):
        from logging_manager import LoggingManager
        log = LoggingManager.get_logger("satin.test")
        self.assertIsInstance(log, logging.Logger)
        self.assertEqual(log.name, "satin.test")

    def test_get_logger_is_callable_without_instance(self):
        # Must work as a static/class method (no LoggingManager() instance needed,
        # which would touch config + spawn a compression thread).
        from logging_manager import LoggingManager
        self.assertTrue(callable(LoggingManager.get_logger))

    def test_integrators_obtain_loggers(self):
        # Smoke test: the modules that depend on get_logger must import.
        import youtube_integrator
        import web_integrator
        import content_aggregator
        import async_integrator
        # Each exposes its main class; confirm one to be safe
        self.assertTrue(hasattr(youtube_integrator, "YouTubeIntegrator"))
        self.assertTrue(hasattr(web_integrator, "WebIntegrator"))


if __name__ == "__main__":
    unittest.main()
