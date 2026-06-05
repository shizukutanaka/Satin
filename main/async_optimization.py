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
import functools
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
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop yet (e.g. called at startup before asyncio.run).
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        loop.set_debug(enable)

        if enable:
            logger.info("Asyncio debug mode enabled")
        else:
            logger.info("Asyncio debug mode disabled")

    @staticmethod
    def recommended_selector(selector_type: str = "auto") -> str:
        """
        Return the recommended selector for the current platform.

        The selector backend is fixed when the event loop is created and cannot
        be swapped on a live loop, so this method is informational only: it
        reports which backend asyncio will already be using. It does NOT mutate
        any running loop.

        Args:
            selector_type: "auto" to detect from the platform, otherwise echoed back.

        Returns:
            The selector backend name (e.g. "epoll", "kqueue", "iocp", "poll").

        Note:
        - epoll: Linux (most efficient)
        - kqueue: BSD/macOS
        - iocp: Windows (default)
        - poll: Unix fallback
        """
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

        logger.info(f"Recommended event loop selector for this platform: {selector_type}")
        return selector_type


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
        name = task_name or task_id

        # Pre-create the result record; the wrapper fills it in as the task runs
        # so timing/result/exception are captured reliably (asyncio.Task exposes
        # no public start/end timestamps).
        result = AsyncTaskResult(task_id=task_id, coroutine_name=name)

        async def bounded_coro():
            async with self.semaphore:
                result.start_time = datetime.now()
                started = time.perf_counter()
                try:
                    result.result = await coro
                    return result.result
                except Exception as exc:
                    result.exception = exc
                    raise
                finally:
                    result.end_time = datetime.now()
                    result.duration_ms = (time.perf_counter() - started) * 1000

        task = asyncio.create_task(bounded_coro(), name=name)
        self.tasks.append(task)
        self.results.append(result)
        return task_id

    async def run_all(self, return_exceptions: bool = True) -> List[AsyncTaskResult]:
        """
        Run all tasks concurrently and wait for completion.

        Args:
            return_exceptions: If True, exceptions are captured per-result instead
                of propagating out of this call.

        Returns:
            List of task results (one per add_task call, in submission order)
        """
        if not self.tasks:
            return []

        # Tasks were already scheduled in add_task(); awaiting them here drives
        # them to completion. The per-task wrapper records result/exception, so a
        # plain gather works correctly on every supported Python version.
        await asyncio.gather(*self.tasks, return_exceptions=return_exceptions)

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
        # Lazily-created, reused pools for "auto" mode so we don't spawn (and
        # leak) a fresh pool on every call.
        self._auto_thread: Optional[ThreadPoolExecutor] = None
        self._auto_process: Optional[ProcessPoolExecutor] = None

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
        loop = asyncio.get_running_loop()

        if self.executor is None:
            # Auto-select a reused executor based on function characteristics.
            if self._is_cpu_bound(func):
                if self._auto_process is None:
                    self._auto_process = ProcessPoolExecutor(max_workers=self.max_workers)
                executor = self._auto_process
            else:
                if self._auto_thread is None:
                    self._auto_thread = ThreadPoolExecutor(max_workers=self.max_workers)
                executor = self._auto_thread
        else:
            executor = self.executor

        # functools.partial carries **kwargs (run_in_executor only forwards *args).
        call = functools.partial(func, *args, **kwargs)
        return await loop.run_in_executor(executor, call)

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
        loop = asyncio.get_running_loop()
        futures = []

        for item in iterables[0] if iterables else []:
            future = loop.run_in_executor(
                self.executor,
                func,
                item
            )
            futures.append(future)

        gathered = asyncio.gather(*futures, return_exceptions=False)
        if timeout is not None:
            return await asyncio.wait_for(gathered, timeout=timeout)
        return await gathered

    def shutdown(self) -> None:
        """Shutdown all executors owned by this instance."""
        for pool in (self.executor, self._auto_thread, self._auto_process):
            if pool is not None:
                pool.shutdown(wait=True)


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
        # Number of permits we still owe back to a shrink decision. While > 0,
        # completing tasks retire their permit instead of returning it, which
        # lowers capacity without ever replacing the live Semaphore object.
        self._pending_reduction = 0
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
        # Track latency first so the adjustment below sees this sample.
        self.latencies.append(latency_ms)
        if len(self.latencies) > self.window_size:
            self.latencies.pop(0)

        # Decide whether to grow or shrink the concurrency budget.
        if len(self.latencies) >= 10:
            idx = min(int(len(self.latencies) * 0.99), len(self.latencies) - 1)
            p99_latency = sorted(self.latencies)[idx]

            if (p99_latency > self.target_latency_ms
                    and self.current_concurrency > self.min_concurrency):
                # Too slow: retire one permit (paid down when tasks complete).
                self._pending_reduction += 1
                self.current_concurrency -= 1
                logger.info(f"Adjusted concurrency to {self.current_concurrency}")
            elif (p99_latency < self.target_latency_ms * 0.8
                    and self.current_concurrency < self.max_concurrency):
                # Headroom: add a permit to the same semaphore.
                self.current_concurrency += 1
                self.semaphore.release()
                logger.info(f"Adjusted concurrency to {self.current_concurrency}")

        # Return this task's permit, unless we owe a pending reduction — in which
        # case retiring it now is how we shrink the budget.
        if self._pending_reduction > 0:
            self._pending_reduction -= 1
        else:
            self.semaphore.release()


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
            # Try to create an overflow connection. The check + create + append
            # must be atomic, otherwise concurrent acquirers can race past the
            # cap and create more than pool_size + max_overflow connections
            # (which would later overflow the bounded queue on release()).
            async with self._lock:
                if len(self._all_connections) < self.pool_size + self.max_overflow:
                    conn = await self.factory()
                    self._all_connections.append(conn)
                    return conn

            raise

    async def release(self, conn: Any) -> None:
        """Release connection back to pool, discarding it if the pool is full."""
        try:
            self._available.put_nowait(conn)
        except asyncio.QueueFull:
            # Pool already at capacity (e.g. a transient overflow connection);
            # drop this one instead of blocking the caller forever.
            async with self._lock:
                if conn in self._all_connections:
                    self._all_connections.remove(conn)
            if hasattr(conn, 'close'):
                closer = conn.close()
                if asyncio.iscoroutine(closer):
                    await closer

    async def close_all(self) -> None:
        """Close all connections."""
        async with self._lock:
            for conn in self._all_connections:
                if hasattr(conn, 'close'):
                    await conn.close()
            self._all_connections.clear()
