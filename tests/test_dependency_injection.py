"""
Unit tests for dependency_injection.ServiceContainer.

Covers: register/resolve transient & singleton, factory, circular dependency
detection, ServiceNotFoundError, and the global container singleton helpers.
"""
import asyncio
import os
import sys
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from dependency_injection import (  # noqa: E402
    ServiceContainer,
    ServiceLifetime,
    ServiceNotFoundError,
    CircularDependencyError,
    get_service_container,
    set_service_container,
)


def _run(coro):
    return asyncio.run(coro)


class _Service:
    pass


class _Impl(_Service):
    pass


class _OtherService:
    pass


class RegisterResolveTests(unittest.TestCase):
    def setUp(self):
        self.container = ServiceContainer()

    def test_resolve_registered_type_returns_instance(self):
        self.container.register(_Service)
        instance = _run(self.container.resolve(_Service))
        self.assertIsInstance(instance, _Service)

    def test_resolve_with_implementation_type(self):
        self.container.register(_Service, _Impl)
        instance = _run(self.container.resolve(_Service))
        self.assertIsInstance(instance, _Impl)

    def test_transient_returns_different_instances(self):
        self.container.register(_Service, lifetime=ServiceLifetime.TRANSIENT)
        a = _run(self.container.resolve(_Service))
        b = _run(self.container.resolve(_Service))
        self.assertIsNot(a, b)

    def test_singleton_returns_same_instance(self):
        self.container.register(_Service, lifetime=ServiceLifetime.SINGLETON)
        a = _run(self.container.resolve(_Service))
        b = _run(self.container.resolve(_Service))
        self.assertIs(a, b)

    def test_register_singleton_instance(self):
        instance = _Service()
        self.container.register_singleton(_Service, instance)
        resolved = _run(self.container.resolve(_Service))
        self.assertIs(resolved, instance)

    def test_unregistered_type_raises_service_not_found(self):
        with self.assertRaises(ServiceNotFoundError):
            _run(self.container.resolve(_OtherService))

    def test_register_returns_self_for_chaining(self):
        result = self.container.register(_Service)
        self.assertIs(result, self.container)


class FactoryTests(unittest.TestCase):
    def setUp(self):
        self.container = ServiceContainer()

    def test_factory_called_on_resolve(self):
        called = []
        def factory(c):
            called.append(True)
            return _Service()
        self.container.register_factory(_Service, factory)
        _run(self.container.resolve(_Service))
        self.assertTrue(called)

    def test_factory_receives_container(self):
        received = []
        def factory(c):
            received.append(c)
            return _Service()
        self.container.register_factory(_Service, factory)
        _run(self.container.resolve(_Service))
        self.assertIs(received[0], self.container)

    def test_singleton_factory_called_once(self):
        calls = []
        def factory(c):
            calls.append(1)
            return _Service()
        self.container.register_factory(_Service, factory, lifetime=ServiceLifetime.SINGLETON)
        _run(self.container.resolve(_Service))
        _run(self.container.resolve(_Service))
        self.assertEqual(len(calls), 1)

    def test_transient_factory_called_each_time(self):
        calls = []
        def factory(c):
            calls.append(1)
            return _Service()
        self.container.register_factory(_Service, factory, lifetime=ServiceLifetime.TRANSIENT)
        _run(self.container.resolve(_Service))
        _run(self.container.resolve(_Service))
        self.assertEqual(len(calls), 2)


class CircularDependencyTests(unittest.TestCase):
    def test_circular_dependency_raises(self):
        # A needs B, B needs A — via constructor injection (the path the
        # per-call cycle-detection stack actually guards). Annotations are
        # attached after both classes exist so each refers to the real type.
        class A:
            def __init__(self, b):
                self.b = b

        class B:
            def __init__(self, a):
                self.a = a

        A.__init__.__annotations__['b'] = B
        B.__init__.__annotations__['a'] = A

        container = ServiceContainer()
        container.register(A)
        container.register(B)

        # Must raise CircularDependencyError specifically (not just any
        # Exception). The previous version used factories with nested
        # asyncio.run, which raised an unrelated RuntimeError and left a
        # dangling unawaited coroutine — so it never tested cycle detection.
        with self.assertRaises(CircularDependencyError):
            _run(container.resolve(A))

    def test_circular_dependency_chain_in_message(self):
        class X:
            def __init__(self, y):
                self.y = y

        class Y:
            def __init__(self, x):
                self.x = x

        X.__init__.__annotations__['y'] = Y
        Y.__init__.__annotations__['x'] = X

        container = ServiceContainer()
        container.register(X)
        container.register(Y)

        with self.assertRaises(CircularDependencyError) as ctx:
            _run(container.resolve(X))
        # The error names the cycle so it is diagnosable.
        self.assertIn("X", str(ctx.exception))
        self.assertIn("Y", str(ctx.exception))


class GlobalContainerTests(unittest.TestCase):
    def setUp(self):
        self._original = get_service_container()

    def tearDown(self):
        set_service_container(self._original)

    def test_get_service_container_returns_container(self):
        c = get_service_container()
        self.assertIsInstance(c, ServiceContainer)

    def test_set_service_container_replaces_global(self):
        new_container = ServiceContainer()
        set_service_container(new_container)
        self.assertIs(get_service_container(), new_container)

    def test_register_and_resolve_via_global_container(self):
        c = ServiceContainer()
        c.register_singleton(_Service, _Service())
        set_service_container(c)
        resolved = _run(get_service_container().resolve(_Service))
        self.assertIsInstance(resolved, _Service)


if __name__ == "__main__":
    unittest.main()
