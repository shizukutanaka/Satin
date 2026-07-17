"""
Unit tests for graceful_shutdown — signal handling and resource cleanup.
"""
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import sys
import os
_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from graceful_shutdown import (  # noqa: E402
    GracefulShutdownManager,
    ShutdownEvent,
    SignalHandler,
    AsyncApplication,
    AsyncContextResource,
    HealthChecker,
    HealthStatus,
    with_graceful_shutdown,
)


# ---------------------------------------------------------------------------
# GracefulShutdownManager — register/unregister/shutdown
# ---------------------------------------------------------------------------

class GracefulShutdownManagerTests(unittest.IsolatedAsyncioTestCase):

    def test_register_cleanup_appends_handler(self):
        mgr = GracefulShutdownManager()
        mgr.register_cleanup("h", lambda: None)
        self.assertEqual(len(mgr.cleanup_handlers), 1)
        self.assertEqual(mgr.cleanup_handlers[0][0], "h")

    def test_unregister_cleanup_removes_handler(self):
        mgr = GracefulShutdownManager()
        mgr.register_cleanup("h", lambda: None)
        result = mgr.unregister_cleanup("h")
        self.assertTrue(result)
        self.assertEqual(len(mgr.cleanup_handlers), 0)

    def test_unregister_nonexistent_returns_false(self):
        mgr = GracefulShutdownManager()
        self.assertFalse(mgr.unregister_cleanup("ghost"))

    def test_unregister_removes_only_first_match(self):
        called = []
        mgr = GracefulShutdownManager()
        mgr.register_cleanup("dup", lambda: called.append(1))
        mgr.register_cleanup("dup", lambda: called.append(2))
        mgr.unregister_cleanup("dup")
        # One entry remains
        self.assertEqual(len(mgr.cleanup_handlers), 1)

    def test_register_task_appends(self):
        mgr = GracefulShutdownManager()
        task = MagicMock(spec=asyncio.Task)
        mgr.register_task(task)
        self.assertIn(task, mgr.active_tasks)

    def test_unregister_task_removes(self):
        mgr = GracefulShutdownManager()
        task = MagicMock(spec=asyncio.Task)
        mgr.active_tasks.append(task)
        mgr.unregister_task(task)
        self.assertNotIn(task, mgr.active_tasks)

    def test_unregister_task_not_present_is_silent(self):
        mgr = GracefulShutdownManager()
        task = MagicMock(spec=asyncio.Task)
        mgr.unregister_task(task)  # must not raise

    async def test_shutdown_runs_sync_cleanup_handlers_in_order(self):
        mgr = GracefulShutdownManager()
        called = []
        mgr.register_cleanup("h1", lambda: called.append("h1"))
        mgr.register_cleanup("h2", lambda: called.append("h2"))
        await mgr.shutdown("TEST")
        self.assertEqual(called, ["h1", "h2"])

    async def test_shutdown_runs_async_cleanup_handler(self):
        mgr = GracefulShutdownManager()
        called = []

        async def async_h():
            called.append("async")

        mgr.register_cleanup("async_h", async_h)
        await mgr.shutdown("TEST")
        self.assertEqual(called, ["async"])

    async def test_shutdown_sets_event(self):
        mgr = GracefulShutdownManager()
        await mgr.shutdown("TEST")
        self.assertTrue(mgr.shutdown_event.is_set())

    async def test_shutdown_is_idempotent(self):
        mgr = GracefulShutdownManager()
        called = []
        mgr.register_cleanup("h", lambda: called.append("h"))
        await mgr.shutdown("FIRST")
        await mgr.shutdown("SECOND")  # must not re-run handlers
        self.assertEqual(called, ["h"])

    async def test_cleanup_exception_does_not_stop_subsequent_handlers(self):
        mgr = GracefulShutdownManager()
        called = []

        def boom():
            raise RuntimeError("boom")

        mgr.register_cleanup("boom", boom)
        mgr.register_cleanup("ok", lambda: called.append("ok"))
        await mgr.shutdown("TEST")
        self.assertEqual(called, ["ok"])

    async def test_async_cleanup_timeout_does_not_stop_others(self):
        mgr = GracefulShutdownManager(shutdown_timeout=0.1)
        called = []

        async def slow():
            await asyncio.sleep(10)  # will timeout

        async def fast():
            called.append("fast")

        mgr.register_cleanup("slow", slow)
        mgr.register_cleanup("fast", fast)
        await mgr.shutdown("TEST")
        self.assertIn("fast", called)

    async def test_cancel_active_tasks_on_shutdown(self):
        mgr = GracefulShutdownManager()

        async def forever():
            await asyncio.sleep(9999)

        task = asyncio.create_task(forever())
        mgr.register_task(task)
        await mgr.shutdown("TEST")
        self.assertTrue(task.cancelled() or task.done())

    async def test_shutdown_with_no_handlers_no_crash(self):
        mgr = GracefulShutdownManager()
        await mgr.shutdown("EMPTY")  # must not raise


# ---------------------------------------------------------------------------
# Regression: list-mutation-during-async-iteration
# If an async handler calls unregister_cleanup for a later handler,
# the later handler must still be called (snapshot-based iteration).
# ---------------------------------------------------------------------------

class CleanupListSnapshotTests(unittest.IsolatedAsyncioTestCase):

    async def test_handler_added_during_cleanup_not_invoked(self):
        """Handlers registered AFTER shutdown starts should NOT be called."""
        mgr = GracefulShutdownManager()
        called = []
        late_called = []

        async def h1():
            called.append("h1")
            mgr.register_cleanup("late", lambda: late_called.append("late"))

        mgr.register_cleanup("h1", h1)
        await mgr.shutdown("TEST")
        self.assertIn("h1", called)
        self.assertEqual(late_called, [],
                         "handler registered DURING cleanup must not be called")

    async def test_handler_unregistered_by_earlier_handler_is_still_called(self):
        """Handlers that unregister a sibling must not silently skip it.

        Without the snapshot fix, a handler at index i removing handler at
        index i+1 would shift the list so the next index jump skips it.
        The snapshot ensures all handlers captured at shutdown time run.
        """
        mgr = GracefulShutdownManager()
        called = []

        def h1():
            called.append("h1")
            mgr.unregister_cleanup("h2")  # sabotage the next handler

        def h2():
            called.append("h2")

        mgr.register_cleanup("h1", h1)
        mgr.register_cleanup("h2", h2)
        await mgr.shutdown("TEST")
        self.assertEqual(called, ["h1", "h2"],
                         "h2 must still run even if h1 unregistered it")


# ---------------------------------------------------------------------------
# with_graceful_shutdown decorator
# ---------------------------------------------------------------------------

class WithGracefulShutdownDecoratorTests(unittest.IsolatedAsyncioTestCase):

    async def test_registers_current_task(self):
        mgr = GracefulShutdownManager()
        registered = []
        orig_register = mgr.register_task

        def spy_register(t):
            registered.append(t)
            orig_register(t)

        mgr.register_task = spy_register

        @with_graceful_shutdown(mgr)
        async def job():
            pass

        await job()
        self.assertEqual(len(registered), 1)

    async def test_unregisters_after_completion(self):
        mgr = GracefulShutdownManager()

        @with_graceful_shutdown(mgr)
        async def job():
            pass

        await job()
        self.assertEqual(len(mgr.active_tasks), 0)

    async def test_unregisters_even_after_exception(self):
        mgr = GracefulShutdownManager()

        @with_graceful_shutdown(mgr)
        async def boom():
            raise ValueError("test")

        with self.assertRaises(ValueError):
            await boom()
        self.assertEqual(len(mgr.active_tasks), 0)

    async def test_return_value_preserved(self):
        mgr = GracefulShutdownManager()

        @with_graceful_shutdown(mgr)
        async def job():
            return 42

        result = await job()
        self.assertEqual(result, 42)


# ---------------------------------------------------------------------------
# AsyncContextResource
# ---------------------------------------------------------------------------

class AsyncContextResourceTests(unittest.IsolatedAsyncioTestCase):

    async def test_init_calls_init_func(self):
        resource_holder = []
        r = AsyncContextResource("r", lambda: resource_holder.append("init") or "res",
                                 lambda res: None)
        async with r as res:
            self.assertEqual(res, "res")
        self.assertIn("init", resource_holder)

    async def test_exit_calls_cleanup_func(self):
        cleaned = []
        r = AsyncContextResource("r", lambda: "res",
                                 lambda res: cleaned.append(res))
        async with r:
            pass
        self.assertEqual(cleaned, ["res"])

    async def test_exit_calls_async_cleanup_func(self):
        cleaned = []

        async def async_cleanup(res):
            cleaned.append(res)

        r = AsyncContextResource("r", lambda: "res", async_cleanup)
        async with r:
            pass
        self.assertEqual(cleaned, ["res"])

    async def test_exit_with_exception_still_cleans_up(self):
        cleaned = []
        r = AsyncContextResource("r", lambda: "res",
                                 lambda res: cleaned.append(res))
        with self.assertRaises(ValueError):
            async with r:
                raise ValueError("oops")
        self.assertEqual(cleaned, ["res"])

    async def test_registers_with_shutdown_manager(self):
        mgr = GracefulShutdownManager()
        r = AsyncContextResource("r", lambda: "res", lambda res: None, mgr)
        async with r:
            self.assertEqual(len(mgr.cleanup_handlers), 1)
        # After normal exit, unregistered
        self.assertEqual(len(mgr.cleanup_handlers), 0)

    async def test_unregisters_from_shutdown_manager_on_normal_exit(self):
        mgr = GracefulShutdownManager()
        r = AsyncContextResource("r", lambda: "res", lambda res: None, mgr)
        async with r:
            pass
        self.assertEqual(mgr.cleanup_handlers, [],
                         "handler must be unregistered to prevent double cleanup")

    async def test_no_crash_with_falsy_but_valid_resource(self):
        """A resource that is falsy (e.g., 0) must still be cleaned up."""
        cleaned = []
        r = AsyncContextResource("r", lambda: 0,
                                 lambda res: cleaned.append(res))
        async with r:
            pass
        self.assertEqual(cleaned, [0])


# ---------------------------------------------------------------------------
# HealthChecker
# ---------------------------------------------------------------------------

class HealthCheckerTests(unittest.IsolatedAsyncioTestCase):

    async def test_all_checks_pass_is_healthy(self):
        mgr = GracefulShutdownManager()
        hc = HealthChecker(mgr)
        hc.register_check("ok", lambda: True)
        status = await hc.check()
        self.assertTrue(status.is_healthy)
        self.assertEqual(status.message, "Healthy")

    async def test_one_check_fails_is_unhealthy(self):
        mgr = GracefulShutdownManager()
        hc = HealthChecker(mgr)
        hc.register_check("ok", lambda: True)
        hc.register_check("fail", lambda: False)
        status = await hc.check()
        self.assertFalse(status.is_healthy)
        self.assertIn("fail", status.message)

    async def test_during_shutdown_is_unhealthy(self):
        mgr = GracefulShutdownManager()
        mgr.is_shutting_down = True
        hc = HealthChecker(mgr)
        hc.register_check("ok", lambda: True)
        status = await hc.check()
        self.assertFalse(status.is_healthy)
        self.assertIn("Shutting down", status.message)

    async def test_async_check_is_awaited(self):
        mgr = GracefulShutdownManager()
        hc = HealthChecker(mgr)
        called = []

        async def async_check():
            called.append(True)
            return True

        hc.register_check("async", async_check)
        await hc.check()
        self.assertEqual(called, [True])

    async def test_check_exception_yields_unhealthy(self):
        mgr = GracefulShutdownManager()
        hc = HealthChecker(mgr)

        def boom():
            raise RuntimeError("db down")

        hc.register_check("db", boom)
        status = await hc.check()
        self.assertFalse(status.is_healthy)
        self.assertFalse(status.checks["db"])

    async def test_check_timeout_yields_unhealthy(self):
        import graceful_shutdown as _gs
        mgr = GracefulShutdownManager()
        hc = HealthChecker(mgr)

        async def check():
            return True

        hc.register_check("slow", check)

        async def fake_wait_for(coro, timeout):
            coro.close()  # prevent "coroutine never awaited" warning
            raise asyncio.TimeoutError()

        with patch.object(_gs.asyncio, "wait_for", fake_wait_for):
            status = await hc.check()
        self.assertFalse(status.checks["slow"])

    async def test_no_checks_is_healthy(self):
        mgr = GracefulShutdownManager()
        hc = HealthChecker(mgr)
        status = await hc.check()
        self.assertTrue(status.is_healthy)

    async def test_status_has_timestamp(self):
        mgr = GracefulShutdownManager()
        hc = HealthChecker(mgr)
        status = await hc.check()
        self.assertIsNotNone(status.timestamp)

    async def test_status_includes_all_check_names(self):
        mgr = GracefulShutdownManager()
        hc = HealthChecker(mgr)
        hc.register_check("alpha", lambda: True)
        hc.register_check("beta", lambda: False)
        status = await hc.check()
        self.assertIn("alpha", status.checks)
        self.assertIn("beta", status.checks)


# ---------------------------------------------------------------------------
# ShutdownEvent dataclass
# ---------------------------------------------------------------------------

class ShutdownEventTests(unittest.TestCase):

    def test_default_is_not_forced(self):
        ev = ShutdownEvent("SIGTERM", None, "normal")
        self.assertFalse(ev.is_forced)

    def test_forced_flag(self):
        ev = ShutdownEvent("SIGINT", None, "user abort", is_forced=True)
        self.assertTrue(ev.is_forced)


# ---------------------------------------------------------------------------
# SignalHandler
# ---------------------------------------------------------------------------

class SignalHandlerTests(unittest.IsolatedAsyncioTestCase):

    async def test_first_sigint_triggers_graceful_shutdown(self):
        mgr = GracefulShutdownManager()
        sh = SignalHandler(mgr)
        await sh._handle_sigint()
        self.assertTrue(mgr.is_shutting_down)

    async def test_second_sigint_calls_sys_exit(self):
        mgr = GracefulShutdownManager()
        sh = SignalHandler(mgr)
        await sh._handle_sigint()  # first
        with self.assertRaises(SystemExit):
            await sh._handle_sigint()  # second → force

    async def test_sigterm_triggers_shutdown(self):
        mgr = GracefulShutdownManager()
        sh = SignalHandler(mgr)
        await sh._handle_sigterm()
        self.assertTrue(mgr.is_shutting_down)


if __name__ == "__main__":
    unittest.main()
