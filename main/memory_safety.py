"""
メモリ安全性・リソース管理モジュール
Weak references, 循環参照回避, garbage collection最適化
"""

import logging
import gc
import weakref
from typing import Any, Optional, Dict, List, Tuple, Callable
from weakref import WeakValueDictionary, WeakKeyDictionary, ref
from dataclasses import dataclass
from datetime import datetime, timedelta
import sys
from functools import wraps

logger = logging.getLogger(__name__)


# ========================================================================
# 1. キャッシュ専用のメモリセーフ実装
# ========================================================================

class WeakReferencedCache:
    """
    Weak reference を使用したセーフキャッシュ

    キャッシュ内のオブジェクトがガベージコレクションの対象外にならないようにする
    循環参照を防止し、メモリリーク防止
    """

    def __init__(self, max_size: int = 1000, ttl_seconds: int = 3600):
        """
        Args:
            max_size: 最大キャッシュサイズ
            ttl_seconds: キャッシュの有効期間（秒）
        """
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds

        # Weak reference をキーとするマップ
        self._cache: WeakValueDictionary = WeakValueDictionary()

        # TTL管理用（強参照で保持）
        self._ttl_map: Dict[str, datetime] = {}

        # アクセス統計
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Optional[Any]:
        """キャッシュから値を取得"""
        # TTL チェック
        if key in self._ttl_map:
            if datetime.now() > self._ttl_map[key]:
                # 期限切れ
                self._cache.pop(key, None)
                self._ttl_map.pop(key, None)
                self.misses += 1
                return None

        # キャッシュから取得（weak reference なので参照がなければ None）
        value = self._cache.get(key)
        if value is None:
            self.misses += 1
        else:
            self.hits += 1

        return value

    def set(self, key: str, value: Any) -> None:
        """キャッシュに値を設定"""
        if len(self._cache) >= self.max_size:
            # LRU 削除（最も古い TTL を削除）
            if self._ttl_map:
                oldest_key = min(self._ttl_map, key=self._ttl_map.get)
                self._cache.pop(oldest_key, None)
                self._ttl_map.pop(oldest_key, None)

        self._cache[key] = value
        self._ttl_map[key] = datetime.now() + timedelta(seconds=self.ttl_seconds)

    def get_stats(self) -> Dict[str, Any]:
        """キャッシュ統計を取得"""
        total = self.hits + self.misses
        return {
            'hits': self.hits,
            'misses': self.misses,
            'hit_rate': (self.hits / total * 100) if total > 0 else 0,
            'size': len(self._cache),
            'max_size': self.max_size
        }

    def clear(self) -> None:
        """キャッシュをクリア"""
        self._cache.clear()
        self._ttl_map.clear()
        self.hits = 0
        self.misses = 0


# ========================================================================
# 2. リソース管理コンテキストマネージャ
# ========================================================================

class ResourceManager:
    """
    リソース生成・破棄の安全な管理

    複数のリソースを管理し、例外発生時も必ずクリーンアップ
    """

    def __init__(self):
        self._resources: List[Tuple[str, Any, Callable]] = []
        self._cleanup_order = []

    def register(self, name: str, resource: Any, cleanup_func: Callable[[Any], None]) -> Any:
        """
        リソースを登録

        Args:
            name: リソース名
            resource: リソースオブジェクト
            cleanup_func: クリーンアップ関数

        Returns:
            リソースオブジェクト
        """
        self._resources.append((name, resource, cleanup_func))
        self._cleanup_order.insert(0, (name, resource, cleanup_func))  # LIFO order
        return resource

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """コンテキスト終了時にすべてのリソースをクリーンアップ"""
        for name, resource, cleanup_func in self._cleanup_order:
            try:
                cleanup_func(resource)
                logger.debug(f"Cleaned up resource: {name}")
            except Exception as e:
                logger.error(f"Error cleaning up {name}: {e}")

        self._resources.clear()
        self._cleanup_order.clear()

    def __repr__(self):
        return f"ResourceManager({len(self._resources)} resources)"


# ========================================================================
# 3. ガベージコレクション最適化
# ========================================================================

class GarbageCollectionOptimizer:
    """
    ガベージコレクションを監視・最適化

    大規模バッチ処理時の GC オーバーヘッド削減
    """

    def __init__(self):
        self.logger = logger
        self.initial_stats = gc.get_stats()

    def disable_during_batch(self):
        """
        大規模バッチ処理中は GC を無効化

        処理後に明示的に gc.collect() を実行
        """
        gc.disable()
        self.logger.debug("GC disabled for batch processing")

    def enable_and_collect(self):
        """GC を再度有効化し、明示的に実行"""
        gc.collect()
        gc.enable()
        self.logger.debug("GC enabled and manual collection completed")

    def get_memory_info(self) -> Dict[str, Any]:
        """メモリ情報を取得"""
        import os
        try:
            import psutil
            process = psutil.Process(os.getpid())
            mem_info = process.memory_info()
            return {
                'rss_mb': mem_info.rss / 1024 / 1024,
                'vms_mb': mem_info.vms / 1024 / 1024,
                'percent': process.memory_percent()
            }
        except ImportError:
            # psutil がない場合はシンプル情報
            return {
                'gc_objects': len(gc.get_objects()),
                'gc_stats': gc.get_stats()
            }

    @staticmethod
    def find_circular_references() -> List[Tuple[Any, Any]]:
        """循環参照を検出"""
        gc.collect()
        unreachable = gc.garbage
        circular_refs = []

        for obj in unreachable:
            if hasattr(obj, '__dict__'):
                circular_refs.append((type(obj).__name__, obj))

        return circular_refs


# ========================================================================
# 4. デコレータ - リソースライフサイクル管理
# ========================================================================

def manage_resources(cleanup_handlers: Dict[str, Callable]) -> Callable:
    """
    デコレータ: リソースライフサイクル管理

    Example:
        ```python
        @manage_resources({
            'connection': lambda conn: conn.close(),
            'file': lambda f: f.close()
        })
        def process_data(connection, file):
            # 処理
            pass
        ```
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            manager = ResourceManager()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                manager.__exit__(None, None, None)
        return wrapper
    return decorator


def prevent_circular_refs(func: Callable) -> Callable:
    """
    デコレータ: 循環参照防止

    関数実行後に gc.collect() を実行して循環参照を除去
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        finally:
            # 明示的にガベージコレクション実行
            gc.collect(generation=0)  # 第0世代のみ（高速）
    return wrapper


# ========================================================================
# 5. バッチ処理のメモリ安全な実装
# ========================================================================

class MemorySafeBatchProcessor:
    """
    バッチ処理中のメモリ使用を厳密に管理

    大規模データセット処理時のメモリオーバーフロー防止
    """

    def __init__(self, batch_size: int = 100, gc_threshold: int = 1000):
        """
        Args:
            batch_size: バッチのサイズ
            gc_threshold: GC実行の対象数閾値
        """
        self.batch_size = batch_size
        self.gc_threshold = gc_threshold
        self.processor_count = 0
        self.optimizer = GarbageCollectionOptimizer()

    def process_items(
        self,
        items: List[Any],
        process_func: Callable[[Any], Any],
        cleanup_func: Optional[Callable[[Any], None]] = None
    ) -> List[Any]:
        """
        メモリセーフなバッチ処理

        Args:
            items: 処理対象アイテムリスト
            process_func: 各アイテムの処理関数
            cleanup_func: 処理後のクリーンアップ関数

        Returns:
            処理結果リスト
        """
        results = []
        self.optimizer.disable_during_batch()

        try:
            for i, item in enumerate(items):
                # アイテム処理
                result = process_func(item)
                results.append(result)

                # クリーンアップ
                if cleanup_func:
                    cleanup_func(item)

                # 定期的な GC実行
                if (i + 1) % self.gc_threshold == 0:
                    gc.collect(generation=0)
                    self.processor_count += 1
                    logger.debug(
                        f"GC triggered after {i + 1} items. "
                        f"Current memory: {self.optimizer.get_memory_info()}"
                    )

        finally:
            self.optimizer.enable_and_collect()

        return results


# ========================================================================
# 6. メモリ監視・警告システム
# ========================================================================

@dataclass
class MemoryWarning:
    """メモリ警告情報"""
    level: str  # 'INFO', 'WARNING', 'CRITICAL'
    message: str
    memory_usage: Dict[str, Any]
    timestamp: datetime


class MemoryWatcher:
    """
    メモリ使用状況を監視し、閾値超過時に警告
    """

    def __init__(self, warning_threshold: float = 0.8, critical_threshold: float = 0.95):
        """
        Args:
            warning_threshold: 警告対象メモリ率（80%）
            critical_threshold: 致命的警告率（95%）
        """
        self.warning_threshold = warning_threshold
        self.critical_threshold = critical_threshold
        self.warnings: List[MemoryWarning] = []

    def check_memory(self) -> Optional[MemoryWarning]:
        """メモリ使用状況をチェック"""
        optimizer = GarbageCollectionOptimizer()
        memory_info = optimizer.get_memory_info()

        if 'percent' in memory_info:
            percent = memory_info['percent']

            if percent >= self.critical_threshold:
                warning = MemoryWarning(
                    level='CRITICAL',
                    message=f"Memory usage critical: {percent:.1f}%",
                    memory_usage=memory_info,
                    timestamp=datetime.now()
                )
                self.warnings.append(warning)
                logger.critical(warning.message)
                return warning

            elif percent >= self.warning_threshold:
                warning = MemoryWarning(
                    level='WARNING',
                    message=f"Memory usage warning: {percent:.1f}%",
                    memory_usage=memory_info,
                    timestamp=datetime.now()
                )
                self.warnings.append(warning)
                logger.warning(warning.message)
                return warning

        return None

    def get_warnings(self) -> List[MemoryWarning]:
        """すべての警告を取得"""
        return self.warnings


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # デモンストレーション
    print("=== WeakReferencedCache デモ ===")
    cache = WeakReferencedCache(max_size=10, ttl_seconds=60)

    cache.set('key1', 'value1')
    print(f"Get key1: {cache.get('key1')}")
    print(f"Stats: {cache.get_stats()}")

    print("\n=== MemorySafeBatchProcessor デモ ===")
    processor = MemorySafeBatchProcessor(batch_size=100, gc_threshold=50)

    def example_process(item):
        return item * 2

    items = list(range(200))
    results = processor.process_items(items, example_process)
    print(f"Processed {len(results)} items")

    print("\n=== MemoryWatcher デモ ===")
    watcher = MemoryWatcher(warning_threshold=0.8, critical_threshold=0.95)
    warning = watcher.check_memory()
    if warning:
        print(f"Warning: {warning.message}")
