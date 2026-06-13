"""
Circuit Breaker + 分散キャッシング統合
障害検知・自動フェイルオーバー・Bulkhead Isolation
"""

import time
import asyncio
import logging
from typing import Any, Optional, Callable, Dict, List
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timedelta
from collections import deque
import json

logger = logging.getLogger(__name__)


class CircuitBreakerOpenError(Exception):
    """サーキットブレーカーが OPEN（遮断中）のため呼び出しを拒否したことを示す。

    生の Exception では呼び出し側が「ブレーカー遮断（=後でリトライ）」と
    「下流の本当の障害」を区別できず、メッセージ文字列を見るしかなかった。
    専用型にすることで `except CircuitBreakerOpenError` で個別ハンドリングできる。
    Exception のサブクラスなので既存の `except Exception` は引き続き捕捉する。
    """


# ========================================================================
# 1. Circuit Breaker 状態管理
# ========================================================================

class CircuitState(Enum):
    """Circuit Breaker の状態"""
    CLOSED = "closed"          # 正常 - リクエスト通す
    OPEN = "open"              # 故障 - リクエスト遮断
    HALF_OPEN = "half_open"    # 回復中 - テストリクエスト許可


@dataclass
class CircuitBreakerConfig:
    """Circuit Breaker の設定"""
    failure_threshold: int = 5           # 故障と判定するまでの失敗数
    success_threshold: int = 2           # 回復と判定するまでの成功数
    timeout_seconds: float = 60.0        # OPEN から HALF_OPEN への遷移待機時間
    metrics_window: int = 100            # メトリクス収集のウィンドウサイズ
    slow_call_threshold_ms: float = 1000 # スロー呼び出しの閾値(ms)


@dataclass
class CircuitBreakerMetrics:
    """Circuit Breaker のメトリクス"""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    slow_calls: int = 0
    rejected_calls: int = 0  # OPEN 状態で遮断されたリクエスト
    last_failure_time: Optional[datetime] = None
    last_success_time: Optional[datetime] = None
    state_change_time: Optional[datetime] = None

    def get_failure_rate(self) -> float:
        """失敗率を計算（%）"""
        total = self.total_calls
        if total == 0:
            return 0.0
        return (self.failed_calls / total) * 100

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            'total_calls': self.total_calls,
            'successful_calls': self.successful_calls,
            'failed_calls': self.failed_calls,
            'slow_calls': self.slow_calls,
            'rejected_calls': self.rejected_calls,
            'failure_rate': self.get_failure_rate(),
            'last_failure_time': self.last_failure_time.isoformat() if self.last_failure_time else None,
            'last_success_time': self.last_success_time.isoformat() if self.last_success_time else None,
            'state_change_time': self.state_change_time.isoformat() if self.state_change_time else None
        }


class CircuitBreaker:
    """
    Circuit Breaker パターンの実装

    障害の連鎖を防止し、自動復旧を実現
    """

    def __init__(self, name: str, config: Optional[CircuitBreakerConfig] = None):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self.state = CircuitState.CLOSED
        self.metrics = CircuitBreakerMetrics()
        self.failure_count = 0
        self.success_count = 0
        self._half_open_calls = 0
        self.last_failure_time: Optional[datetime] = None
        self.call_history: deque = deque(maxlen=self.config.metrics_window)
        # Guards state transitions / counters. Held only around bookkeeping,
        # never around the wrapped call, so CLOSED-state calls stay concurrent.
        self._lock = asyncio.Lock()

    async def call(
        self,
        func: Callable,
        *args,
        fallback: Optional[Callable] = None,
        **kwargs
    ) -> Any:
        """
        Circuit Breaker 経由で関数を実行

        Args:
            func: 実行する関数
            fallback: 回復不可時のフォールバック関数
            *args, **kwargs: func に渡す引数

        Returns:
            func の実行結果 or フォールバック値
        """
        # 状態チェック・遷移(状態更新はロックで保護。func 実行はロック外)
        rejected = False
        async with self._lock:
            if self.state == CircuitState.OPEN:
                # 回復待機時間が経過したか確認
                if self._should_attempt_reset():
                    self.state = CircuitState.HALF_OPEN
                    self.success_count = 0
                    self.failure_count = 0      # 回復試行をクリーンに開始
                    self._half_open_calls = 0
                    self.metrics.state_change_time = datetime.now()
                    logger.info(f"Circuit Breaker '{self.name}' -> HALF_OPEN")
                else:
                    rejected = True

            # HALF_OPEN 中はプローブ数を success_threshold までに制限
            if not rejected and self.state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.config.success_threshold:
                    rejected = True
                else:
                    self._half_open_calls += 1

        if rejected:
            # OPEN 状態のまま / HALF_OPEN 上限 - リクエスト遮断
            self.metrics.rejected_calls += 1
            logger.warning(f"Circuit Breaker '{self.name}' is OPEN - rejecting call")

            if fallback:
                return await self._call_function(fallback)
            else:
                raise CircuitBreakerOpenError(f"Circuit Breaker '{self.name}' is OPEN")

        # 関数を実行
        start_time = time.time()
        try:
            result = await self._call_function(func, *args, **kwargs)

            # 実行成功
            elapsed_ms = (time.time() - start_time) * 1000

            self.metrics.total_calls += 1
            self.metrics.successful_calls += 1
            self.metrics.last_success_time = datetime.now()

            # スロー呼び出しをチェック
            if elapsed_ms > self.config.slow_call_threshold_ms:
                self.metrics.slow_calls += 1
                logger.warning(
                    f"Slow call detected in '{self.name}': {elapsed_ms:.1f}ms "
                    f"(threshold: {self.config.slow_call_threshold_ms}ms)"
                )

            # 状態遷移・カウンタはロックで保護
            async with self._lock:
                if self.state == CircuitState.HALF_OPEN:
                    self.success_count += 1
                    if self.success_count >= self.config.success_threshold:
                        self.state = CircuitState.CLOSED
                        self.failure_count = 0
                        self.success_count = 0
                        self._half_open_calls = 0
                        self.metrics.state_change_time = datetime.now()
                        logger.info(f"Circuit Breaker '{self.name}' -> CLOSED (recovered)")

                # CLOSED 状態では失敗カウントをリセット
                elif self.state == CircuitState.CLOSED:
                    self.failure_count = 0

            return result

        except Exception as e:
            # 実行失敗
            self.metrics.total_calls += 1
            self.metrics.failed_calls += 1
            self.metrics.last_failure_time = datetime.now()
            self.last_failure_time = datetime.now()

            logger.error(f"Call failed in Circuit Breaker '{self.name}': {e}")

            async with self._lock:
                self.failure_count += 1

                # HALF_OPEN 状態では即座に OPEN に(成功カウントもリセット)
                if self.state == CircuitState.HALF_OPEN:
                    self.state = CircuitState.OPEN
                    self.success_count = 0
                    self._half_open_calls = 0
                    self.metrics.state_change_time = datetime.now()
                    logger.error(f"Circuit Breaker '{self.name}' -> OPEN (recovery failed)")

                # CLOSED 状態で閾値到達 → OPEN に
                elif self.state == CircuitState.CLOSED:
                    if self.failure_count >= self.config.failure_threshold:
                        self.state = CircuitState.OPEN
                        self.metrics.state_change_time = datetime.now()
                        logger.error(
                            f"Circuit Breaker '{self.name}' -> OPEN "
                            f"(failures: {self.failure_count}/{self.config.failure_threshold})"
                        )

            # フォールバック実行
            if fallback:
                logger.info(f"Executing fallback for '{self.name}'")
                try:
                    return await self._call_function(fallback)
                except Exception as fb_error:
                    logger.error(f"Fallback also failed: {fb_error}")
                    raise

            raise

    async def _call_function(self, func: Callable, *args, **kwargs) -> Any:
        """非同期/同期関数を統一的に呼び出し"""
        if asyncio.iscoroutinefunction(func):
            return await func(*args, **kwargs)
        else:
            return func(*args, **kwargs)

    def _should_attempt_reset(self) -> bool:
        """回復テストを試みるべきか判定"""
        if not self.last_failure_time:
            return False

        elapsed = (datetime.now() - self.last_failure_time).total_seconds()
        return elapsed >= self.config.timeout_seconds

    def get_state(self) -> str:
        """現在の状態を取得"""
        return self.state.value

    def get_metrics(self) -> Dict[str, Any]:
        """メトリクスを取得"""
        return self.metrics.to_dict()


# ========================================================================
# 2. Bulkhead Isolation (リソース隔離)
# ========================================================================

class BulkheadPolicy:
    """Bulkhead Isolation ポリシー"""

    def __init__(
        self,
        max_concurrent_calls: int = 10,
        max_wait_duration_ms: float = 5000.0
    ):
        self.max_concurrent_calls = max_concurrent_calls
        self.max_wait_duration_ms = max_wait_duration_ms
        self.semaphore = asyncio.Semaphore(max_concurrent_calls)
        self.active_calls = 0
        self.rejected_calls = 0

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Bulkhead 制御下で関数を実行
        """
        try:
            # セマフォで並行数を制限
            async with asyncio.timeout(self.max_wait_duration_ms / 1000.0):
                async with self.semaphore:
                    self.active_calls += 1
                    try:
                        if asyncio.iscoroutinefunction(func):
                            return await func(*args, **kwargs)
                        else:
                            return func(*args, **kwargs)
                    finally:
                        self.active_calls -= 1

        except asyncio.TimeoutError:
            self.rejected_calls += 1
            logger.error("Bulkhead wait timeout - request rejected")
            raise

    def get_status(self) -> Dict[str, Any]:
        """Bulkhead 状態を取得"""
        return {
            'active_calls': self.active_calls,
            'max_concurrent_calls': self.max_concurrent_calls,
            'rejected_calls': self.rejected_calls,
            'utilization': (self.active_calls / self.max_concurrent_calls) * 100
        }


# ========================================================================
# 3. 分散キャッシング（Redis/Memcached 対応）
# ========================================================================

class DistributedCacheConfig:
    """分散キャッシング設定"""

    def __init__(
        self,
        backend: str = "memory",  # memory, redis, memcached
        ttl_seconds: int = 3600,
        invalidation_strategy: str = "ttl"  # ttl, event-driven, manual
    ):
        self.backend = backend
        self.ttl_seconds = ttl_seconds
        self.invalidation_strategy = invalidation_strategy


class CacheInvalidationStrategy(Enum):
    """キャッシュ無効化戦略"""
    TTL = "ttl"                    # 時間ベース
    EVENT_DRIVEN = "event-driven"  # イベント駆動（Pub/Sub）
    MANUAL = "manual"              # 手動無効化
    LRU = "lru"                    # LRU ポリシー
    LFU = "lfu"                    # LFU ポリシー


class DistributedCache:
    """
    分散キャッシング実装

    複数バックエンドに対応（memory/Redis/Memcached）
    キャッシュ無効化戦略を選択可能
    """

    def __init__(self, config: DistributedCacheConfig):
        self.config = config
        self.memory_cache: Dict[str, tuple] = {}  # (value, expiry_time)
        self.tag_map: Dict[str, set] = {}  # タグベースの無効化用
        self.access_log: deque = deque(maxlen=10000)

    async def get(self, key: str) -> Optional[Any]:
        """キャッシュから値を取得"""
        if key not in self.memory_cache:
            return None

        value, expiry_time = self.memory_cache[key]

        # TTL チェック
        if datetime.now() > expiry_time:
            del self.memory_cache[key]
            return None

        # アクセスログに記録
        self.access_log.append({
            'key': key,
            'operation': 'get',
            'timestamp': datetime.now(),
            'hit': True
        })

        return value

    async def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: Optional[int] = None,
        tags: Optional[List[str]] = None
    ) -> None:
        """キャッシュに値を設定"""
        ttl = ttl_seconds or self.config.ttl_seconds
        expiry_time = datetime.now() + timedelta(seconds=ttl)

        self.memory_cache[key] = (value, expiry_time)

        # タグを記録（グループベース無効化用）
        if tags:
            for tag in tags:
                if tag not in self.tag_map:
                    self.tag_map[tag] = set()
                self.tag_map[tag].add(key)

        logger.debug(f"Cache SET: {key} (TTL: {ttl}s, tags: {tags})")

    async def invalidate_by_tag(self, tag: str) -> int:
        """タグに基づいてキャッシュを無効化"""
        if tag not in self.tag_map:
            return 0

        keys_to_delete = self.tag_map[tag]
        for key in keys_to_delete:
            self.memory_cache.pop(key, None)

        count = len(keys_to_delete)
        del self.tag_map[tag]

        logger.info(f"Invalidated {count} cache entries for tag: {tag}")
        return count

    async def invalidate_by_pattern(self, pattern: str) -> int:
        """パターンに基づいてキャッシュを無効化"""
        import re
        regex = re.compile(pattern)
        keys_to_delete = [k for k in self.memory_cache if regex.match(k)]

        for key in keys_to_delete:
            self.memory_cache.pop(key, None)

        logger.info(f"Invalidated {len(keys_to_delete)} cache entries for pattern: {pattern}")
        return len(keys_to_delete)

    def get_stats(self) -> Dict[str, Any]:
        """キャッシュ統計を取得"""
        total_accesses = len(self.access_log)
        hits = sum(1 for log in self.access_log if log.get('hit', False))
        hit_rate = (hits / total_accesses * 100) if total_accesses > 0 else 0

        return {
            'cached_items': len(self.memory_cache),
            'tagged_groups': len(self.tag_map),
            'total_accesses': total_accesses,
            'cache_hit_rate': hit_rate,
            'backend': self.config.backend,
            'invalidation_strategy': self.config.invalidation_strategy
        }


# ========================================================================
# 4. Resilience パターン統合
# ========================================================================

class ResilientService:
    """
    Circuit Breaker + Bulkhead + Cache を統合した
    高信頼性サービス実装
    """

    def __init__(
        self,
        name: str,
        circuit_breaker_config: Optional[CircuitBreakerConfig] = None,
        bulkhead_config: Optional[Dict[str, int]] = None,
        cache_config: Optional[DistributedCacheConfig] = None
    ):
        self.name = name
        self.circuit_breaker = CircuitBreaker(name, circuit_breaker_config)
        self.bulkhead = BulkheadPolicy(
            max_concurrent_calls=bulkhead_config.get('max_concurrent_calls', 10)
            if bulkhead_config else 10
        )
        self.cache = DistributedCache(cache_config or DistributedCacheConfig())

    async def call(
        self,
        func: Callable,
        cache_key: Optional[str] = None,
        fallback: Optional[Callable] = None,
        *args,
        **kwargs
    ) -> Any:
        """
        複合的な保護機構を備えた関数実行

        1. キャッシュ確認
        2. Bulkhead 制限
        3. Circuit Breaker 保護
        4. フォールバック実行
        """

        # ステップ 1: キャッシュ確認
        if cache_key:
            cached_value = await self.cache.get(cache_key)
            if cached_value is not None:
                logger.debug(f"Cache HIT for {cache_key}")
                return cached_value

        # ステップ 2 & 3: Bulkhead + Circuit Breaker
        async def protected_call():
            return await self.bulkhead.call(
                lambda: self.circuit_breaker.call(
                    func,
                    *args,
                    fallback=fallback,
                    **kwargs
                )
            )

        result = await protected_call()

        # キャッシュに保存
        if cache_key:
            await self.cache.set(cache_key, result)

        return result

    def get_status(self) -> Dict[str, Any]:
        """サービスのステータスを取得"""
        return {
            'name': self.name,
            'circuit_breaker': {
                'state': self.circuit_breaker.get_state(),
                'metrics': self.circuit_breaker.get_metrics()
            },
            'bulkhead': self.bulkhead.get_status(),
            'cache': self.cache.get_stats()
        }


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # デモンストレーション
    async def demo():
        # Circuit Breaker デモ
        cb = CircuitBreaker("demo", CircuitBreakerConfig(failure_threshold=2))

        async def failing_func():
            raise Exception("Service unavailable")

        async def fallback_func():
            return "Fallback value"

        for i in range(5):
            try:
                result = await cb.call(failing_func, fallback=fallback_func)
                print(f"Call {i+1}: {result}")
            except Exception as e:
                print(f"Call {i+1} failed: {e}")

            print(f"State: {cb.get_state()}, Metrics: {cb.get_metrics()}")

    asyncio.run(demo())
