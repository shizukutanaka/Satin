"""
Performance optimization utilities for Satin
"""
import functools
import time
from typing import Callable, Any, Optional

class PerformanceMonitor:
    """Track and log performance metrics"""
    
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self.metrics = {}
    
    def timeit(self, func: Optional[Callable] = None, name: Optional[str] = None):
        """Decorator to measure function execution time"""
        if func is None:
            return lambda f: self.timeit(f, name)
            
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
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
        return wrapper
    
    def record_metric(self, name: str, value: float):
        """Record a performance metric"""
        if name not in self.metrics:
            self.metrics[name] = []
        self.metrics[name].append(value)
    
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

def cache_result(ttl: int = 300):
    """Cache function results with TTL"""
    def decorator(func):
        cache = {}
        
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Create a key from function arguments
            key = (args, frozenset(kwargs.items()))
            
            # Check cache
            if key in cache:
                result, timestamp = cache[key]
                if time.time() - timestamp < ttl:
                    return result
            
            # Call function and cache result
            result = func(*args, **kwargs)
            cache[key] = (result, time.time())
            return result
            
        return wrapper
    return decorator

def batch_process(items: list, process_func: Callable, batch_size: int = 10) -> list:
    """Process items in batches"""
    results = []
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        results.extend(process_func(batch))
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
