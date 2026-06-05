"""
Stdlib-only regression tests for the Tier-1 fixes in:
  - main/async_optimization.py
  - main/dependency_injection.py

No third-party deps (uses unittest + asyncio) so it runs with a bare Python.
Run: python -m unittest tests.test_async_di -v
"""
import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main.async_optimization import AsyncTaskPool, ConcurrentExecutor  # noqa: E402
from main.dependency_injection import (  # noqa: E402
    ServiceContainer, ServiceLifetime, ServiceProviderDecorator,
)


class AsyncOptimizationTests(unittest.TestCase):
    def test_task_pool_runs_all_and_collects_results(self):
        async def scenario():
            pool = AsyncTaskPool(max_concurrent=4)

            async def work(n):
                await asyncio.sleep(0)
                return n * 2

            for i in range(5):
                await pool.add_task(work(i), task_name=f"w{i}")
            results = await pool.run_all()
            self.assertEqual(len(results), 5)
            self.assertTrue(all(r.is_done for r in results))
            self.assertEqual(sorted(pool.get_successful()), [0, 2, 4, 6, 8])
            self.assertEqual(pool.get_failures(), [])
        asyncio.run(scenario())

    def test_task_pool_captures_exceptions(self):
        async def scenario():
            pool = AsyncTaskPool()

            async def boom():
                raise ValueError("nope")

            await pool.add_task(boom(), task_name="boom")
            results = await pool.run_all(return_exceptions=True)
            self.assertEqual(len(results), 1)
            self.assertFalse(results[0].success)
            self.assertIsInstance(results[0].exception, ValueError)
        asyncio.run(scenario())

    def test_concurrent_executor_forwards_kwargs(self):
        async def scenario():
            ex = ConcurrentExecutor(executor_type="thread", max_workers=2)
            try:
                def fn(a, b=0, c=0):
                    return a + b + c
                got = await ex.run(fn, 1, b=2, c=3)
                self.assertEqual(got, 6)  # kwargs must not be dropped
            finally:
                ex.shutdown()
        asyncio.run(scenario())


class DependencyInjectionTests(unittest.TestCase):
    def test_async_provider_injects_by_param_name_and_calls_func(self):
        async def scenario():
            class Repo:
                pass

            container = ServiceContainer()
            container.register(Repo, Repo, ServiceLifetime.SINGLETON)
            service_provider = ServiceProviderDecorator(container)

            @service_provider(Repo)
            async def handler(repo: Repo):
                return repo

            result = await handler()
            self.assertIsInstance(result, Repo)
        asyncio.run(scenario())

    def test_sync_provider_calls_func_and_returns_value(self):
        class Repo:
            pass

        container = ServiceContainer()
        container.register(Repo, Repo, ServiceLifetime.SINGLETON)
        service_provider = ServiceProviderDecorator(container)

        @service_provider(Repo)
        def handler(repo: Repo):
            return ("called", repo)

        tag, repo = handler()  # no running loop -> resolves, then calls func
        self.assertEqual(tag, "called")
        self.assertIsInstance(repo, Repo)

    def test_singleton_concurrent_resolution_is_single_instance(self):
        async def scenario():
            created = {"n": 0}

            class Db:
                def __init__(self):
                    created["n"] += 1

            container = ServiceContainer()
            container.register(Db, Db, ServiceLifetime.SINGLETON)
            instances = await asyncio.gather(*(container.resolve(Db) for _ in range(20)))
            self.assertEqual(created["n"], 1)
            self.assertTrue(all(i is instances[0] for i in instances))
        asyncio.run(scenario())

    def test_async_factory_is_awaited(self):
        async def scenario():
            class Conn:
                pass

            async def make(_c):
                await asyncio.sleep(0)
                return Conn()

            container = ServiceContainer()
            container.register_factory(Conn, make, ServiceLifetime.TRANSIENT)
            got = await container.resolve(Conn)
            self.assertIsInstance(got, Conn)  # not a coroutine
        asyncio.run(scenario())

    def test_constructor_dependency_injection(self):
        async def scenario():
            class Repo:
                pass

            class Service:
                def __init__(self, repo: Repo):
                    self.repo = repo

            container = ServiceContainer()
            container.register(Repo, Repo, ServiceLifetime.SINGLETON)
            container.register(Service, Service, ServiceLifetime.TRANSIENT)
            svc = await container.resolve(Service)
            self.assertIsInstance(svc.repo, Repo)
        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
