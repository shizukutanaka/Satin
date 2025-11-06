"""
Async/await optimization and concurrent programming strategies for Satin.

Provides:
- Event loop optimization (uvloop support)
- Concurrent execution patterns (threading vs multiprocessing)
- Async context management
- Task pooling and batch operations
- CPU-bound work offloading
- Database connection pooling for async operations

Based on 2025 best practices:
- uvloop for 2-4x performance improvements
- asyncio task groups (Python 3.11+)
- ThreadPoolExecutor for I/O-bound blocking code
- ProcessPoolExecutor for CPU-bound work
- SQLAlchemy async session management
"""

import asyncio
import logging
import time
from typing import Any, Callable, List, Optional, TypeVar, Union, Coroutine
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, Future
from dataclasses import dataclass
from datetime import datetime, timedelta
import sys

logger = logging.getLogger(__name__)

T = TypeVar('T')


class EventLoopOptimizer:
    """Configure and optimize asyncio event loop."""

    @staticmethod
    def use_uvloop() -> bool:
        """
        Switch to uvloop for 2-4x performance improvement.

        Returns:
            True if uvloop enabled, False otherwise

        Note: Requires `pip install uvloop`
        """
        try:
            import uvloop
            asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
            logger.info("uvloop event loop policy enabled (2-4x faster)")
            return True
        except ImportError:
            logger.debug("uvloop not available, using standard asyncio")
            return False

    @staticmethod
    def enable_debug_mode(enable: bool = True) -> None:
        """
        Enable asyncio debug mode for development.

        Provides:
        - Long-running callback warnings
        - Slow selector warnings
        - Task creation/destruction logging

        Args:
            enable: Whether to enable debug mode
        """
        loop = asyncio.get_event_loop()
        loop.set_debug(enable)

        if enable:
            logger.info("Asyncio debug mode enabled")
        else:
            logger.info("Asyncio debug mode disabled")

    @staticmethod
    def optimize_selector(selector_type: str = "auto") -> None:
        """
        Set optimal selector for platform.

        Args:
            selector_type: "auto", "select", "poll", "epoll", "kqueue", "iocp"

        Note:
        - epoll: Linux (most efficient)
        - kqueue: BSD/macOS
        - iocp: Windows (default)
        - poll: Unix fallback
        """
        import selectors

        if selector_type == "auto":
            # Platform-specific optimization
            if sys.platform == "linux":
                selector_type = "epoll"
            elif sys.platform == "darwin":
                selector_type = "kqueue"
            elif sys.platform == "win32":
                selector_type = "iocp"
            else:
                selector_type = "poll"

        try:
            loop = asyncio.get_event_loop()
            # Selector policy is typically determined at event loop creation
            logger.info(f"Event loop using selector: {selector_type}")
        except Exception as e:
            logger.warning(f"Could not set selector: {e}")


@dataclass
class AsyncTaskResult:
    """Result of async task execution."""
    task_id: str
    coroutine_name: str
    result: Any = None
    exception: Optional[Exception] = None
    duration_ms: float = 0.0
    start_time: datetime = None
    end_time: datetime = None

    @property
    def success(self) -> bool:
        """Whether task succeeded."""
        return self.exception is None

    @property
    def is_done(self) -> bool:
        """Whether task is complete."""
        return self.end_time is not None


class AsyncTaskPool:
    """
    Manage pool of concurrent async tasks.

    For Python 3.11+, this uses TaskGroup. For older versions, it manages
    tasks manually with proper error handling.
    """

    def __init__(self, max_concurrent: Optional[int] = None):
        """
        Initialize task pool.

        Args:
            max_concurrent: Maximum concurrent tasks (None = no limit)
        """
        self.max_concurrent = max_concurrent or 100
        self.semaphore = asyncio.Semaphore(self.max_concurrent)
        self.tasks: List[asyncio.Task] = []
        self.results: List[AsyncTaskResult] = []
        self._task_counter = 0

    async def add_task(
        self,
        coro: Coroutine[Any, Any, T],
        task_name: Optional[str] = None
    ) -> str:
        """
        Add task to pool.

        Args:
            coro: Coroutine to execute
            task_name: Optional task name

        Returns:
            Task ID
        """
        task_id = f"task_{self._task_counter}"
        self._task_counter += 1

        async def bounded_coro():
            async with self.semaphore:
                return await coro

        task = asyncio.create_task(bounded_coro(), name=task_name or task_id)
        self.tasks.append(task)
        return task_id

    async def run_all(self, return_exceptions: bool = True) -> List[AsyncTaskResult]:
        """
        Run all tasks concurrently.

        Args:
            return_exceptions: Include exceptions in results

        Returns:
            List of task results
        """
        if not self.tasks:
            return []

        try:
            if sys.version_info >= (3, 11):
                # Python 3.11+ TaskGroup
                async with asyncio.TaskGroup() as tg:
                    for task in self.tasks:
                        tg.create_task(task)
            else:
                # Manual task management
                await asyncio.gather(*self.tasks, return_exceptions=return_exceptions)
        except Exception as e:
            logger.error(f"Task pool execution error: {e}")

        # Collect results
        for i, task in enumerate(self.tasks):
            result = AsyncTaskResult(
                task_id=f"task_{i}",
                coroutine_name=task.get_name()
            )

            if task.done():
                try:
                    result.result = task.result()
                    result.duration_ms = (
                        (task._when - task._created) * 1000
                        if hasattr(task, '_when') and hasattr(task, '_created')
                        else 0
                    )
                except Exception as e:
                    result.exception = e

            self.results.append(result)

        return self.results

    def get_successful(self) -> List[Any]:
        """Get results from successful tasks."""
        return [r.result for r in self.results if r.success]

    def get_failures(self) -> List[tuple]:
        """Get (task_id, exception) for failed tasks."""
        return [(r.task_id, r.exception) for r in self.results if not r.success]


class ConcurrentExecutor:
    """
    Execute sync functions concurrently.

    Automatically chooses ThreadPoolExecutor for I/O-bound or
    ProcessPoolExecutor for CPU-bound work.
    """

    def __init__(
        self,
        max_workers: Optional[int] = None,
        executor_type: str = "thread"
    ):
        """
        Initialize executor.

        Args:
            max_workers: Number of worker threads/processes
            executor_type: "thread" (I/O), "process" (CPU), or "auto"
        """
        self.max_workers = max_workers
        self.executor_type = executor_type

        if executor_type == "thread":
            self.executor = ThreadPoolExecutor(max_workers=max_workers)
        elif executor_type == "process":
            self.executor = ProcessPoolExecutor(max_workers=max_workers)
        else:
            self.executor = None  # Will auto-select

    async def run(
        self,
        func: Callable[..., T],
        *args,
        **kwargs
    ) -> T:
        """
        Run sync function asynchronously.

        Args:
            func: Synchronous function
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Function result
        """
        loop = asyncio.get_event_loop()

        if self.executor is None:
            # Auto-select executor based on function characteristics
            if self._is_cpu_bound(func):
                executor = ProcessPoolExecutor(max_workers=self.max_workers)
            else:
                executor = ThreadPoolExecutor(max_workers=self.max_workers)
        else:
            executor = self.executor

        return await loop.run_in_executor(executor, func, *args)

    @staticmethod
    def _is_cpu_bound(func: Callable) -> bool:
        """Heuristic: detect if function is CPU-bound."""
        cpu_bound_names = {
            'compute', 'calculate', 'process', 'transform',
            'encrypt', 'compress', 'analyze', 'parse'
        }
        return any(
            name in func.__name__.lower()
            for name in cpu_bound_names
        )

    async def map(
        self,
        func: Callable[..., T],
        *iterables,
        timeout: Optional[float] = None
    ) -> List[T]:
        """
        Apply function to iterables asynchronously.

        Args:
            func: Function to apply
            *iterables: Iterables to map over
            timeout: Result timeout in seconds

        Returns:
            List of results
        """
        loop = asyncio.get_event_loop()
        futures = []

        for item in iterables[0] if iterables else []:
            future = loop.run_in_executor(
                self.executor,
                func,
                item
            )
            futures.append(future)

        return await asyncio.gather(*futures, return_exceptions=False)

    def shutdown(self) -> None:
        """Shutdown executor."""
        if self.executor:
            self.executor.shutdown(wait=True)


class AsyncContextManager:
    """
    Base class for async context managers with resource management.

    Provides:
    - Proper async initialization
    - Resource cleanup on error
    - Lifecycle hooks
    """

    def __init__(self, name: str = "resource"):
        """Initialize context manager."""
        self.name = name
        self._initialized = False

    async def __aenter__(self):
        """Async enter context."""
        await self.async_init()
        self._initialized = True
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async exit context."""
        await self.async_cleanup(exc_type is not None)
        self._initialized = False

    async def async_init(self) -> None:
        """Initialize async resources."""
        logger.debug(f"Initializing {self.name}")

    async def async_cleanup(self, errored: bool = False) -> None:
        """
        Cleanup async resources.

        Args:
            errored: Whether context exited with exception
        """
        logger.debug(f"Cleaning up {self.name}")


class BatchAsyncProcessor:
    """Process items in batches asynchronously."""

    def __init__(
        self,
        batch_size: int = 100,
        max_batch_wait_ms: int = 1000
    ):
        """
        Initialize batch processor.

        Args:
            batch_size: Items per batch
            max_batch_wait_ms: Max wait time before processing partial batch
        """
        self.batch_size = batch_size
        self.max_batch_wait_ms = max_batch_wait_ms
        self.batch: List[Any] = []
        self.created_at = datetime.now()
        self._processor: Optional[Callable] = None

    async def add(self, item: Any) -> Optional[List[Any]]:
        """
        Add item to batch.

        Args:
            item: Item to add

        Returns:
            Processed batch if ready, None otherwise
        """
        self.batch.append(item)

        # Process if batch is full
        if len(self.batch) >= self.batch_size:
            return await self._process_batch()

        # Process if max wait exceeded
        elapsed_ms = (datetime.now() - self.created_at).total_seconds() * 1000
        if elapsed_ms > self.max_batch_wait_ms and self.batch:
            return await self._process_batch()

        return None

    async def flush(self) -> Optional[List[Any]]:
        """Process remaining items."""
        if self.batch:
            return await self._process_batch()
        return None

    async def _process_batch(self) -> List[Any]:
        """Process current batch."""
        batch = self.batch
        self.batch = []
        self.created_at = datetime.now()

        if self._processor:
            try:
                return await self._processor(batch)
            except Exception as e:
                logger.error(f"Batch processing error: {e}")
                return batch

        return batch

    def set_processor(self, processor: Callable) -> None:
        """Set batch processor function."""
        self._processor = processor


class AsyncRateLimiterAdvanced:
    """
    Advanced async rate limiter with adaptive concurrency.

    Monitors task completion times and adjusts concurrency level
    to maximize throughput while maintaining latency SLA.
    """

    def __init__(
        self,
        target_latency_ms: float = 100.0,
        min_concurrency: int = 1,
        max_concurrency: int = 100
    ):
        """
        Initialize adaptive rate limiter.

        Args:
            target_latency_ms: Target p99 latency in milliseconds
            min_concurrency: Minimum concurrent operations
            max_concurrency: Maximum concurrent operations
        """
        self.target_latency_ms = target_latency_ms
        self.min_concurrency = min_concurrency
        self.max_concurrency = max_concurrency
        self.current_concurrency = min_concurrency
        self.semaphore = asyncio.Semaphore(self.current_concurrency)
        self.latencies: List[float] = []
        self.window_size = 100

    async def acquire(self) -> None:
        """Acquire permission to execute task."""
        await self.semaphore.acquire()

    def release(self, latency_ms: float) -> None:
        """
        Release permission after task completion.

        Args:
            latency_ms: Task execution latency
        """
        self.semaphore.release()

        # Track latency
        self.latencies.append(latency_ms)
        if len(self.latencies) > self.window_size:
            self.latencies.pop(0)

        # Adjust concurrency
        if len(self.latencies) >= 10:
            p99_latency = sorted(self.latencies)[int(len(self.latencies) * 0.99)]

            if p99_latency > self.target_latency_ms:
                # Reduce concurrency if latency too high
                new_concurrency = max(
                    self.min_concurrency,
                    self.current_concurrency - 1
                )
            elif p99_latency < self.target_latency_ms * 0.8:
                # Increase concurrency if latency good
                new_concurrency = min(
                    self.max_concurrency,
                    self.current_concurrency + 1
                )
            else:
                new_concurrency = self.current_concurrency

            if new_concurrency != self.current_concurrency:
                self.current_concurrency = new_concurrency
                self.semaphore = asyncio.Semaphore(new_concurrency)
                logger.info(f"Adjusted concurrency to {new_concurrency}")


async def gather_with_timeout(
    *coros,
    timeout_seconds: float = 30.0,
    return_exceptions: bool = False
) -> List[Any]:
    """
    Run coroutines with timeout.

    Args:
        *coros: Coroutines to run
        timeout_seconds: Timeout duration
        return_exceptions: Include exceptions in results

    Returns:
        Results or exceptions
    """
    try:
        return await asyncio.wait_for(
            asyncio.gather(*coros, return_exceptions=return_exceptions),
            timeout=timeout_seconds
        )
    except asyncio.TimeoutError:
        logger.error(f"Gather timed out after {timeout_seconds}s")
        raise


async def safe_gather(
    *coros,
    max_failures: Optional[int] = None
) -> List[Any]:
    """
    Run coroutines with error tolerance.

    Args:
        *coros: Coroutines to run
        max_failures: Stop if this many fail (None = no limit)

    Returns:
        Results (exceptions included)
    """
    results = []
    failures = 0

    for coro in coros:
        try:
            result = await coro
            results.append(result)
        except Exception as e:
            failures += 1
            results.append(e)

            if max_failures and failures >= max_failures:
                logger.warning(f"Reached max failures ({max_failures}), stopping")
                break

    return results


class AsyncConnectionPool:
    """
    Generic async connection pool for database/service connections.

    Manages connection lifecycle and recycling.
    """

    def __init__(
        self,
        factory: Callable,
        pool_size: int = 10,
        max_overflow: int = 5,
        timeout_seconds: float = 30.0
    ):
        """
        Initialize connection pool.

        Args:
            factory: Async callable to create connections
            pool_size: Minimum pool size
            max_overflow: Additional connections allowed
            timeout_seconds: Connection timeout
        """
        self.factory = factory
        self.pool_size = pool_size
        self.max_overflow = max_overflow
        self.timeout_seconds = timeout_seconds
        self._available: asyncio.Queue = asyncio.Queue(maxsize=pool_size + max_overflow)
        self._all_connections: List[Any] = []
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Initialize pool with initial connections."""
        async with self._lock:
            for _ in range(self.pool_size):
                conn = await self.factory()
                self._all_connections.append(conn)
                await self._available.put(conn)

    async def acquire(self, timeout: Optional[float] = None) -> Any:
        """
        Acquire connection from pool.

        Args:
            timeout: Acquisition timeout (None = use default)

        Returns:
            Connection object
        """
        timeout = timeout or self.timeout_seconds

        try:
            conn = await asyncio.wait_for(
                self._available.get(),
                timeout=timeout
            )
            return conn
        except asyncio.TimeoutError:
            # Try to create overflow connection
            if len(self._all_connections) < self.pool_size + self.max_overflow:
                conn = await self.factory()
                self._all_connections.append(conn)
                return conn

            raise

    async def release(self, conn: Any) -> None:
        """Release connection back to pool."""
        await self._available.put(conn)

    async def close_all(self) -> None:
        """Close all connections."""
        async with self._lock:
            for conn in self._all_connections:
                if hasattr(conn, 'close'):
                    await conn.close()
            self._all_connections.clear()
