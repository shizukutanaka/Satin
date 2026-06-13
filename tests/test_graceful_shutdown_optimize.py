"""
Stdlib-only regression tests for graceful_shutdown.py and optimize.py.

Run: python -m unittest tests.test_graceful_shutdown_optimize -v
"""
import asyncio
import os
import sys
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)


class GracefulShutdownTests(unittest.TestCase):
    def test_unregister_task_no_crash_when_not_registered(self):
        # list.discard() doesn't exist — was AttributeError before fix
        import graceful_shutdown as gs
        mgr = gs.GracefulShutdownManager()

        async def _fake():
            pass

        loop = asyncio.new_event_loop()
        try:
            task = loop.create_task(_fake())
            loop.run_until_complete(task)  # consume the coroutine (no unawaited warning)
            # unregister_task on an unknown task must not raise
            mgr.unregister_task(task)
            # also works if registered first
            mgr.register_task(task)
            mgr.unregister_task(task)
            self.assertEqual(mgr.active_tasks, [])
        finally:
            loop.close()

    def test_register_cleanup_and_shutdown(self):
        import graceful_shutdown as gs
        mgr = gs.GracefulShutdownManager(shutdown_timeout=1.0)
        called = []
        mgr.register_cleanup("test", lambda: called.append(1))

        async def _run():
            await mgr.shutdown("TEST")

        asyncio.run(_run())
        self.assertEqual(called, [1])


class OptimizeImportTests(unittest.TestCase):
    def test_imports_without_optional_deps(self):
        # Previously crashed because aiofiles/numpy/sklearn were imported unconditionally
        import optimize  # must not raise ModuleNotFoundError
        self.assertTrue(hasattr(optimize, "PerformanceMonitor"))

    def test_get_metrics_empty_no_zerodivision(self):
        import optimize
        mon = optimize.PerformanceMonitor()
        # get_metrics on empty metrics must return {} without ZeroDivisionError
        result = mon.get_metrics()
        self.assertIsInstance(result, dict)

    def test_record_and_get_metrics(self):
        import optimize
        mon = optimize.PerformanceMonitor()
        mon.record_metric("latency", 0.1)
        mon.record_metric("latency", 0.2)
        metrics = mon.get_metrics()
        self.assertIn("latency", metrics)
        self.assertEqual(metrics["latency"]["count"], 2)
        self.assertAlmostEqual(metrics["latency"]["avg"], 0.15)


class PerformanceMonitorTests(unittest.TestCase):
    def test_imports_without_psutil(self):
        import performance_monitor as pm
        self.assertTrue(hasattr(pm, "PerformanceMonitor"))

    def test_instantiation_without_settings(self):
        # Previously AttributeError: 'PerformanceMonitor' has no 'interval' when
        # plugin config returns None and all attrs were inside if self.settings:
        import performance_monitor as pm
        mon = pm.PerformanceMonitor()
        # All required attrs must exist with defaults
        self.assertIsNotNone(mon.interval)
        self.assertIsInstance(mon.thresholds, dict)
        self.assertFalse(mon.running)


class AsyncContextResourceTests(unittest.TestCase):
    def test_sync_init_and_cleanup(self):
        log = []
        resource = {"value": 42}

        resource_ref = []

        async def run():
            import graceful_shutdown as gs
            ctx = gs.AsyncContextResource(
                "test_res",
                init_func=lambda: resource,
                cleanup_func=lambda r: log.append(("cleanup", r)),
            )
            async with ctx as res:
                resource_ref.append(res)
            return res

        result = asyncio.run(run())
        self.assertEqual(result["value"], 42)
        self.assertEqual(log, [("cleanup", resource)])

    def test_async_init_supported(self):
        resource = [1, 2, 3]

        async def run():
            import graceful_shutdown as gs

            async def async_init():
                return resource

            ctx = gs.AsyncContextResource(
                "async_res",
                init_func=async_init,
                cleanup_func=lambda r: None,
            )
            async with ctx as res:
                return res

        result = asyncio.run(run())
        self.assertIs(result, resource)

    def test_registers_cleanup_with_shutdown_manager(self):
        async def run():
            import graceful_shutdown as gs
            mgr = gs.GracefulShutdownManager()
            ctx = gs.AsyncContextResource(
                "managed_res",
                init_func=lambda: object(),
                cleanup_func=lambda r: None,
                shutdown_manager=mgr,
            )
            async with ctx:
                pass
            return len(mgr.cleanup_handlers)

        count = asyncio.run(run())
        self.assertEqual(count, 1)


class GracefulShutdownHealthCheckerTests(unittest.TestCase):
    def test_all_checks_pass_returns_healthy(self):
        async def run():
            import graceful_shutdown as gs
            mgr = gs.GracefulShutdownManager()
            checker = gs.HealthChecker(mgr)
            checker.register_check("db", lambda: True)
            return await checker.check()

        result = asyncio.run(run())
        self.assertTrue(result.is_healthy)
        self.assertEqual(result.message, "Healthy")

    def test_failing_check_returns_unhealthy(self):
        async def run():
            import graceful_shutdown as gs
            mgr = gs.GracefulShutdownManager()
            checker = gs.HealthChecker(mgr)
            checker.register_check("db", lambda: False)
            return await checker.check()

        result = asyncio.run(run())
        self.assertFalse(result.is_healthy)

    def test_shutting_down_returns_unhealthy(self):
        async def run():
            import graceful_shutdown as gs
            mgr = gs.GracefulShutdownManager()
            mgr.is_shutting_down = True
            checker = gs.HealthChecker(mgr)
            checker.register_check("x", lambda: True)
            return await checker.check()

        result = asyncio.run(run())
        self.assertFalse(result.is_healthy)
        self.assertEqual(result.message, "Shutting down")

    def test_check_exception_treated_as_false(self):
        async def run():
            import graceful_shutdown as gs
            mgr = gs.GracefulShutdownManager()
            checker = gs.HealthChecker(mgr)

            def broken():
                raise RuntimeError("db unreachable")

            checker.register_check("db", broken)
            return await checker.check()

        result = asyncio.run(run())
        self.assertFalse(result.is_healthy)
        self.assertFalse(result.checks["db"])

    def test_result_has_checks_dict(self):
        async def run():
            import graceful_shutdown as gs
            mgr = gs.GracefulShutdownManager()
            checker = gs.HealthChecker(mgr)
            checker.register_check("cache", lambda: True)
            return await checker.check()

        result = asyncio.run(run())
        self.assertIn("cache", result.checks)
        self.assertTrue(result.checks["cache"])


if __name__ == "__main__":
    unittest.main()
