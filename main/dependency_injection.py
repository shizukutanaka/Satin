"""
Dependency Injection container for Satin module composition.

Provides:
- Service registration and resolution
- Singleton and transient lifecycles
- Async resource management
- Configuration injection
- Service discovery
- Circular dependency detection

Suitable for:
- Decoupling integrator components
- Testing with mock implementations
- Configuration management
- Microservices patterns
"""

import inspect
import logging
from typing import (
    Any, Callable, Dict, List, Optional, Type, TypeVar, Generic, Union
)
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
import asyncio
import weakref

logger = logging.getLogger(__name__)

T = TypeVar('T')


class ServiceLifetime(str, Enum):
    """Service lifetime management."""
    SINGLETON = "singleton"
    TRANSIENT = "transient"
    SCOPED = "scoped"


@dataclass
class ServiceDescriptor:
    """Description of a registered service."""
    service_type: Type
    implementation_type: Optional[Type] = None
    factory: Optional[Callable] = None
    instance: Optional[Any] = None
    lifetime: ServiceLifetime = ServiceLifetime.TRANSIENT
    dependencies: List[Type] = field(default_factory=list)
    tags: Dict[str, Any] = field(default_factory=dict)


class ServiceResolutionError(Exception):
    """Error during service resolution."""
    pass


class CircularDependencyError(ServiceResolutionError):
    """Circular dependency detected."""
    pass


class ServiceNotFoundError(ServiceResolutionError):
    """Service not registered."""
    pass


class ServiceContainer:
    """
    IoC (Inversion of Control) container for dependency injection.

    Manages service registration, resolution, and lifecycle.
    """

    def __init__(self):
        """Initialize service container."""
        self._services: Dict[Type, ServiceDescriptor] = {}
        self._factories: Dict[Type, Callable] = {}
        self._singletons: Dict[Type, Any] = {}
        self._scopes: List['ServiceScope'] = []
        self._resolution_stack: List[Type] = []
        self._lock = asyncio.Lock()

    def register(
        self,
        service_type: Type[T],
        implementation_type: Optional[Type[T]] = None,
        lifetime: ServiceLifetime = ServiceLifetime.TRANSIENT,
        tags: Optional[Dict[str, Any]] = None
    ) -> 'ServiceContainer':
        """
        Register a service with its implementation.

        Args:
            service_type: Interface/base class
            implementation_type: Concrete implementation
            lifetime: Singleton, Transient, or Scoped
            tags: Metadata tags

        Returns:
            Self for chaining
        """
        impl_type = implementation_type or service_type

        descriptor = ServiceDescriptor(
            service_type=service_type,
            implementation_type=impl_type,
            lifetime=lifetime,
            tags=tags or {}
        )

        self._services[service_type] = descriptor
        logger.debug(f"Registered {service_type.__name__} -> {impl_type.__name__}")

        return self

    def register_singleton(
        self,
        service_type: Type[T],
        instance: T
    ) -> 'ServiceContainer':
        """
        Register a singleton instance.

        Args:
            service_type: Service interface
            instance: Singleton instance

        Returns:
            Self for chaining
        """
        descriptor = ServiceDescriptor(
            service_type=service_type,
            implementation_type=type(instance),
            instance=instance,
            lifetime=ServiceLifetime.SINGLETON
        )

        self._services[service_type] = descriptor
        self._singletons[service_type] = instance
        logger.debug(f"Registered singleton {service_type.__name__}")

        return self

    def register_factory(
        self,
        service_type: Type[T],
        factory: Callable[['ServiceContainer'], T],
        lifetime: ServiceLifetime = ServiceLifetime.TRANSIENT
    ) -> 'ServiceContainer':
        """
        Register a service with factory function.

        Args:
            service_type: Service interface
            factory: Function to create instances
            lifetime: Service lifetime

        Returns:
            Self for chaining
        """
        descriptor = ServiceDescriptor(
            service_type=service_type,
            factory=factory,
            lifetime=lifetime
        )

        self._services[service_type] = descriptor
        self._factories[service_type] = factory
        logger.debug(f"Registered factory for {service_type.__name__}")

        return self

    async def resolve(self, service_type: Type[T]) -> T:
        """
        Resolve a service instance.

        Args:
            service_type: Service type to resolve

        Returns:
            Instance of service

        Raises:
            ServiceNotFoundError: Service not registered
            CircularDependencyError: Circular dependency detected
        """
        # Check for circular dependencies
        if service_type in self._resolution_stack:
            chain = ' -> '.join(t.__name__ for t in self._resolution_stack + [service_type])
            raise CircularDependencyError(f"Circular dependency: {chain}")

        if service_type not in self._services:
            raise ServiceNotFoundError(f"Service {service_type.__name__} not registered")

        descriptor = self._services[service_type]

        # Return singleton if available
        if descriptor.lifetime == ServiceLifetime.SINGLETON:
            if service_type in self._singletons:
                return self._singletons[service_type]

            # Create singleton
            self._resolution_stack.append(service_type)
            try:
                instance = await self._create_instance(descriptor)
                self._singletons[service_type] = instance
                return instance
            finally:
                self._resolution_stack.pop()

        # Create transient or scoped instance
        self._resolution_stack.append(service_type)
        try:
            return await self._create_instance(descriptor)
        finally:
            self._resolution_stack.pop()

    async def _create_instance(self, descriptor: ServiceDescriptor) -> Any:
        """Create service instance."""
        if descriptor.instance is not None:
            return descriptor.instance

        if descriptor.factory:
            return descriptor.factory(self)

        if descriptor.implementation_type is None:
            raise ServiceResolutionError("No implementation provided")

        # Get constructor parameters
        init_signature = inspect.signature(descriptor.implementation_type.__init__)
        kwargs = {}

        for param_name, param in init_signature.parameters.items():
            if param_name == 'self':
                continue

            if param.annotation == inspect.Parameter.empty:
                if param.default != inspect.Parameter.empty:
                    kwargs[param_name] = param.default
                continue

            # Try to resolve dependency
            try:
                kwargs[param_name] = await self.resolve(param.annotation)
            except ServiceResolutionError:
                if param.default != inspect.Parameter.empty:
                    kwargs[param_name] = param.default
                else:
                    raise

        # Create instance
        instance = descriptor.implementation_type(**kwargs)

        # Call async init if available
        if hasattr(instance, 'async_init'):
            await instance.async_init()

        return instance

    def create_scope(self) -> 'ServiceScope':
        """Create a new service scope."""
        scope = ServiceScope(self)
        self._scopes.append(weakref.ref(scope))
        return scope

    def get_descriptor(self, service_type: Type) -> Optional[ServiceDescriptor]:
        """Get service descriptor."""
        return self._services.get(service_type)

    def get_all_descriptors(self) -> Dict[Type, ServiceDescriptor]:
        """Get all registered services."""
        return dict(self._services)

    async def clear(self) -> None:
        """Clear all services and dispose resources."""
        # Dispose async resources
        for service in self._singletons.values():
            if hasattr(service, 'async_dispose'):
                await service.async_dispose()

        self._services.clear()
        self._singletons.clear()
        self._factories.clear()
        logger.debug("Container cleared")


class ServiceScope:
    """Service scope for scoped lifetime services."""

    def __init__(self, container: ServiceContainer):
        """
        Initialize service scope.

        Args:
            container: Parent container
        """
        self._container = container
        self._scoped_instances: Dict[Type, Any] = {}

    async def resolve(self, service_type: Type[T]) -> T:
        """Resolve service in this scope."""
        descriptor = self._container.get_descriptor(service_type)

        if descriptor is None:
            raise ServiceNotFoundError(f"Service {service_type.__name__} not registered")

        # Return scoped instance if available
        if descriptor.lifetime == ServiceLifetime.SCOPED:
            if service_type in self._scoped_instances:
                return self._scoped_instances[service_type]

            instance = await self._container.resolve(service_type)
            self._scoped_instances[service_type] = instance
            return instance

        # Delegate to container for other lifetimes
        return await self._container.resolve(service_type)

    async def dispose(self) -> None:
        """Dispose scoped services."""
        for service in self._scoped_instances.values():
            if hasattr(service, 'async_dispose'):
                await service.async_dispose()

        self._scoped_instances.clear()


class ServiceBuilder:
    """Fluent builder for container configuration."""

    def __init__(self):
        """Initialize service builder."""
        self._container = ServiceContainer()

    def add_singleton(
        self,
        service_type: Type[T],
        implementation: Optional[Union[Type[T], T]] = None
    ) -> 'ServiceBuilder':
        """Add singleton service."""
        if isinstance(implementation, type):
            self._container.register(
                service_type,
                implementation,
                ServiceLifetime.SINGLETON
            )
        else:
            self._container.register_singleton(service_type, implementation)

        return self

    def add_transient(
        self,
        service_type: Type[T],
        implementation: Optional[Type[T]] = None
    ) -> 'ServiceBuilder':
        """Add transient service."""
        self._container.register(
            service_type,
            implementation,
            ServiceLifetime.TRANSIENT
        )
        return self

    def add_scoped(
        self,
        service_type: Type[T],
        implementation: Optional[Type[T]] = None
    ) -> 'ServiceBuilder':
        """Add scoped service."""
        self._container.register(
            service_type,
            implementation,
            ServiceLifetime.SCOPED
        )
        return self

    def add_factory(
        self,
        service_type: Type[T],
        factory: Callable[[ServiceContainer], T],
        lifetime: ServiceLifetime = ServiceLifetime.TRANSIENT
    ) -> 'ServiceBuilder':
        """Add factory-based service."""
        self._container.register_factory(service_type, factory, lifetime)
        return self

    def build(self) -> ServiceContainer:
        """Build and return container."""
        return self._container


class ServiceCollection:
    """Collection management for multiple service implementations."""

    def __init__(self, service_type: Type):
        """
        Initialize service collection.

        Args:
            service_type: Service interface
        """
        self.service_type = service_type
        self.services: List[ServiceDescriptor] = []

    def add(self, descriptor: ServiceDescriptor) -> None:
        """Add service to collection."""
        self.services.append(descriptor)

    def get_all(self) -> List[ServiceDescriptor]:
        """Get all services."""
        return self.services

    def get_by_tag(self, tag_key: str, tag_value: Any) -> List[ServiceDescriptor]:
        """Get services matching tag."""
        return [
            s for s in self.services
            if s.tags.get(tag_key) == tag_value
        ]


# Service locator pattern (use with caution - prefer DI)
_global_container: Optional[ServiceContainer] = None


def get_service_container() -> ServiceContainer:
    """Get global service container."""
    global _global_container
    if _global_container is None:
        _global_container = ServiceContainer()
    return _global_container


def set_service_container(container: ServiceContainer) -> None:
    """Set global service container."""
    global _global_container
    _global_container = container


class ServiceProviderDecorator:
    """Decorator for automatic service resolution."""

    def __init__(self, container: Optional[ServiceContainer] = None):
        """
        Initialize service provider decorator.

        Args:
            container: Service container (uses global if None)
        """
        self.container = container or get_service_container()

    def __call__(self, service_type: Type[T]) -> Callable:
        """
        Decorate function to inject service.

        Usage:
            @service_provider(IRepository)
            async def my_function(repo: IRepository):
                pass
        """
        def decorator(func: Callable) -> Callable:
            async def async_wrapper(*args, **kwargs):
                if service_type not in kwargs:
                    kwargs[service_type.__name__] = await self.container.resolve(service_type)
                return await func(*args, **kwargs)

            def sync_wrapper(*args, **kwargs):
                if service_type not in kwargs:
                    # Create event loop if needed
                    try:
                        loop = asyncio.get_running_loop()
                    except RuntimeError:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        return loop.run_until_complete(
                            self.container.resolve(service_type)
                        )
                    # In async context - cannot use sync wrapper
                    raise RuntimeError("Use async wrapper in async context")
                return func(*args, **kwargs)

            if inspect.iscoroutinefunction(func):
                return async_wrapper
            return sync_wrapper

        return decorator
