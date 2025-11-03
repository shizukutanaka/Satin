"""
統一的なリトライ戦略 - Tenacity ベース
API リクエスト・スクレイピング・外部サービス呼び出し用
"""

import logging
from typing import Callable, Optional, Type, Tuple, Any
from functools import wraps
from datetime import datetime
import time

try:
    from tenacity import (
        retry,
        stop_after_attempt,
        stop_after_delay,
        wait_exponential,
        wait_fixed,
        wait_random_exponential,
        retry_if_exception_type,
        retry_if_result,
        before_sleep_log,
        after_log,
        RetryError,
        Attempt,
    )
    TENACITY_AVAILABLE = True
except ImportError:
    TENACITY_AVAILABLE = False
    print("Warning: tenacity not installed. Install with: pip install tenacity")


class RetryConfiguration:
    """リトライ設定の統一インターフェース"""

    def __init__(
        self,
        max_attempts: int = 3,
        initial_wait: float = 1.0,
        max_wait: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True
    ):
        """
        Args:
            max_attempts: 最大試行回数
            initial_wait: 初期待機時間（秒）
            max_wait: 最大待機時間（秒）
            exponential_base: 指数バックオフの基数
            jitter: ジッターの有効化
        """
        self.max_attempts = max_attempts
        self.initial_wait = initial_wait
        self.max_wait = max_wait
        self.exponential_base = exponential_base
        self.jitter = jitter

    def get_stop_strategy(self):
        """停止戦略を取得"""
        if not TENACITY_AVAILABLE:
            return None
        return stop_after_attempt(self.max_attempts)

    def get_wait_strategy(self):
        """待機戦略を取得"""
        if not TENACITY_AVAILABLE:
            return None

        if self.jitter:
            return wait_random_exponential(
                multiplier=self.initial_wait,
                max=self.max_wait
            )
        else:
            return wait_exponential(
                multiplier=self.initial_wait,
                max=self.max_wait,
                exp_base=self.exponential_base
            )


# ========================================================================
# 1. YouTube API リトライ戦略
# ========================================================================

class YouTubeRetryConfig(RetryConfiguration):
    """YouTube API 専用リトライ設定"""

    def __init__(self):
        super().__init__(
            max_attempts=4,
            initial_wait=2.0,
            max_wait=120.0,
            exponential_base=2.0,
            jitter=True
        )


def retry_youtube_api(func: Callable) -> Callable:
    """
    YouTube API リトライデコレータ

    対応エラー:
    - 429 Too Many Requests (quota exceeded)
    - 503 Service Unavailable
    - Connection errors
    """
    if not TENACITY_AVAILABLE:
        return func

    config = YouTubeRetryConfig()
    logger = logging.getLogger(f"{func.__module__}.{func.__name__}")

    @retry(
        stop=config.get_stop_strategy(),
        wait=config.get_wait_strategy(),
        retry=retry_if_exception_type((
            ConnectionError,
            TimeoutError,
            Exception
        )),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        after=after_log(logger, logging.INFO),
        reraise=True
    )
    @wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    return wrapper


# ========================================================================
# 2. Web スクレイピング リトライ戦略
# ========================================================================

class WebScrapingRetryConfig(RetryConfiguration):
    """Web スクレイピング専用リトライ設定"""

    def __init__(self):
        super().__init__(
            max_attempts=5,
            initial_wait=1.0,
            max_wait=60.0,
            exponential_base=2.0,
            jitter=True
        )


def should_retry_on_http_error(result: Any) -> bool:
    """HTTP エラーの種類に基づいてリトライを判定"""
    if not result:
        return False

    # HTTPx.Response の場合
    if hasattr(result, 'status_code'):
        status = result.status_code

        # リトライすべき状態コード
        retryable_statuses = {429, 500, 502, 503, 504}
        return status in retryable_statuses

    return False


def retry_web_scraping(func: Callable) -> Callable:
    """
    Web スクレイピング リトライデコレータ

    対応エラー:
    - 429 Too Many Requests
    - 5xx Server errors
    - Connection errors
    - Timeouts
    """
    if not TENACITY_AVAILABLE:
        return func

    config = WebScrapingRetryConfig()
    logger = logging.getLogger(f"{func.__module__}.{func.__name__}")

    @retry(
        stop=config.get_stop_strategy(),
        wait=config.get_wait_strategy(),
        retry=(
            retry_if_exception_type((
                ConnectionError,
                TimeoutError,
                OSError
            )) |
            retry_if_result(should_retry_on_http_error)
        ),
        before_sleep=before_sleep_log(logger, logging.DEBUG),
        after=after_log(logger, logging.DEBUG),
        reraise=True
    )
    @wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    return wrapper


# ========================================================================
# 3. 学術 API リトライ戦略 (arXiv, Scholar等)
# ========================================================================

class AcademicAPIRetryConfig(RetryConfiguration):
    """学術 API 専用リトライ設定"""

    def __init__(self):
        super().__init__(
            max_attempts=3,
            initial_wait=2.0,
            max_wait=180.0,
            exponential_base=2.0,
            jitter=True
        )


def retry_academic_api(func: Callable) -> Callable:
    """
    学術 API (arXiv, Scholar, DOI) リトライデコレータ

    注: arXiv は rate limiting が厳しいため conservative approach
    """
    if not TENACITY_AVAILABLE:
        return func

    config = AcademicAPIRetryConfig()
    logger = logging.getLogger(f"{func.__module__}.{func.__name__}")

    @retry(
        stop=config.get_stop_strategy(),
        wait=config.get_wait_strategy(),
        retry=retry_if_exception_type((
            ConnectionError,
            TimeoutError,
            Exception
        )),
        before_sleep=before_sleep_log(logger, logging.INFO),
        after=after_log(logger, logging.INFO),
        reraise=True
    )
    @wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    return wrapper


# ========================================================================
# 4. キャッシュ・データベース操作リトライ戦略
# ========================================================================

class DatabaseRetryConfig(RetryConfiguration):
    """データベース操作専用リトライ設定"""

    def __init__(self):
        super().__init__(
            max_attempts=3,
            initial_wait=0.1,
            max_wait=10.0,
            exponential_base=2.0,
            jitter=False
        )


def retry_database_operation(func: Callable) -> Callable:
    """
    データベース操作 (キャッシュ、ディスク I/O) リトライデコレータ

    対応エラー:
    - Disk I/O errors
    - Lock timeouts
    - Temporary database unavailability
    """
    if not TENACITY_AVAILABLE:
        return func

    config = DatabaseRetryConfig()
    logger = logging.getLogger(f"{func.__module__}.{func.__name__}")

    @retry(
        stop=config.get_stop_strategy(),
        wait=config.get_wait_strategy(),
        retry=retry_if_exception_type((
            OSError,
            IOError,
            TimeoutError,
            Exception
        )),
        before_sleep=before_sleep_log(logger, logging.DEBUG),
        reraise=True
    )
    @wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    return wrapper


# ========================================================================
# 5. 通用デコレータ - カスタマイズ可能
# ========================================================================

def retry_with_config(
    config: RetryConfiguration,
    retry_exceptions: Tuple[Type[Exception], ...] = (Exception,),
    logger_name: Optional[str] = None
) -> Callable:
    """
    カスタマイズ可能なリトライデコレータ

    Args:
        config: リトライ設定
        retry_exceptions: リトライ対象の例外タプル
        logger_name: ロガー名（デフォルト: 関数のモジュール名）

    Example:
        ```python
        @retry_with_config(
            YouTubeRetryConfig(),
            retry_exceptions=(ConnectionError, TimeoutError)
        )
        def my_api_call():
            ...
        ```
    """
    if not TENACITY_AVAILABLE:
        def no_retry_decorator(func):
            return func
        return no_retry_decorator

    def decorator(func: Callable) -> Callable:
        logger = logging.getLogger(logger_name or func.__module__)

        @retry(
            stop=config.get_stop_strategy(),
            wait=config.get_wait_strategy(),
            retry=retry_if_exception_type(retry_exceptions),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            after=after_log(logger, logging.INFO),
            reraise=True
        )
        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        return wrapper

    return decorator


# ========================================================================
# 6. メトリクス記録デコレータ
# ========================================================================

class RetryMetrics:
    """リトライメトリクスの記録"""

    def __init__(self):
        self.total_calls = 0
        self.total_retries = 0
        self.successful_calls = 0
        self.failed_calls = 0
        self.start_times = {}

    def record_attempt(self, func_name: str, attempt: int, success: bool, error: Optional[str] = None):
        """リトライ試行を記録"""
        self.total_calls += 1
        if attempt > 1:
            self.total_retries += 1

        if success:
            self.successful_calls += 1
        else:
            self.failed_calls += 1


def retry_with_metrics(
    config: RetryConfiguration,
    metrics: Optional[RetryMetrics] = None
) -> Callable:
    """
    メトリクス記録付きリトライデコレータ
    """
    if not TENACITY_AVAILABLE:
        def no_retry_decorator(func):
            return func
        return no_retry_decorator

    metrics = metrics or RetryMetrics()

    def decorator(func: Callable) -> Callable:
        logger = logging.getLogger(func.__module__)

        @retry(
            stop=config.get_stop_strategy(),
            wait=config.get_wait_strategy(),
            retry=retry_if_exception_type(Exception),
            reraise=True
        )
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                metrics.record_attempt(func.__name__, 1, True)
                return result
            except RetryError as e:
                elapsed = time.time() - start_time
                logger.error(
                    f"{func.__name__} failed after "
                    f"{e.last_attempt.attempt_number} attempts in {elapsed:.2f}s: {e.last_exception}"
                )
                metrics.record_attempt(func.__name__, e.last_attempt.attempt_number, False)
                raise

        return wrapper

    return decorator


def get_retry_metrics() -> dict:
    """
    すべてのリトライメトリクスを取得

    Returns:
        メトリクス辞書
    """
    return {
        'total_calls': RetryMetrics.total_calls if TENACITY_AVAILABLE else 0,
        'total_retries': RetryMetrics.total_retries if TENACITY_AVAILABLE else 0,
        'successful': RetryMetrics.successful_calls if TENACITY_AVAILABLE else 0,
        'failed': RetryMetrics.failed_calls if TENACITY_AVAILABLE else 0,
    }


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # デモンストレーション
    @retry_youtube_api
    def demo_youtube_call():
        print("Attempting YouTube API call...")
        return "Success"

    if TENACITY_AVAILABLE:
        result = demo_youtube_call()
        print(f"Result: {result}")
