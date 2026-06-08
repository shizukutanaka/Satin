"""
非同期統合モジュール - High-Performance Async Integration
asyncio + httpx による高速並列処理実装
"""
# Defer annotation evaluation so httpx.* type hints don't require httpx at import
# time (httpx is an optional dependency guarded by the try/except below).
from __future__ import annotations

import asyncio
import time
from typing import Dict, List, Optional, Any, Tuple, Set
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum
import logging

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

try:
    from tenacity import (
        retry,
        stop_after_attempt,
        wait_exponential,
        retry_if_exception_type,
        before_sleep_log,
        after_log,
    )
    TENACITY_AVAILABLE = True
except ImportError:
    TENACITY_AVAILABLE = False

from logging_manager import LoggingManager


class AsyncRetryConfig:
    """非同期リトライ設定"""
    def __init__(
        self,
        max_retries: int = 3,
        initial_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True
    ):
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter

    def calculate_delay(self, attempt: int) -> float:
        """指数バックオフで遅延を計算"""
        delay = min(
            self.initial_delay * (self.exponential_base ** attempt),
            self.max_delay
        )

        if self.jitter:
            import random
            delay *= random.uniform(0.8, 1.2)

        return delay


class TokenBucketRateLimiter:
    """
    トークンバケット方式のレート制限

    複数の API キーを効率的に管理し、各キーの割り当てを独立して制御
    """
    def __init__(
        self,
        rate_per_second: float = 10.0,
        burst_size: int = 20,
        refill_interval: float = 0.1
    ):
        self.rate_per_second = rate_per_second
        self.burst_size = burst_size
        self.refill_interval = refill_interval
        self.tokens = burst_size
        self.last_refill = time.time()
        self.lock = asyncio.Lock()

    async def acquire(self, tokens: int = 1) -> None:
        """トークン取得（利用可能になるまで待機）"""
        while True:
            async with self.lock:
                # トークン補充
                now = time.time()
                elapsed = now - self.last_refill
                refill_tokens = elapsed * self.rate_per_second

                self.tokens = min(
                    self.burst_size,
                    self.tokens + refill_tokens
                )
                self.last_refill = now

                # トークン利用可能か確認
                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return

                # 必要な待機時間を計算（ロック内で算出）
                wait_time = (tokens - self.tokens) / self.rate_per_second

            # ロックを解放してから待機する。ロックを保持したまま sleep すると
            # 他のコルーチンが補充・取得できず、レート制限が完全に直列化してしまう。
            await asyncio.sleep(wait_time)


class AsyncHTTPClient:
    """
    非同期 HTTP クライアント（接続プーリング・リトライ付き）

    httpx による高速リクエスト処理
    接続の再利用で大幅な性能向上を実現
    """
    def __init__(
        self,
        max_connections: int = 100,
        max_keepalive: int = 20,
        timeout: float = 30.0,
        retry_config: Optional[AsyncRetryConfig] = None
    ):
        self.logger = LoggingManager.get_logger("async_http_client")
        self.max_connections = max_connections
        self.max_keepalive = max_keepalive
        self.timeout = timeout
        self.retry_config = retry_config or AsyncRetryConfig()
        self.client: Optional[httpx.AsyncClient] = None
        self.rate_limiter = TokenBucketRateLimiter(rate_per_second=10.0)

    async def __aenter__(self):
        """非同期コンテキストマネージャの開始"""
        limits = httpx.Limits(
            max_connections=self.max_connections,
            max_keepalive_connections=self.max_keepalive
        )
        self.client = httpx.AsyncClient(
            limits=limits,
            timeout=self.timeout
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """非同期コンテキストマネージャの終了"""
        if self.client:
            await self.client.aclose()

    async def get(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        **kwargs
    ) -> Optional[httpx.Response]:
        """
        GET リクエスト（自動リトライ・レート制限付き）
        """
        if not self.client:
            raise RuntimeError("Client not initialized. Use async with statement.")

        await self.rate_limiter.acquire()

        for attempt in range(self.retry_config.max_retries):
            try:
                self.logger.debug(f"GET {url} (attempt {attempt + 1})")
                response = await self.client.get(url, headers=headers, **kwargs)
                response.raise_for_status()
                return response

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:  # Too Many Requests
                    # Retry-After ヘッダを確認
                    retry_after = e.response.headers.get('retry-after')
                    if retry_after:
                        try:
                            wait_seconds = int(retry_after)
                        except ValueError:
                            wait_seconds = int(self.retry_config.calculate_delay(attempt))
                    else:
                        wait_seconds = int(self.retry_config.calculate_delay(attempt))

                    self.logger.warning(
                        f"Rate limited on {url}. "
                        f"Waiting {wait_seconds}s before retry."
                    )
                    await asyncio.sleep(wait_seconds)
                    continue

                elif e.response.status_code >= 500:
                    # サーバーエラーはリトライ
                    if attempt < self.retry_config.max_retries - 1:
                        delay = self.retry_config.calculate_delay(attempt)
                        self.logger.warning(
                            f"Server error {e.response.status_code} on {url}. "
                            f"Retrying in {delay:.1f}s..."
                        )
                        await asyncio.sleep(delay)
                        continue
                    else:
                        self.logger.error(f"Max retries exceeded for {url}")
                        return None

                else:
                    # クライアントエラー（リトライなし）
                    self.logger.error(f"Client error {e.response.status_code}: {url}")
                    return None

            except httpx.RequestError as e:
                # ネットワークエラー
                if attempt < self.retry_config.max_retries - 1:
                    delay = self.retry_config.calculate_delay(attempt)
                    self.logger.warning(
                        f"Request error: {e}. Retrying in {delay:.1f}s..."
                    )
                    await asyncio.sleep(delay)
                    continue
                else:
                    self.logger.error(f"Request failed after {self.retry_config.max_retries} attempts: {url}")
                    return None

        return None

    async def batch_get(
        self,
        urls: List[str],
        max_concurrent: int = 10,
        headers: Optional[Dict[str, str]] = None
    ) -> List[Tuple[str, Optional[httpx.Response]]]:
        """
        複数 URL への並列 GET リクエスト

        Args:
            urls: リクエスト URL リスト
            max_concurrent: 最大並行数
            headers: リクエストヘッダ

        Returns:
            (URL, Response) のタプルリスト
        """
        semaphore = asyncio.Semaphore(max_concurrent)

        async def bounded_get(url: str):
            async with semaphore:
                response = await self.get(url, headers=headers)
                return url, response

        tasks = [bounded_get(url) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        return results


class AsyncAggregationService:
    """
    非同期コンテンツ集約サービス

    複数の API を効率的に並列処理
    """
    def __init__(self):
        self.logger = LoggingManager.get_logger("async_aggregation")
        self.http_client: Optional[AsyncHTTPClient] = None

    async def __aenter__(self):
        """非同期コンテキストマネージャの開始"""
        self.http_client = AsyncHTTPClient()
        await self.http_client.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """非同期コンテキストマネージャの終了"""
        if self.http_client:
            await self.http_client.__aexit__(exc_type, exc_val, exc_tb)

    async def search_parallel(
        self,
        query: str,
        sources: List[str],
        max_results: int = 10
    ) -> Dict[str, Any]:
        """
        複数ソースを並列検索

        Args:
            query: 検索クエリ
            sources: 検索対象ソース (youtube, arxiv, scholar, web)
            max_results: ソースあたりの最大結果数

        Returns:
            集約結果辞書
        """
        start_time = time.time()
        results = {
            'query': query,
            'sources': sources,
            'results': {},
            'timing': {},
            'errors': {}
        }

        # 各ソースを並列実行
        tasks = []
        source_map = {}

        if 'youtube' in sources:
            task = self._search_youtube(query, max_results)
            tasks.append(task)
            source_map[len(tasks) - 1] = 'youtube'

        if 'arxiv' in sources:
            task = self._search_arxiv(query, max_results)
            tasks.append(task)
            source_map[len(tasks) - 1] = 'arxiv'

        if 'scholar' in sources:
            task = self._search_scholar(query, max_results)
            tasks.append(task)
            source_map[len(tasks) - 1] = 'scholar'

        # 結果を集約
        task_results = await asyncio.gather(*tasks, return_exceptions=True)

        for idx, (source_name, result) in enumerate(zip(
            [source_map[i] for i in range(len(task_results))],
            task_results
        )):
            if isinstance(result, Exception):
                results['errors'][source_name] = str(result)
                self.logger.error(f"Error in {source_name}: {result}")
            else:
                results['results'][source_name] = result

        results['total_time'] = time.time() - start_time
        return results

    async def _search_youtube(self, query: str, max_results: int) -> Dict[str, Any]:
        """YouTube を非同期検索"""
        start = time.time()

        # プレースホルダー実装（実装時にYouTubeAPIラッパー使用）
        await asyncio.sleep(0.5)  # シミュレーション

        return {
            'count': 0,
            'items': [],
            'time': time.time() - start
        }

    async def _search_arxiv(self, query: str, max_results: int) -> Dict[str, Any]:
        """arXiv を非同期検索"""
        start = time.time()

        # プレースホルダー実装
        await asyncio.sleep(0.3)  # シミュレーション

        return {
            'count': 0,
            'items': [],
            'time': time.time() - start
        }

    async def _search_scholar(self, query: str, max_results: int) -> Dict[str, Any]:
        """Google Scholar を非同期検索"""
        start = time.time()

        # プレースホルダー実装
        await asyncio.sleep(1.0)  # シミュレーション

        return {
            'count': 0,
            'items': [],
            'time': time.time() - start
        }


async def demonstrate_async_performance():
    """非同期処理のパフォーマンス実演"""
    logger = LoggingManager.get_logger("async_demo")

    # 非同期集約サービスの実演
    async with AsyncAggregationService() as agg:
        logger.info("Starting parallel search demonstration...")

        start = time.time()
        result = await agg.search_parallel(
            query="machine learning",
            sources=['youtube', 'arxiv', 'scholar'],
            max_results=10
        )
        elapsed = time.time() - start

        logger.info(f"Parallel search completed in {elapsed:.2f}s")
        logger.info(f"Results: {result}")


if __name__ == '__main__':
    # ロギング初期化
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # デモンストレーション実行
    if HTTPX_AVAILABLE:
        asyncio.run(demonstrate_async_performance())
    else:
        print("httpx is required. Install with: pip install httpx")
