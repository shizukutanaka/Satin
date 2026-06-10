"""
Performance profiling and optimization module for Satin.

Provides cProfile-based function profiling, memory profiling, and performance metrics
collection with OpenTelemetry-compatible instrumentation.

Implements:
- Function-level CPU profiling with cProfile
- Memory usage tracking and leak detection
- Performance regression detection
- Bottleneck identification and reporting
- Async-aware profiling support
"""

import cProfile
import pstats
import io
import functools
import time
import tracemalloc
import gc
import asyncio
from typing import Callable, Any, Dict, List, Optional, TypeVar, Union
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime
import json
import logging

T = TypeVar('T')

logger = logging.getLogger(__name__)


@dataclass
class ProfileResult:
    """Result of a profiling operation."""
    function_name: str
    total_calls: int
    total_time_ms: float
    cumulative_time_ms: float
    per_call_time_ms: float
    timestamp: datetime
    memory_peak_mb: float = 0.0
    memory_allocated_mb: float = 0.0
    operations: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class MemorySnapshot:
    """Memory usage snapshot."""
    timestamp: datetime
    current_mb: float
    peak_mb: float
    allocated_mb: float
    top_allocators: List[tuple] = field(default_factory=list)


class PerformanceProfiler:
    """CPU profiler using cProfile with statistical analysis."""

    def __init__(self, enable_stats: bool = True):
        """
        Initialize performance profiler.

        Args:
            enable_stats: Whether to track profiling statistics
        """
        self.enable_stats = enable_stats
        self.results: Dict[str, ProfileResult] = {}
        self._profilers: Dict[str, cProfile.Profile] = {}

    def profile_sync(
        self,
        func: Callable[..., T],
        *args: Any,
        **kwargs: Any
    ) -> tuple[T, ProfileResult]:
        """
        Profile a synchronous function.

        Uses cProfile for deterministic profiling with function call statistics.

        Args:
            func: Function to profile
            *args: Positional arguments for function
            **kwargs: Keyword arguments for function

        Returns:
            Tuple of (function_result, ProfileResult)
        """
        profiler = cProfile.Profile()
        profiler.enable()

        start_memory = tracemalloc.get_traced_memory()[0] if tracemalloc.is_tracing() else 0
        start_time = time.perf_counter()

        try:
            result = func(*args, **kwargs)
            return result, self._create_profile_result(
                func, profiler, start_time, start_memory
            )
        finally:
            profiler.disable()

    async def profile_async(
        self,
        coro: Callable[..., Any],
        *args: Any,
        **kwargs: Any
    ) -> tuple[Any, ProfileResult]:
        """
        Profile an asynchronous coroutine.

        Args:
            coro: Async function to profile
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Tuple of (coroutine_result, ProfileResult)
        """
        profiler = cProfile.Profile()
        profiler.enable()

        start_memory = tracemalloc.get_traced_memory()[0] if tracemalloc.is_tracing() else 0
        start_time = time.perf_counter()

        try:
            result = await coro(*args, **kwargs)
            return result, self._create_profile_result(
                coro, profiler, start_time, start_memory
            )
        finally:
            profiler.disable()

    def _create_profile_result(
        self,
        func: Callable,
        profiler: cProfile.Profile,
        start_time: float,
        start_memory: int
    ) -> ProfileResult:
        """Extract profiling statistics from cProfile.Profile object."""
        elapsed_time_ms = (time.perf_counter() - start_time) * 1000

        # Analyze profiler statistics
        s = io.StringIO()
        ps = pstats.Stats(profiler, stream=s)
        ps.strip_dirs()
        ps.sort_stats('cumulative')

        # Get top 5 functions by cumulative time
        operations = []
        for name, (cc, nc, tt, ct, callers) in ps.stats.items():
            operations.append({
                'name': str(name),
                'calls': nc,
                'total_time_ms': tt * 1000,
                'cumulative_time_ms': ct * 1000,
                'per_call_ms': (ct / nc * 1000) if nc > 0 else 0
            })

        operations.sort(key=lambda x: x['cumulative_time_ms'], reverse=True)
        operations = operations[:5]

        current_memory = tracemalloc.get_traced_memory()[0] if tracemalloc.is_tracing() else 0
        memory_peak_mb = (current_memory - start_memory) / (1024 * 1024)

        result = ProfileResult(
            function_name=func.__name__,
            total_calls=sum(
                nc for (cc, nc, tt, ct, callers) in ps.stats.values()
            ),
            total_time_ms=elapsed_time_ms,
            cumulative_time_ms=sum(
                ct * 1000 for (cc, nc, tt, ct, callers) in ps.stats.values()
            ),
            per_call_time_ms=elapsed_time_ms / max(1, sum(
                nc for (cc, nc, tt, ct, callers) in ps.stats.values()
            )),
            timestamp=datetime.now(),
            memory_peak_mb=memory_peak_mb,
            operations=operations
        )

        self.results[func.__name__] = result
        return result

    def get_slowest_functions(self, limit: int = 10) -> List[ProfileResult]:
        """Get slowest profiled functions."""
        return sorted(
            self.results.values(),
            key=lambda r: r.cumulative_time_ms,
            reverse=True
        )[:limit]

    def get_memory_heavy_functions(self, limit: int = 10) -> List[ProfileResult]:
        """Get most memory-intensive functions."""
        return sorted(
            self.results.values(),
            key=lambda r: r.memory_peak_mb,
            reverse=True
        )[:limit]

    def export_report(self, filepath: Path) -> None:
        """Export profiling results to JSON."""
        report = {
            'timestamp': datetime.now().isoformat(),
            'total_functions_profiled': len(self.results),
            'results': [
                {
                    'function_name': r.function_name,
                    'total_calls': r.total_calls,
                    'total_time_ms': round(r.total_time_ms, 2),
                    'cumulative_time_ms': round(r.cumulative_time_ms, 2),
                    'per_call_time_ms': round(r.per_call_time_ms, 2),
                    'memory_peak_mb': round(r.memory_peak_mb, 2),
                    'operations': r.operations
                }
                for r in self.get_slowest_functions()
            ]
        }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2)

        logger.info(f"Profiling report exported to {filepath}")


class MemoryProfiler:
    """Memory usage profiler using tracemalloc."""

    def __init__(self):
        """Initialize memory profiler."""
        self.snapshots: List[MemorySnapshot] = []
        self._baseline: Optional[MemorySnapshot] = None
        if not tracemalloc.is_tracing():
            tracemalloc.start()

    def take_snapshot(self, top_n: int = 5) -> MemorySnapshot:
        """
        Take a memory usage snapshot.

        Args:
            top_n: Number of top allocators to record

        Returns:
            MemorySnapshot with current memory state
        """
        current, peak = tracemalloc.get_traced_memory()

        snapshot = tracemalloc.take_snapshot()
        top_stats = snapshot.statistics('lineno')[:top_n]

        top_allocators = [
            (str(stat.traceback), stat.size / (1024 * 1024))
            for stat in top_stats
        ]

        mem_snapshot = MemorySnapshot(
            timestamp=datetime.now(),
            current_mb=current / (1024 * 1024),
            peak_mb=peak / (1024 * 1024),
            allocated_mb=(current - (self._baseline.current_mb * 1024 * 1024 if self._baseline else 0)) / (1024 * 1024) if self._baseline else 0,
            top_allocators=top_allocators
        )

        self.snapshots.append(mem_snapshot)
        return mem_snapshot

    def set_baseline(self) -> None:
        """Set current memory as baseline for comparison."""
        gc.collect()
        self._baseline = self.take_snapshot()

    def get_memory_delta(self) -> float:
        """Get memory delta from baseline."""
        if not self._baseline or not self.snapshots:
            return 0.0
        return self.snapshots[-1].current_mb - self._baseline.current_mb

    def detect_leak(self, threshold_mb: float = 10.0) -> bool:
        """
        Detect potential memory leak.

        Args:
            threshold_mb: Memory growth threshold in MB

        Returns:
            True if memory growth exceeds threshold
        """
        return self.get_memory_delta() > threshold_mb

    def export_report(self, filepath: Path) -> None:
        """Export memory profiling report."""
        report = {
            'timestamp': datetime.now().isoformat(),
            'snapshots': [
                {
                    'timestamp': s.timestamp.isoformat(),
                    'current_mb': round(s.current_mb, 2),
                    'peak_mb': round(s.peak_mb, 2),
                    'allocated_mb': round(s.allocated_mb, 2),
                    'top_allocators': [
                        {'traceback': tb, 'size_mb': round(size, 2)}
                        for tb, size in s.top_allocators
                    ]
                }
                for s in self.snapshots
            ]
        }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, default=str)

        logger.info(f"Memory report exported to {filepath}")


def profile_call(func: Optional[Callable] = None, *, memory: bool = False):
    """
    Decorator for profiling function calls.

    Args:
        func: Function to profile (when used without parentheses)
        memory: Whether to also profile memory usage

    Usage:
        @profile_call
        def my_function():
            pass

        @profile_call(memory=True)
        def heavy_function():
            pass
    """
    def decorator(f: Callable[..., T]) -> Callable[..., T]:
        profiler = PerformanceProfiler()

        if asyncio.iscoroutinefunction(f):
            @functools.wraps(f)
            async def async_wrapper(*args: Any, **kwargs: Any) -> T:
                result, profile_result = await profiler.profile_async(f, *args, **kwargs)
                logger.info(
                    f"{f.__name__} executed in {profile_result.total_time_ms:.2f}ms "
                    f"(calls: {profile_result.total_calls})"
                )
                if memory:
                    logger.info(
                        f"Memory delta: {profile_result.memory_peak_mb:.2f}MB"
                    )
                return result

            return async_wrapper
        else:
            @functools.wraps(f)
            def sync_wrapper(*args: Any, **kwargs: Any) -> T:
                result, profile_result = profiler.profile_sync(f, *args, **kwargs)
                logger.info(
                    f"{f.__name__} executed in {profile_result.total_time_ms:.2f}ms "
                    f"(calls: {profile_result.total_calls})"
                )
                if memory:
                    logger.info(
                        f"Memory delta: {profile_result.memory_peak_mb:.2f}MB"
                    )
                return result

            return sync_wrapper

    if func is not None:
        return decorator(func)
    return decorator


class PerformanceMonitor:
    """Monitor and track performance metrics over time."""

    def __init__(self, window_size: int = 100):
        """
        Initialize performance monitor.

        Args:
            window_size: Number of samples to keep in sliding window
        """
        self.window_size = window_size
        self.metrics: Dict[str, List[float]] = {}

    def record_operation(self, operation_name: str, duration_ms: float) -> None:
        """
        Record operation duration.

        Args:
            operation_name: Name of operation
            duration_ms: Duration in milliseconds
        """
        if operation_name not in self.metrics:
            self.metrics[operation_name] = []

        self.metrics[operation_name].append(duration_ms)

        if len(self.metrics[operation_name]) > self.window_size:
            self.metrics[operation_name].pop(0)

    def get_statistics(self, operation_name: str) -> Dict[str, float]:
        """
        Get statistics for operation.

        Returns:
            Dictionary with count, mean, median, min, max, p95, p99, stdev.
            When there are no samples, every key is present with 0.0 (and
            count 0) so callers never hit a KeyError.
        """
        import statistics

        values = sorted(self.metrics.get(operation_name) or [])
        n = len(values)

        if n == 0:
            return {
                'count': 0,
                'mean_ms': 0.0, 'median_ms': 0.0,
                'min_ms': 0.0, 'max_ms': 0.0,
                'p95_ms': 0.0, 'p99_ms': 0.0,
                'stdev_ms': 0.0,
            }

        return {
            'count': n,
            'mean_ms': sum(values) / n,
            'median_ms': statistics.median(values),
            'min_ms': values[0],
            'max_ms': values[-1],
            'p95_ms': self._percentile(values, 95.0),
            'p99_ms': self._percentile(values, 99.0),
            'stdev_ms': self._calculate_stdev(values)
        }

    @staticmethod
    def _percentile(values: List[float], pct: float) -> float:
        """Linear-interpolation percentile over an already-sorted list."""
        if not values:
            return 0.0
        if len(values) == 1:
            return values[0]
        rank = (pct / 100.0) * (len(values) - 1)
        lo = int(rank)
        hi = min(lo + 1, len(values) - 1)
        frac = rank - lo
        return values[lo] + (values[hi] - values[lo]) * frac

    @staticmethod
    def _calculate_stdev(values: List[float]) -> float:
        """Calculate standard deviation."""
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
        return variance ** 0.5

    def detect_regression(
        self,
        operation_name: str,
        threshold_percent: float = 10.0
    ) -> bool:
        """
        Detect performance regression.

        Args:
            operation_name: Operation to check
            threshold_percent: Threshold percentage for regression detection

        Returns:
            True if recent performance degraded beyond threshold
        """
        if operation_name not in self.metrics:
            return False

        metrics = self.metrics[operation_name]
        if len(metrics) < 20:
            return False

        midpoint = len(metrics) // 2
        older_mean = sum(metrics[:midpoint]) / midpoint
        recent_mean = sum(metrics[midpoint:]) / (len(metrics) - midpoint)

        if older_mean == 0:
            return False

        percent_change = ((recent_mean - older_mean) / older_mean) * 100
        return percent_change > threshold_percent
