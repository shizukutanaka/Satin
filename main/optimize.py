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
    """Enhanced performance monitoring system with adaptive optimization"""
    
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
        self._anomaly_detector = AnomalyDetector()
        self._batch_optimizer = BatchOptimizer()
        self._distributed_processor = DistributedProcessor()
        self._confidence_intervals = {
            'memory': (0, 0),
            'cpu': (0, 0),
            'disk': (0, 0),
            'network': (0, 0)
        }
        self._last_anomaly_check = time.time()
        self._anomaly_check_interval = 300  # 5 minutes
        self._memory_manager = MemoryManager()
        self._cache_manager = CacheManager()
        self._distributed_cache = DistributedCache()
        self._last_memory_optimization = time.time()
        self._memory_optimization_interval = 300  # 5 minutes
        self._adaptive_optimizer = AdaptiveOptimizer()
        self._resource_forecaster = ResourceForecaster()
        self._last_adaptive_optimization = time.time()
        self._adaptive_optimization_interval = 300  # 5 minutes
    
    async def adaptive_optimize(self):
        """Adaptively optimize resources based on current conditions"""
        if not self.enabled:
            return
            
        current_time = time.time()
        if current_time - self._last_adaptive_optimization < self._adaptive_optimization_interval:
            return
            
        # Get current metrics
        metrics = self.get_metrics()
        if not metrics:
            return
            
        # Forecast future usage
        predictions = await self._resource_forecaster.forecast_resources()
        
        # Analyze patterns
        patterns = self._analyze_resource_patterns(metrics)
        
        # Determine optimization strategy
        strategy = self._adaptive_optimizer.determine_strategy(
            metrics,
            predictions,
            patterns
        )
        
        # Apply optimization
        await self._adaptive_optimizer.apply_strategy(strategy)
        
        self._last_adaptive_optimization = current_time
    
    def _analyze_resource_patterns(self, metrics: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """Analyze resource usage patterns"""
        patterns = {}
        for name, metric in metrics.items():
            if 'history' in metric:
                values = [point['value'] for point in metric['history']]
                timestamps = [point['timestamp'] for point in metric['history']]
                patterns[name] = {
                    'trend': self._calculate_trend(values),
                    'seasonality': self._calculate_seasonality(values, timestamps),
                    'variance': self._calculate_variance(values),
                    'peak': max(values) if values else 0,
                    'avg': sum(values) / len(values) if values else 0
                }
        return patterns
    
    class AdaptiveOptimizer:
        """Adaptive optimization engine"""
        
        def __init__(self):
            self._strategies = {
                'memory': [
                    'compaction',
                    'cache_clearing',
                    'heap_optimization'
                ],
                'cpu': [
                    'load_balancing',
                    'priority_adjustment',
                    'process_scheduling'
                ],
                'disk': [
                    'io_optimization',
                    'cache_clearing',
                    'data_compression'
                ],
                'network': [
                    'connection_optimization',
                    'traffic_compression',
                    'load_balancing'
                ]
            }
            self._last_strategies = {}
            self._strategy_effectiveness = {}
            
        def determine_strategy(self, 
                            metrics: Dict[str, Any],
                            predictions: Dict[str, Any],
                            patterns: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
            """Determine optimal optimization strategy"""
            strategy = {}
            for resource in self._strategies.keys():
                if resource in metrics:
                    current = metrics[resource][-1]['value']
                    predicted = predictions[resource]
                    pattern = patterns[resource]
                    
                    # Determine strategy based on conditions
                    if predicted > 90:  # High usage predicted
                        strategy[resource] = self._strategies[resource][0]
                    elif predicted > 80:  # Moderate usage
                        strategy[resource] = self._strategies[resource][1]
                    else:  # Low usage
                        strategy[resource] = self._strategies[resource][2]
                        
                    # Consider previous strategy effectiveness
                    if resource in self._strategy_effectiveness:
                        if self._strategy_effectiveness[resource] < 0.5:
                            strategy[resource] = self._strategies[resource][0]
                            
            return strategy
            
        async def apply_strategy(self, strategy: Dict[str, str]):
            """Apply optimization strategy"""
            for resource, opt_strategy in strategy.items():
                if resource in self._strategies:
                    await getattr(self, f'_optimize_{opt_strategy}')(resource)
                    
        async def _optimize_compaction(self, resource: str):
            """Optimize memory compaction"""
            import gc
            gc.collect()
            
        async def _optimize_cache_clearing(self, resource: str):
            """Clear cache"""
            # Implementation depends on resource type
            pass
            
        async def _optimize_heap_optimization(self, resource: str):
            """Optimize heap memory"""
            # Implementation depends on resource type
            pass
            
        async def _optimize_load_balancing(self, resource: str):
            """Balance resource load"""
            # Implementation depends on resource type
            pass
            
        async def _optimize_priority_adjustment(self, resource: str):
            """Adjust process priority"""
            # Implementation depends on resource type
            pass
            
        async def _optimize_process_scheduling(self, resource: str):
            """Optimize process scheduling"""
            # Implementation depends on resource type
            pass
            
        async def _optimize_io_optimization(self, resource: str):
            """Optimize disk I/O"""
            # Implementation depends on resource type
            pass
            
        async def _optimize_data_compression(self, resource: str):
            """Compress data"""
            # Implementation depends on resource type
            pass
            
        async def _optimize_connection_optimization(self, resource: str):
            """Optimize network connections"""
            # Implementation depends on resource type
            pass
            
        async def _optimize_traffic_compression(self, resource: str):
            """Compress network traffic"""
            # Implementation depends on resource type
            pass
            
        async def _optimize_load_balancing(self, resource: str):
            """Balance resource load"""
            # Implementation depends on resource type
            pass
            
        async def evaluate_strategy(self, resource: str, strategy: str):
            """Evaluate strategy effectiveness"""
            if resource not in self._last_strategies:
                self._last_strategies[resource] = strategy
                return
                
            # Compare current metrics with previous
            current_metrics = await self._get_current_metrics(resource)
            previous_metrics = await self._get_previous_metrics(resource)
            
            # Calculate improvement
            improvement = self._calculate_improvement(
                current_metrics,
                previous_metrics
            )
            
            # Update strategy effectiveness
            self._strategy_effectiveness[resource] = improvement
            
        async def _get_current_metrics(self, resource: str) -> Dict[str, float]:
            """Get current resource metrics"""
            # Implementation depends on resource type
            pass
            
        async def _get_previous_metrics(self, resource: str) -> Dict[str, float]:
            """Get previous resource metrics"""
            # Implementation depends on resource type
            pass
            
        def _calculate_improvement(self, 
                                current: Dict[str, float],
                                previous: Dict[str, float]) -> float:
            """Calculate improvement percentage"""
            if not previous:
                return 1.0
                
            improvement = 0.0
            count = 0
            
            for metric, current_value in current.items():
                if metric in previous:
                    prev_value = previous[metric]
                    if prev_value > 0:
                        improvement += (current_value - prev_value) / prev_value
                        count += 1
                        
            return improvement / count if count > 0 else 1.0
    
    async def optimize_memory(self):
        """Optimize memory usage"""
        if not self.enabled:
            return
            
        current_time = time.time()
        if current_time - self._last_memory_optimization < self._memory_optimization_interval:
            return
            
        # Get current memory usage
        memory_usage = await self.get_memory_usage()
        
        # Predict future usage
        future_usage = await self.predict_resource_usage('memory', time.time() + 3600)
        
        # Determine optimization strategy
        if future_usage > 90:  # High usage predicted
            await self._memory_manager.compact_memory()
            await self._cache_manager.clear_cache()
        elif future_usage > 80:  # Moderate usage
            await self._memory_manager.optimize_heap()
        else:  # Low usage
            await self._memory_manager.optimize_cache()
            
        self._last_memory_optimization = current_time
    
    async def optimize_batch_memory(self, items: List[Any], batch_size: int = 100) -> List[Any]:
        """Optimize memory usage during batch processing"""
        if not items:
            return []
            
        # Calculate optimal batch size based on memory
        memory_usage = await self.get_memory_usage()
        optimal_batch_size = self._batch_optimizer.calculate_memory_optimal_batch_size(
            batch_size,
            memory_usage
        )
        
        # Process in batches with memory optimization
        results = []
        for i in range(0, len(items), optimal_batch_size):
            batch = items[i:i + optimal_batch_size]
            
            # Optimize memory before processing
            await self._memory_manager.preprocess_batch(batch)
            
            # Process batch
            batch_results = await self._process_batch(batch)
            results.extend(batch_results)
            
            # Optimize memory after processing
            await self._memory_manager.postprocess_batch(batch_results)
            
            # Monitor memory usage
            await self.monitor_memory_usage(batch, batch_results)
            
        return results
    
    async def monitor_memory_usage(self, batch: List[Any], results: List[Any]):
        """Monitor memory usage during batch processing"""
        metrics = {
            'memory': await self.get_memory_usage(),
            'heap': await self.get_heap_usage(),
            'cache': await self.get_cache_usage()
        }
        
        # Update metrics
        for resource, value in metrics.items():
            await self.add_metric(resource, value)
            
        # Detect memory anomalies
        await self.detect_memory_anomalies()
    
    async def detect_memory_anomalies(self):
        """Detect memory usage anomalies"""
        memory_usage = await self.get_memory_usage()
        heap_usage = await self.get_heap_usage()
        cache_usage = await self.get_cache_usage()
        
        # Check for anomalies
        if memory_usage > 95:
            await self._anomaly_detector.handle_memory_anomaly('critical')
        elif memory_usage > 90:
            await self._anomaly_detector.handle_memory_anomaly('high')
        
        if heap_usage > 85:
            await self._anomaly_detector.handle_heap_anomaly('medium')
        
        if cache_usage > 90:
            await self._anomaly_detector.handle_cache_anomaly('warning')
    
    class MemoryManager:
        """Memory management system"""
        
        def __init__(self):
            self._last_compaction = time.time()
            self._compaction_interval = 3600  # 1 hour
            self._last_heap_optimization = time.time()
            self._heap_optimization_interval = 1800  # 30 minutes
            
        async def compact_memory(self):
            """Compact memory usage"""
            import gc
            gc.collect()
            
            # Force garbage collection
            gc.collect(generation=2)
            
            # Optimize memory layout
            await self._optimize_memory_layout()
            
        async def _optimize_memory_layout(self):
            """Optimize memory layout"""
            # Implementation depends on specific memory management needs
            pass
            
        async def optimize_heap(self):
            """Optimize heap memory"""
            current_time = time.time()
            if current_time - self._last_heap_optimization < self._heap_optimization_interval:
                return
                
            # Implement heap optimization strategies
            await self._optimize_heap_layout()
            await self._reduce_fragmentation()
            
            self._last_heap_optimization = current_time
            
        async def _optimize_heap_layout(self):
            """Optimize heap layout"""
            # Implementation depends on specific heap management needs
            pass
            
        async def _reduce_fragmentation(self):
            """Reduce memory fragmentation"""
            # Implementation depends on specific fragmentation reduction needs
            pass
            
        async def optimize_cache(self):
            """Optimize cache usage"""
            # Clear least used cache items
            await self._clear_least_used()
            
            # Compress cache items
            await self._compress_cache_items()
            
        async def _clear_least_used(self):
            """Clear least used cache items"""
            # Implementation depends on cache management needs
            pass
            
        async def _compress_cache_items(self):
            """Compress cache items"""
            # Implementation depends on cache compression needs
            pass
            
        async def preprocess_batch(self, batch: List[Any]):
            """Preprocess batch for memory optimization"""
            # Optimize memory before batch processing
            await self.compact_memory()
            await self.optimize_heap()
            
        async def postprocess_batch(self, results: List[Any]):
            """Postprocess batch for memory optimization"""
            # Optimize memory after batch processing
            await self.optimize_heap()
            await self.optimize_cache()
    
    async def calculate_confidence_interval(self, resource: str, confidence: float = 0.95) -> Tuple[float, float]:
        """Calculate confidence interval for resource usage"""
        if resource not in self.metrics:
            return (0, 0)
            
        values = [point['value'] for point in self.metrics[resource]['history']]
        if not values:
            return (0, 0)
            
        mean = np.mean(values)
        std = np.std(values)
        n = len(values)
        
        z_score = 1.96  # For 95% confidence
        margin = z_score * (std / np.sqrt(n))
        
        return (mean - margin, mean + margin)
    
    async def detect_anomalies(self):
        """Detect anomalies in resource usage"""
        if not self.enabled:
            return
            
        current_time = time.time()
        if current_time - self._last_anomaly_check < self._anomaly_check_interval:
            return
            
        for resource, history in self.metrics.items():
            if 'history' in history:
                values = [point['value'] for point in history['history']]
                latest = values[-1]
                
                # Get confidence interval
                lower, upper = await self.calculate_confidence_interval(resource)
                
                # Check for anomaly
                if latest < lower or latest > upper:
                    await self._anomaly_detector.handle_anomaly(resource, latest)
                    
        self._last_anomaly_check = current_time
    
    async def optimize_batch_processing(self, items: List[Any], batch_size: int = 100) -> List[Any]:
        """Optimize batch processing with dynamic batch size"""
        if not items:
            return []
            
        # Calculate optimal batch size based on current system load
        cpu_load = await self.get_cpu_load()
        memory_usage = await self.get_memory_usage()
        
        # Adjust batch size based on system resources
        adjusted_batch_size = self._batch_optimizer.calculate_optimal_batch_size(
            batch_size,
            cpu_load,
            memory_usage
        )
        
        # Process items in batches
        results = []
        for i in range(0, len(items), adjusted_batch_size):
            batch = items[i:i + adjusted_batch_size]
            batch_results = await self._process_batch(batch)
            results.extend(batch_results)
            
            # Monitor resource usage during processing
            await self.monitor_batch_processing(batch, batch_results)
            
        return results
    
    async def monitor_batch_processing(self, batch: List[Any], results: List[Any]):
        """Monitor resource usage during batch processing"""
        metrics = {
            'cpu': await self.get_cpu_load(),
            'memory': await self.get_memory_usage(),
            'disk': await self.get_disk_usage(),
            'network': await self.get_network_usage()
        }
        
        # Update metrics
        for resource, value in metrics.items():
            await self.add_metric(resource, value)
            
        # Detect anomalies during processing
        await self.detect_anomalies()
    
    async def process_distributed(self, items: List[Any], num_nodes: int = 4) -> List[Any]:
        """Process items across distributed nodes"""
        if not items:
            return []
            
        # Split items across nodes
        chunks = self._split_items(items, num_nodes)
        
        # Process in parallel
        results = await asyncio.gather(*[
            self._distributed_processor.process_chunk(chunk)
            for chunk in chunks
        ])
        
        # Combine results
        return [item for sublist in results for item in sublist]
    
    def _split_items(self, items: List[Any], num_nodes: int) -> List[List[Any]]:
        """Split items into chunks for distributed processing"""
        chunk_size = len(items) // num_nodes
        chunks = []
        for i in range(num_nodes):
            start = i * chunk_size
            end = start + chunk_size if i < num_nodes - 1 else len(items)
            chunks.append(items[start:end])
        return chunks
    
    class AnomalyDetector:
        """Resource usage anomaly detection"""
        
        def __init__(self):
            self._alerts = []
            self._last_alert = time.time()
            self._alert_interval = 300  # 5 minutes
            
        async def handle_anomaly(self, resource: str, value: float):
            """Handle detected anomaly"""
            current_time = time.time()
            if current_time - self._last_alert < self._alert_interval:
                return
                
            # Generate alert
            alert = {
                'timestamp': current_time,
                'resource': resource,
                'value': value,
                'severity': self._calculate_severity(value)
            }
            self._alerts.append(alert)
            
            # Take corrective action
            await self._take_corrective_action(resource, value)
            
            self._last_alert = current_time
            
        def _calculate_severity(self, value: float) -> str:
            """Calculate anomaly severity"""
            if value > 95:
                return 'critical'
            elif value > 90:
                return 'high'
            elif value > 85:
                return 'medium'
            return 'low'
            
        async def _take_corrective_action(self, resource: str, value: float):
            """Take corrective action for anomaly"""
            if resource == 'memory':
                await self._optimize_memory()
            elif resource == 'cpu':
                await self._optimize_cpu()
            elif resource == 'disk':
                await self._optimize_disk()
            elif resource == 'network':
                await self._optimize_network()
    
    class BatchOptimizer:
        """Batch processing optimization"""
        
        def __init__(self):
            self._optimal_batch_sizes = {}
            self._last_optimization = time.time()
            self._optimization_interval = 300  # 5 minutes
            
        def calculate_optimal_batch_size(self, 
                                        current_size: int,
                                        cpu_load: float,
                                        memory_usage: float) -> int:
            """Calculate optimal batch size based on system resources"""
            # Adjust batch size based on CPU load
            cpu_factor = 1.0 - (cpu_load / 100)
            
            # Adjust batch size based on memory usage
            memory_factor = 1.0 - (memory_usage / 100)
            
            # Calculate final adjustment factor
            adjustment = cpu_factor * memory_factor
            
            # Apply adjustment with minimum size constraint
            optimal_size = max(1, int(current_size * adjustment))
            
            return optimal_size
    
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
