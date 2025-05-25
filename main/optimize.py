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
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from statsmodels.tsa.seasonal import seasonal_decompose
import pandas as pd

T = TypeVar('T')

class PerformanceMonitor:
    """Enhanced performance monitoring system with ML-based optimization"""
    
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self.metrics = OrderedDict()
        self._lock = asyncio.Lock()
        self._executor = ThreadPoolExecutor(max_workers=4)
        self._last_cleanup = time.time()
        self._cleanup_interval = 3600  # 1 hour
        self._max_metrics = 1000  # Maximum number of metrics to keep
        self._resource_optimizer = ResourceOptimizer()
        self._last_optimization = time.time()
        self._optimization_interval = 3600  # 1 hour
        self._ml_optimizer = MLOptimizer()
        self._last_ml_training = time.time()
        self._ml_training_interval = 3600 * 24  # 24 hours
        self._ml_models = {
            'memory': None,
            'cpu': None,
            'disk': None,
            'network': None
        }
    
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

def cache_result(ttl: int = 300, max_size: int = 1000, compression: bool = False):
    """Enhanced caching decorator with size limit, async support, and compression"""
    def decorator(func):
        cache = OrderedDict()
        
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            key = (args, frozenset(kwargs.items()))
            
            # Check cache
            if key in cache:
                result, timestamp, compressed = cache[key]
                if time.time() - timestamp < ttl:
                    if compressed and compression:
                        result = decompress_result(result)
                    return result
            
            # Call function and cache result
            result = await func(*args, **kwargs)
            
            # Compress result if enabled
            if compression:
                result = compress_result(result)
            
            cache[key] = (result, time.time(), compression)
            
            # Enforce size limit
            if len(cache) > max_size:
                cache.popitem(last=False)
            
            return result
            
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            key = (args, frozenset(kwargs.items()))
            
            # Check cache
            if key in cache:
                result, timestamp, compressed = cache[key]
                if time.time() - timestamp < ttl:
                    if compressed and compression:
                        result = decompress_result(result)
                    return result
            
            # Call function and cache result
            result = func(*args, **kwargs)
            
            # Compress result if enabled
            if compression:
                result = compress_result(result)
            
            cache[key] = (result, time.time(), compression)
            
            # Enforce size limit
            if len(cache) > max_size:
                cache.popitem(last=False)
            
            return result
            
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    return decorator

# Compression utilities
def compress_result(result):
    """Compress result using zlib"""
    import zlib
    import pickle
    return zlib.compress(pickle.dumps(result))

def decompress_result(compressed_result):
    """Decompress result"""
    import zlib
    import pickle
    return pickle.loads(zlib.decompress(compressed_result))

# Memory optimization
def optimize_memory():
    """Optimize memory usage"""
    import gc
    gc.collect()
    return gc.get_count()

async def batch_process(items: List[T], process_func: Callable, batch_size: int = 10, max_workers: int = 4, optimize: bool = True) -> List[T]:
    """Enhanced batch processing with async support, worker pool, and optimization"""
    results = []
    executor = ThreadPoolExecutor(max_workers=max_workers)
    
    async def process_batch(batch: List[T]) -> List[T]:
        loop = asyncio.get_event_loop()
        # Optimize batch size based on system resources
        if optimize:
            batch_size = optimize_batch_size(len(batch))
        return await loop.run_in_executor(executor, process_func, batch[:batch_size])
    
    def optimize_batch_size(total: int) -> int:
        """Optimize batch size based on system resources"""
        import psutil
        memory = psutil.virtual_memory()
        cpu_count = psutil.cpu_count()
        
        # Adjust batch size based on available resources
        if memory.percent > 80:
            return max(1, total // 2)
        elif cpu_count > 4:
            return min(total, 100)
        return min(total, 50)
    
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        results.extend(await process_batch(batch))
    
    return results
    
async def parallel_process(items: List[T], process_func: Callable, max_workers: int = 4, optimize: bool = True) -> List[T]:
    """Process items in parallel using asyncio with optimization"""
    results = []
    
    async def process_item(item: T) -> T:
        loop = asyncio.get_event_loop()
        # Optimize processing based on item type
        if optimize:
            item = optimize_item(item)
        return await loop.run_in_executor(None, process_func, item)
    
    def optimize_item(item: T) -> T:
        """Optimize item processing"""
        import sys
        item_size = sys.getsizeof(item)
        
        # Optimize based on item size
        if item_size > 1024 * 1024:  # Large items
            return optimize_large_item(item)
        return item
    
    def optimize_large_item(item: T) -> T:
        """Optimize large items"""
        import pickle
        import zlib
        
        # Compress large items
        compressed = zlib.compress(pickle.dumps(item))
        return pickle.loads(zlib.decompress(compressed))
    
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
