"""
キャッシュ管理システム
バージョン: 1.0.0
特徴:
- メモリキャッシュ
- ディスクキャッシュ
- キャッシュの自動クリーンアップ
- キャッシュヒット率の監視
- キャッシュの永続化
"""
import os
import json
import logging
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple, TypeVar, Generic
from datetime import datetime, timedelta
from config_manager import get_config_manager
import asyncio
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
from statistics import mean

T = TypeVar('T')

logger = logging.getLogger(__name__)

class CacheStats:
    """Cache statistics tracking"""
    def __init__(self):
        self.hits = 0
        self.misses = 0
        self.last_update = datetime.now()
        self.latencies = []  # Cache access latencies in milliseconds
        self.max_latency = 0
        self.min_latency = float('inf')
        self.avg_latency = 0
        
    def record_hit(self, latency_ms: float):
        """Record a cache hit"""
        self.hits += 1
        self._update_latency(latency_ms)
        
    def record_miss(self, latency_ms: float):
        """Record a cache miss"""
        self.misses += 1
        self._update_latency(latency_ms)
        
    def _update_latency(self, latency_ms: float):
        """Update latency statistics"""
        self.latencies.append(latency_ms)
        if len(self.latencies) > 1000:  # Keep last 1000 samples
            self.latencies.pop(0)
        
        self.max_latency = max(self.max_latency, latency_ms)
        self.min_latency = min(self.min_latency, latency_ms)
        self.avg_latency = mean(self.latencies) if self.latencies else 0
        
    def get_stats(self) -> Dict[str, Any]:
        """Get current cache statistics"""
        total = self.hits + self.misses
        return {
            'hit_rate': (self.hits / total * 100) if total > 0 else 0,
            'miss_rate': (self.misses / total * 100) if total > 0 else 0,
            'total_requests': total,
            'average_latency': self.avg_latency,
            'max_latency': self.max_latency,
            'min_latency': self.min_latency,
            'last_update': self.last_update.isoformat()
        }

logger = logging.getLogger(__name__)

class CacheManager:
    """Enhanced cache management system"""
    
    def __init__(self):
        """Initialize cache manager"""
        self.config = get_config_manager()
        self.settings = self.config.get_plugin_config("cache_manager")
        
        if self.settings:
            self.memory_cache_size = self.settings.get("memory_cache_size", 1024)  # Memory cache size (MB)
            self.disk_cache_size = self.settings.get("disk_cache_size", 1024)  # Disk cache size (MB)
            self.cache_ttl = self.settings.get("cache_ttl", 3600)  # Cache TTL (seconds)
            self.cleanup_interval = self.settings.get("cleanup_interval", 3600)  # Cleanup interval (seconds)
            self.max_concurrent_tasks = self.settings.get("max_concurrent_tasks", 5)  # Maximum concurrent tasks
            
            # Cache directory initialization
            self.cache_dir = Path(self.config.config_path).parent / "cache"
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            
            # Memory cache initialization with LRU
            self.memory_cache = OrderedDict()
            self.memory_cache_size_bytes = self.memory_cache_size * 1024 * 1024
            
            # Thread pool for async operations
            self.executor = ThreadPoolExecutor(max_workers=self.max_concurrent_tasks)
            
            # Cache cleanup thread
            self.cleanup_thread = threading.Thread(target=self._cleanup_cache)
            self.cleanup_thread.daemon = True
            self.cleanup_thread.start()
            
            # Cache statistics
            self.stats = CacheStats()
            
            # Cache warmup
            self._warmup_cache()
            
    def cache(self, func: Callable[..., T]) -> Callable[..., T]:
        """Cache decorator with improved performance"""
        
        @lru_cache(maxsize=self.memory_cache_size)
        async def async_wrapper(*args, **kwargs) -> T:
            """Async wrapper for cache operations"""
            start_time = time.time()
            
            # Check memory cache
            key = self._generate_cache_key(func.__name__, args, kwargs)
            if key in self.memory_cache:
                value, timestamp = self.memory_cache[key]
                if datetime.now() - timestamp < timedelta(seconds=self.cache_ttl):
                    latency = (time.time() - start_time) * 1000
                    self.stats.record_hit(latency)
                    return value
            
            # Execute function with async support
            try:
                result = await func(*args, **kwargs)
            except Exception as e:
                logger.error(f"Error executing cached function: {str(e)}")
                raise
            
            # Update memory cache
            self.memory_cache[key] = (result, datetime.now())
            if len(self.memory_cache) > self.memory_cache_size:
                self.memory_cache.popitem(last=False)  # Remove oldest item
            
            # Update disk cache asynchronously
            asyncio.create_task(self._update_disk_cache_async(key, result))
            
            latency = (time.time() - start_time) * 1000
            self.stats.record_miss(latency)
            return result
            
        return async_wrapper
    
    async def _update_disk_cache_async(self, key: str, value: Any) -> None:
        """Async disk cache update"""
        try:
            cache_file = self.cache_dir / f"{key}.json"
            async with aiofiles.open(cache_file, 'w', encoding='utf-8') as f:
                await f.write(json.dumps({
                    "value": value,
                    "timestamp": datetime.now().isoformat()
                }))
        except Exception as e:
            logger.error(f"Failed to update disk cache: {str(e)}")
    
    def _warmup_cache(self) -> None:
        """Cache warmup for frequently accessed items"""
        try:
            # Load frequently accessed items from disk cache
            for cache_file in self.cache_dir.glob("*.json"):
                try:
                    with open(cache_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        key = cache_file.stem
                        self.memory_cache[key] = (data['value'], 
                                                datetime.fromisoformat(data['timestamp']))
                except Exception as e:
                    logger.warning(f"Failed to warmup cache from {cache_file}: {str(e)}")
        except Exception as e:
            logger.error(f"Cache warmup failed: {str(e)}")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        return self.stats.get_stats()
    
    def clear_cache(self) -> None:
        """Clear both memory and disk cache"""
        try:
            # Clear memory cache
            self.memory_cache.clear()
            
            # Clear disk cache
            for cache_file in self.cache_dir.glob("*.json"):
                try:
                    cache_file.unlink()
                except Exception as e:
                    logger.warning(f"Failed to delete cache file: {str(e)}")
            
            # Reset statistics
            self.stats = CacheStats()
            
        except Exception as e:
            logger.error(f"Failed to clear cache: {str(e)}")
            raise
            
    def cache(self, func: Callable) -> Callable:
        """キャッシュデコレータ"""
        @lru_cache(maxsize=self.memory_cache_size)
        def wrapper(*args, **kwargs):
            # メモリキャッシュのチェック
            key = self._generate_cache_key(func.__name__, args, kwargs)
            if key in self.memory_cache:
                value, timestamp = self.memory_cache[key]
                if datetime.now() - timestamp < timedelta(seconds=self.cache_ttl):
                    self.cache_hits += 1
                    return value
                
            # 関数の実行
            result = func(*args, **kwargs)
            
            # メモリキャッシュの更新
            self.memory_cache[key] = (result, datetime.now())
            
            # ディスクキャッシュの更新
            self._update_disk_cache(key, result)
            
            self.cache_misses += 1
            return result
        
        return wrapper
    
    def _generate_cache_key(self, func_name: str, args: Tuple, kwargs: Dict) -> str:
        """キャッシュキーの生成"""
        return f"{func_name}_{hash(args)}_{hash(tuple(sorted(kwargs.items())))}"
    
    def _update_disk_cache(self, key: str, value: Any) -> None:
        """ディスクキャッシュの更新"""
        try:
            cache_file = self.cache_dir / f"{key}.json"
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump({
                    "value": value,
                    "timestamp": datetime.now().isoformat()
                }, f)
        except Exception as e:
            logger.error(f"ディスクキャッシュの更新に失敗しました: {e}")
    
    async def _cleanup_cache(self) -> None:
        """Async cache cleanup"""
        while True:
            try:
                # Memory cache cleanup
                current_size = sum(len(json.dumps(v[0])) for v in self.memory_cache.values())
                if current_size > self.memory_cache_size_bytes:
                    # Remove oldest items until we're under size limit
                    while current_size > self.memory_cache_size_bytes and self.memory_cache:
                        oldest_key = next(iter(self.memory_cache))
                        del self.memory_cache[oldest_key]
                        current_size = sum(len(json.dumps(v[0])) for v in self.memory_cache.values())
                
                # Disk cache cleanup
                total_size = 0
                cache_files = list(self.cache_dir.glob("*.json"))
                
                # Sort by modification time
                cache_files.sort(key=lambda f: os.path.getmtime(f))
                
                for cache_file in cache_files:
                    try:
                        data = json.loads(cache_file.read_text())
                        timestamp = datetime.fromisoformat(data['timestamp'])
                        
                        if datetime.now() - timestamp > timedelta(seconds=self.cache_ttl):
                            cache_file.unlink()
                            continue
                            
                        total_size += cache_file.stat().st_size
                        
                        if total_size > self.disk_cache_size * 1024 * 1024:
                            # Remove oldest files until we're under size limit
                            while total_size > self.disk_cache_size * 1024 * 1024 and cache_files:
                                oldest_file = cache_files[0]
                                oldest_file.unlink()
                                cache_files.pop(0)
                                total_size = sum(f.stat().st_size for f in cache_files)
                                
                    except Exception as e:
                        logger.error(f"Error during disk cache cleanup: {str(e)}")
                        
                await asyncio.sleep(self.cleanup_interval)
                
            except Exception as e:
                logger.error(f"Cache cleanup error: {str(e)}")
                await asyncio.sleep(self.cleanup_interval)
            try:
                current_size += cache_file.stat().st_size
                cache_files.append(cache_file)
            except Exception:
                continue
        
        # キャッシュサイズの制限を超えた場合、古いキャッシュを削除
        if current_size > self.disk_cache_size * 1024 * 1024:
            cache_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            for cache_file in cache_files:
                if current_size <= self.disk_cache_size * 1024 * 1024:
                    break
                try:
                    cache_file.unlink()
                    current_size -= cache_file.stat().st_size
                except Exception:
                    continue
    
    def _update_cache_stats(self) -> None:
        """キャッシュ統計の更新"""
        if datetime.now() - self.last_stats_update >= timedelta(seconds=300):
            total = self.cache_hits + self.cache_misses
            hit_rate = (self.cache_hits / total * 100) if total > 0 else 0
            logger.info(f"キャッシュ統計: ヒット率 {hit_rate:.1f}%, ヒット {self.cache_hits}, ミス {self.cache_misses}")
            self.last_stats_update = datetime.now()
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """キャッシュ統計を取得"""
        total = self.cache_hits + self.cache_misses
        hit_rate = (self.cache_hits / total * 100) if total > 0 else 0
        return {
            "hit_rate": hit_rate,
            "hits": self.cache_hits,
            "misses": self.cache_misses,
            "total": total,
            "memory_size": self.memory_cache_size,
            "disk_size": self.disk_cache_size,
            "cache_ttl": self.cache_ttl
        }
