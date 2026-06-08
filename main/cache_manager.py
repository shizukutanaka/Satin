"""
キャッシュ管理システム
特徴:
- メモリキャッシュ
- ディスクキャッシュ
- キャッシュの自動クリーンアップ
- キャッシュヒット率の監視
- キャッシュの永続化
"""
import os
import json
import hashlib
import logging
import threading
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple, TypeVar
from datetime import datetime, timedelta
from config_manager import get_config_manager
import asyncio
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
from statistics import mean

try:  # pragma: no cover - optional dependency
    import aiofiles
except ImportError:  # pragma: no cover - optional dependency guard
    aiofiles = None

T = TypeVar('T')

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
        self.last_update = datetime.now()
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
        self.settings = self.config.get_plugin_config("cache_manager") or {}

        self.memory_cache_size = self._validated_int("memory_cache_size", default=1024, minimum=1)
        self.disk_cache_size = self._validated_int("disk_cache_size", default=1024, minimum=0)
        self.cache_ttl = self._validated_int("cache_ttl", default=3600, minimum=1)
        self.cleanup_interval = self._validated_int("cleanup_interval", default=3600, minimum=1)
        self.max_concurrent_tasks = self._validated_int("max_concurrent_tasks", default=5, minimum=1)
        self.max_cache_items = self._validated_int("max_cache_items", default=10000, minimum=0)

        # コンテンツタイプ別 TTL (秒): YouTube動画/論文/Webページで異なる有効期間
        self.cache_ttl_map = {
            'video': 86400 * 7,      # 7日: YouTube動画（頻繁に更新されない）
            'paper': 86400 * 30,     # 30日: 学術論文（ほぼ不変）
            'webpage': 86400 * 3,    # 3日: Webページ（頻繁に更新）
            'default': self.cache_ttl  # デフォルト: 設定値
        }

        self.cache_dir = Path(self.config.config_path).parent / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.memory_cache: "OrderedDict[str, Tuple[Any, datetime]]" = OrderedDict()
        self.memory_cache_size_bytes = self.memory_cache_size * 1024 * 1024
        # Per-key TTL overrides for the public get()/set() API (the decorator
        # path uses the global self.cache_ttl instead).
        self._ttl_overrides: Dict[str, int] = {}

        self.executor = ThreadPoolExecutor(max_workers=self.max_concurrent_tasks)
        # Keep strong refs to fire-and-forget disk-write tasks so the event loop
        # doesn't garbage-collect them mid-flight.
        self._background_tasks: set = set()

        self.stats = CacheStats()
        self._cleanup_stop_event = threading.Event()
        self.cleanup_thread = threading.Thread(target=self._cleanup_cache_loop, name="cache-cleanup", daemon=True)
        self.cleanup_thread.start()

        self._warmup_cache()
            
    def cache(self, func: Callable[..., T]) -> Callable[..., Awaitable[T]]:
        """Cache decorator supporting sync and async callables."""

        is_coroutine = asyncio.iscoroutinefunction(func)

        async def async_executor(*args, **kwargs) -> T:
            if is_coroutine:
                return await func(*args, **kwargs)
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(self.executor, lambda: func(*args, **kwargs))

        # NOTE: do NOT wrap this coroutine with functools.lru_cache — it would
        # cache the *coroutine object*, and the second cache hit would await an
        # already-exhausted coroutine (RuntimeError). Caching is handled by the
        # key-based self.memory_cache below.
        async def wrapper(*args, **kwargs) -> T:
            start_time = time.time()
            key = self._generate_cache_key(func.__name__, args, kwargs)

            value = self._get_memory_cache(key)
            if value is not None:
                latency = (time.time() - start_time) * 1000
                self.stats.record_hit(latency)
                return value

            result = await async_executor(*args, **kwargs)
            self._set_memory_cache(key, result)
            task = asyncio.create_task(self._update_disk_cache_async(key, result))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

            latency = (time.time() - start_time) * 1000
            self.stats.record_miss(latency)
            return result

        return wrapper

    def get(self, key: str) -> Optional[Any]:
        """公開 API: キャッシュから値を取得する（期限切れ・不在は None）。

        youtube_integrator / web_integrator など各インテグレーターが
        cache_manager.get(key) を直接呼ぶが、従来このメソッドが存在せず
        AttributeError でキャッシュ参照が必ず失敗していた。per-key TTL に対応。
        """
        entry = self.memory_cache.get(key)
        if entry is None:
            return None
        value, timestamp = entry
        ttl = self._ttl_overrides.get(key, self.cache_ttl)
        if datetime.now() - timestamp >= timedelta(seconds=ttl):
            del self.memory_cache[key]
            self._ttl_overrides.pop(key, None)
            return None
        self.memory_cache.move_to_end(key)
        return value

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """公開 API: 値をキャッシュに格納する（任意の per-key TTL 対応）。

        ディスクキャッシュが有効な場合は永続化も行う。
        """
        self.memory_cache[key] = (value, datetime.now())
        self.memory_cache.move_to_end(key)
        if ttl is not None:
            self._ttl_overrides[key] = ttl
        else:
            self._ttl_overrides.pop(key, None)

        while self.max_cache_items > 0 and len(self.memory_cache) > self.max_cache_items:
            oldest, _ = self.memory_cache.popitem(last=False)
            self._ttl_overrides.pop(oldest, None)

        # ディスク永続化（disk_cache_size<=0 の場合は内部で no-op）
        self._update_disk_cache(key, value)

    def _get_memory_cache(self, key: str) -> Optional[Any]:
        entry = self.memory_cache.get(key)
        if entry is None:
            return None
        value, timestamp = entry
        if datetime.now() - timestamp >= timedelta(seconds=self.cache_ttl):
            del self.memory_cache[key]
            return None
        self.memory_cache.move_to_end(key)
        return value

    def _set_memory_cache(self, key: str, value: Any) -> None:
        self.memory_cache[key] = (value, datetime.now())
        self.memory_cache.move_to_end(key)
        while self.max_cache_items > 0 and len(self.memory_cache) > self.max_cache_items:
            self.memory_cache.popitem(last=False)

    async def _update_disk_cache_async(self, key: str, value: Any) -> None:
        if self.disk_cache_size <= 0:
            return
        if aiofiles is None:
            self._update_disk_cache(key, value)
            return
        try:
            cache_file = self.cache_dir / f"{key}.json"
            async with aiofiles.open(cache_file, "w", encoding="utf-8") as f:
                await f.write(json.dumps({
                    "value": value,
                    "timestamp": datetime.now().isoformat()
                }))
        except Exception as exc:
            logger.error("Failed to update disk cache asynchronously", extra={"error": str(exc), "key": key})

    def _warmup_cache(self) -> None:
        try:
            for cache_file in self.cache_dir.glob("*.json"):
                try:
                    data = json.loads(cache_file.read_text(encoding="utf-8"))
                    timestamp = datetime.fromisoformat(data.get("timestamp", datetime.now().isoformat()))
                    if datetime.now() - timestamp < timedelta(seconds=self.cache_ttl):
                        self.memory_cache[cache_file.stem] = (data.get("value"), timestamp)
                except Exception as exc:
                    logger.warning("Failed to warmup cache", extra={"file": str(cache_file), "error": str(exc)})
        except Exception as exc:
            logger.error("Cache warmup failed", extra={"error": str(exc)})

    def get_cache_stats(self) -> Dict[str, Any]:
        return self.stats.get_stats()

    def clear_cache(self) -> None:
        try:
            self.memory_cache.clear()
            self._ttl_overrides.clear()
            for cache_file in self.cache_dir.glob("*.json"):
                try:
                    cache_file.unlink()
                except Exception as exc:
                    logger.warning("Failed to delete cache file", extra={"file": str(cache_file), "error": str(exc)})
            self.stats = CacheStats()
        except Exception as exc:
            logger.error("Failed to clear cache", extra={"error": str(exc)})
            raise
    
    def _generate_cache_key(self, func_name: str, args: Tuple, kwargs: Dict) -> str:
        """キャッシュキーの生成（プロセス間で安定なハッシュ）。

        組み込み hash() は PYTHONHASHSEED により実行ごとに変わるため、ディスクキャッシュ
        のキー(=ファイル名)が再起動で一致せず warmup/永続化が効かなくなる。安定した
        hashlib.sha256 を用いる。
        """
        try:
            payload = repr((args, tuple(sorted(kwargs.items()))))
        except Exception:
            payload = repr((args, list(kwargs.items())))
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
        return f"{func_name}_{digest}"
    
    def _update_disk_cache(self, key: str, value: Any) -> None:
        if self.disk_cache_size <= 0:
            return
        try:
            cache_file = self.cache_dir / f"{key}.json"
            cache_file.write_text(json.dumps({
                "value": value,
                "timestamp": datetime.now().isoformat()
            }), encoding="utf-8")
        except Exception as exc:
            logger.error("Failed to update disk cache", extra={"error": str(exc), "key": key})

    def _cleanup_cache_loop(self) -> None:
        while not self._cleanup_stop_event.is_set():
            try:
                self._cleanup_memory_cache()
                self._cleanup_disk_cache()
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.error("Cache cleanup error", extra={"error": str(exc)})
            self._cleanup_stop_event.wait(self.cleanup_interval)

    def _cleanup_memory_cache(self) -> None:
        current_size = sum(len(json.dumps(v[0])) for v in self.memory_cache.values())
        while current_size > self.memory_cache_size_bytes and self.memory_cache:
            oldest, _ = self.memory_cache.popitem(last=False)
            self._ttl_overrides.pop(oldest, None)
            current_size = sum(len(json.dumps(v[0])) for v in self.memory_cache.values())

    def _cleanup_disk_cache(self) -> None:
        if self.disk_cache_size <= 0:
            return
        cache_files = sorted(self.cache_dir.glob("*.json"), key=lambda f: f.stat().st_mtime)
        total_size = 0
        for cache_file in cache_files:
            try:
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                timestamp = datetime.fromisoformat(data.get("timestamp", datetime.now().isoformat()))
                if datetime.now() - timestamp > timedelta(seconds=self.cache_ttl):
                    cache_file.unlink()
                    continue
                total_size += cache_file.stat().st_size
                if total_size > self.disk_cache_size * 1024 * 1024:
                    cache_file.unlink()
                    total_size -= cache_file.stat().st_size
            except Exception as exc:
                logger.error("Error during disk cache cleanup", extra={"file": str(cache_file), "error": str(exc)})

    def get_cache_summary(self) -> Dict[str, Any]:
        """メモリとディスクキャッシュの使用状況サマリーを返す"""

        stats = self.get_cache_stats()
        memory_items = len(self.memory_cache)
        memory_size_bytes = sum(len(json.dumps(value[0])) for value in self.memory_cache.values())

        if self.disk_cache_size > 0:
            disk_files = list(self.cache_dir.glob("*.json"))
            disk_size_bytes = sum(file.stat().st_size for file in disk_files)
            disk_usage_ratio = disk_size_bytes / (self.disk_cache_size * 1024 * 1024) if self.disk_cache_size else 0
        else:
            disk_files = []
            disk_size_bytes = 0
            disk_usage_ratio = 0

        return {
            "memory_items": memory_items,
            "memory_size_bytes": memory_size_bytes,
            "memory_usage_ratio": memory_size_bytes / self.memory_cache_size_bytes if self.memory_cache_size_bytes else 0,
            "max_cache_items": self.max_cache_items,
            "memory_item_ratio": memory_items / self.max_cache_items if self.max_cache_items else 0,
            "disk_cache_enabled": self.disk_cache_size > 0,
            "disk_files": len(disk_files),
            "disk_size_bytes": disk_size_bytes,
            "disk_usage_ratio": disk_usage_ratio,
            "stats": stats,
        }

    def get_effective_settings(self) -> Dict[str, Any]:
        """現在適用されているキャッシュ設定値を返す"""

        return {
            "memory_cache_size_mb": self.memory_cache_size,
            "disk_cache_size_mb": self.disk_cache_size,
            "disk_cache_enabled": self.disk_cache_size > 0,
            "cache_ttl_seconds": self.cache_ttl,
            "cleanup_interval_seconds": self.cleanup_interval,
            "max_concurrent_tasks": self.max_concurrent_tasks,
            "max_cache_items": self.max_cache_items,
        }

    def clear_expired_cache(self) -> Dict[str, int]:
        """期限切れのメモリ・ディスクキャッシュを即時に削除"""

        removed_memory = 0
        for key in list(self.memory_cache.keys()):
            entry = self.memory_cache.get(key)
            if entry is None:
                continue
            _, timestamp = entry
            if datetime.now() - timestamp >= timedelta(seconds=self.cache_ttl):
                del self.memory_cache[key]
                removed_memory += 1

        removed_disk = 0
        if self.disk_cache_size > 0:
            for cache_file in list(self.cache_dir.glob("*.json")):
                try:
                    data = json.loads(cache_file.read_text(encoding="utf-8"))
                    timestamp = datetime.fromisoformat(data.get("timestamp", datetime.now().isoformat()))
                    if datetime.now() - timestamp >= timedelta(seconds=self.cache_ttl):
                        cache_file.unlink()
                        removed_disk += 1
                except Exception as exc:
                    logger.error("Failed to remove expired cache file", extra={"file": str(cache_file), "error": str(exc)})

        return {
            "removed_memory_entries": removed_memory,
            "removed_disk_entries": removed_disk,
        }

    def shutdown(self, wait: bool = True, timeout: Optional[float] = None) -> None:
        """バックグラウンドスレッドと実行基盤を安全に停止"""

        self._cleanup_stop_event.set()
        if wait and self.cleanup_thread.is_alive():
            self.cleanup_thread.join(timeout=timeout)
        try:
            self.executor.shutdown(wait=wait)
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.warning("Executor shutdown failed", extra={"error": str(exc)})

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.shutdown(wait=True)

    def __del__(self):  # pragma: no cover - defensive cleanup
        try:
            self.shutdown(wait=False)
        except Exception:
            pass

    def _validated_int(self, key: str, default: int, minimum: int) -> int:
        raw_value = self.settings.get(key, default)
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            logger.warning(
                "Invalid cache manager setting. Falling back to default.",
                extra={"setting": key, "value": raw_value, "default": default},
            )
            return default

        if value < minimum:
            logger.warning(
                "Cache manager setting below minimum. Falling back to default.",
                extra={"setting": key, "value": value, "minimum": minimum, "default": default},
            )
            return default

        return value
