"""
Performance optimization utilities for Satin
"""
import functools
import time
from typing import Callable, Any, Optional, List, Dict, Tuple, TypeVar, Generic
import asyncio
from concurrent.futures import ThreadPoolExecutor
import weakref
from collections import OrderedDict
import json
import os
import logging
import aiofiles

T = TypeVar('T')

class PerformanceMonitor:
    """Enhanced performance monitoring system"""
    
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self.metrics = OrderedDict()  # Use OrderedDict for better memory efficiency
        self._lock = asyncio.Lock()
        self._executor = ThreadPoolExecutor(max_workers=4)
        self._last_cleanup = time.time()
        self._cleanup_interval = 3600  # 1 hour
        self._max_metrics = 1000  # Maximum number of metrics to keep
    
    def timeit(self, func: Optional[Callable] = None, name: Optional[str] = None):
        """Async performance measurement decorator"""
        if func is None:
            return lambda f: self.timeit(f, name)
            
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            if not self.enabled:
                return await func(*args, **kwargs)
                
            start_time = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                elapsed = time.perf_counter() - start_time
                func_name = name or func.__name__
                await self.async_record_metric(func_name, elapsed)
                
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            if not self.enabled:
                return func(*args, **kwargs)
                
            start_time = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                elapsed = time.perf_counter() - start_time
                func_name = name or func.__name__
                self.record_metric(func_name, elapsed)
                
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    async def async_record_metric(self, name: str, value: float):
        """Async metric recording with cleanup"""
        async with self._lock:
            if name not in self.metrics:
                self.metrics[name] = []
            self.metrics[name].append(value)
            
            # Periodic cleanup
            current_time = time.time()
            if current_time - self._last_cleanup > self._cleanup_interval:
                await self._cleanup_metrics()
                self._last_cleanup = current_time
                
    def record_metric(self, name: str, value: float):
        """Sync metric recording with cleanup"""
        if name not in self.metrics:
            self.metrics[name] = []
        self.metrics[name].append(value)
        
        # Periodic cleanup
        current_time = time.time()
        if current_time - self._last_cleanup > self._cleanup_interval:
            self._cleanup_metrics()
            self._last_cleanup = current_time
            
    async def _cleanup_metrics(self):
        """Cleanup old metrics"""
        async with self._lock:
            # Remove metrics older than 24 hours
            cutoff = time.time() - 86400
            for name in list(self.metrics.keys()):
                if name.endswith('_timestamp'):
                    continue
                    
                timestamps = self.metrics.get(name + '_timestamp', [])
                if not timestamps:
                    continue
                    
                # Remove old values
                while timestamps and timestamps[0] < cutoff:
                    timestamps.pop(0)
                    self.metrics[name].pop(0)
                    
                # Remove empty metrics
                if not timestamps:
                    del self.metrics[name]
                    del self.metrics[name + '_timestamp']
                    
    def get_metrics(self) -> dict:
        """Get all recorded metrics with detailed statistics"""
        return {
            name: {
                'count': len(times),
                'total': sum(times),
                'avg': sum(times) / len(times) if times else 0,
                'min': min(times) if times else 0,
                'max': max(times) if times else 0,
                'std_dev': self._calculate_std_dev(times),
                'p95': self._calculate_percentile(times, 95),
                'p99': self._calculate_percentile(times, 99)
            }
            for name, times in self.metrics.items()
            if name.endswith('_timestamp')
        }
        
    def _calculate_std_dev(self, values: List[float]) -> float:
        """Calculate standard deviation"""
        if not values:
            return 0
            
        mean_val = sum(values) / len(values)
        return (sum((x - mean_val) ** 2 for x in values) / len(values)) ** 0.5
        
    def _calculate_percentile(self, values: List[float], percentile: float) -> float:
        """Calculate percentile value"""
        if not values:
            return 0
            
        sorted_values = sorted(values)
        index = int(len(sorted_values) * (percentile / 100))
        return sorted_values[index]
    
    def get_metrics(self) -> dict:
        """Get all recorded metrics"""
        return {
            name: {
                'count': len(times),
                'total': sum(times),
                'avg': sum(times) / len(times),
                'min': min(times),
                'max': max(times)
            }
            for name, times in self.metrics.items()
        }

def cache_result(ttl: int = 300, max_size: int = 1000):
    """Enhanced caching decorator with size limit and async support"""
    def decorator(func):
        cache = OrderedDict()
        
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            key = (args, frozenset(kwargs.items()))
            
            # Check cache
            if key in cache:
                result, timestamp = cache[key]
                if time.time() - timestamp < ttl:
                    return result
            
            # Call function and cache result
            result = await func(*args, **kwargs)
            cache[key] = (result, time.time())
            
            # Enforce size limit
            if len(cache) > max_size:
                cache.popitem(last=False)
            
            return result
            
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            key = (args, frozenset(kwargs.items()))
            
            # Check cache
            if key in cache:
                result, timestamp = cache[key]
                if time.time() - timestamp < ttl:
                    return result
            
            # Call function and cache result
            result = func(*args, **kwargs)
            cache[key] = (result, time.time())
            
            # Enforce size limit
            if len(cache) > max_size:
                cache.popitem(last=False)
            
            return result
            
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    return decorator

async def batch_process(items: List[T], process_func: Callable, batch_size: int = 10, max_workers: int = 4) -> List[T]:
    """Enhanced batch processing with async support and worker pool"""
    results = []
    executor = ThreadPoolExecutor(max_workers=max_workers)
    
    async def process_batch(batch: List[T]) -> List[T]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(executor, process_func, batch)
    
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        results.extend(await process_batch(batch))
    
    return results
    
async def parallel_process(items: List[T], process_func: Callable, max_workers: int = 4) -> List[T]:
    """Process items in parallel using asyncio"""
    results = []
    
    async def process_item(item: T) -> T:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, process_func, item)
    
    tasks = [process_item(item) for item in items]
    results = await asyncio.gather(*tasks)
    return results

# Global instance
monitor = PerformanceMonitor()

def enable_monitoring():
    """Enable performance monitoring"""
    monitor.enabled = True

def disable_monitoring():
    """Disable performance monitoring"""
    monitor.enabled = False

def get_performance_metrics() -> dict:
    """Get current performance metrics"""
    return monitor.get_metrics()
