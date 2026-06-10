"""
高度なエラーハンドリング・例外処理システム
カスタム例外, エラー回復戦略, エラーコンテキスト管理
"""

import sys
import logging
import traceback
from typing import Type, Callable, Optional, List, Dict, Any, Union
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from functools import wraps
import json

logger = logging.getLogger(__name__)


# ========================================================================
# 1. カスタム例外の階層
# ========================================================================

class SatinException(Exception):
    """Satin プロジェクトのベース例外"""

    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None
    ):
        self.message = message
        self.error_code = error_code or self.__class__.__name__
        self.context = context or {}
        self.cause = cause
        self.timestamp = datetime.now()
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換（ロギング・API レスポンス用）"""
        return {
            'error_type': self.__class__.__name__,
            'error_code': self.error_code,
            'message': self.message,
            'context': self.context,
            'timestamp': self.timestamp.isoformat(),
            'cause': str(self.cause) if self.cause else None
        }

    def to_json(self) -> str:
        """JSON 形式に変換"""
        return json.dumps(self.to_dict(), indent=2, default=str)


class APIIntegrationError(SatinException):
    """API 統合エラーのベース"""
    pass


class YouTubeAPIError(APIIntegrationError):
    """YouTube API エラー"""

    def __init__(
        self,
        message: str,
        api_error_code: Optional[int] = None,
        quota_exceeded: bool = False,
        retry_after: Optional[float] = None,
        **kwargs
    ):
        super().__init__(message, **kwargs)
        self.api_error_code = api_error_code
        self.quota_exceeded = quota_exceeded
        self.retry_after = retry_after


class WebScrapingError(APIIntegrationError):
    """Web スクレイピングエラー"""

    def __init__(
        self,
        message: str,
        http_status: Optional[int] = None,
        blocked: bool = False,
        **kwargs
    ):
        super().__init__(message, **kwargs)
        self.http_status = http_status
        self.blocked = blocked


class RateLimitError(APIIntegrationError):
    """レート制限エラー"""

    def __init__(
        self,
        message: str,
        reset_at: Optional[datetime] = None,
        retry_after: Optional[float] = None,
        **kwargs
    ):
        super().__init__(message, **kwargs)
        self.reset_at = reset_at
        self.retry_after = retry_after


class DataValidationError(SatinException):
    """データ検証エラー"""

    def __init__(
        self,
        message: str,
        field: Optional[str] = None,
        value: Any = None,
        **kwargs
    ):
        super().__init__(message, **kwargs)
        self.field = field
        self.value = value


class ResourceCleanupError(SatinException):
    """リソースクリーンアップエラー"""

    def __init__(
        self,
        message: str,
        resource_name: Optional[str] = None,
        partial_cleanup: bool = False,
        **kwargs
    ):
        super().__init__(message, **kwargs)
        self.resource_name = resource_name
        self.partial_cleanup = partial_cleanup


# ========================================================================
# 2. エラーコンテキストと詳細情報
# ========================================================================

@dataclass
class ErrorContext:
    """エラーコンテキスト情報"""
    operation: str
    timestamp: datetime = field(default_factory=datetime.now)
    duration_ms: Optional[float] = None
    retry_count: int = 0
    extra_context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'operation': self.operation,
            'timestamp': self.timestamp.isoformat(),
            'duration_ms': self.duration_ms,
            'retry_count': self.retry_count,
            'extra_context': self.extra_context
        }


@dataclass
class ErrorRecoveryInfo:
    """エラー回復情報"""
    is_recoverable: bool
    recovery_action: Optional[Callable] = None
    fallback_value: Any = None
    retry_possible: bool = False
    retry_after_seconds: Optional[float] = None
    alternative_paths: List[str] = field(default_factory=list)


# ========================================================================
# 3. エラー回復戦略
# ========================================================================

class ErrorRecoveryStrategy:
    """
    エラー回復戦略の基盤クラス

    API 呼び出し・スクレイピング・DB 操作など、
    各操作に応じた回復方法を実装
    """

    @staticmethod
    def determine_recovery(exception: Exception) -> ErrorRecoveryInfo:
        """例外に基づいて回復戦略を決定"""

        if isinstance(exception, RateLimitError):
            return ErrorRecoveryInfo(
                is_recoverable=True,
                retry_possible=True,
                retry_after_seconds=exception.retry_after or 60.0,
                recovery_action=ErrorRecoveryStrategy.wait_and_retry
            )

        elif isinstance(exception, YouTubeAPIError):
            if exception.quota_exceeded:
                # クォータ超過 → 翌日まで待機 or フォールバック
                return ErrorRecoveryInfo(
                    is_recoverable=True,
                    fallback_value=None,
                    alternative_paths=['use_yt_dlp', 'use_cache']
                )
            else:
                # 一時的エラー → リトライ
                return ErrorRecoveryInfo(
                    is_recoverable=True,
                    retry_possible=True,
                    retry_after_seconds=2.0 ** exception.context.get('retry_count', 0)
                )

        elif isinstance(exception, WebScrapingError):
            if exception.http_status == 429:
                return ErrorRecoveryInfo(
                    is_recoverable=True,
                    retry_possible=True,
                    retry_after_seconds=exception.context.get('retry_after', 60.0)
                )
            elif exception.blocked:
                # IP ブロック → プロキシ切り替え or スキップ
                return ErrorRecoveryInfo(
                    is_recoverable=False,
                    alternative_paths=['rotate_proxy', 'skip_page']
                )
            elif exception.http_status in [500, 502, 503, 504]:
                return ErrorRecoveryInfo(
                    is_recoverable=True,
                    retry_possible=True,
                    retry_after_seconds=5.0
                )

        elif isinstance(exception, DataValidationError):
            # 検証エラー → 修正 or スキップ
            return ErrorRecoveryInfo(
                is_recoverable=True,
                alternative_paths=['fix_data', 'skip_record']
            )

        # デフォルト: 回復不可
        return ErrorRecoveryInfo(is_recoverable=False)

    @staticmethod
    def wait_and_retry(delay: float) -> None:
        """待機してリトライ"""
        import time
        logger.info(f"Waiting {delay}s before retry...")
        time.sleep(delay)

    @staticmethod
    def use_fallback_cache() -> Any:
        """キャッシュからフォールバック"""
        logger.info("Using fallback cache...")
        return None  # 実装時に cache_manager から取得

    @staticmethod
    def rotate_proxy() -> str:
        """プロキシを切り替え"""
        logger.info("Rotating proxy...")
        return None  # 実装時にプロキシリストから選択


# ========================================================================
# 4. エラーコンテキストマネージャ
# ========================================================================

class ErrorContextManager:
    """
    エラーコンテキストを管理し、
    エラー時に詳細な情報を自動収集・ログ出力
    """

    def __init__(self, operation: str):
        self.context = ErrorContext(operation=operation)
        self.start_time = datetime.now()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # 実行時間を記録
        self.context.duration_ms = (datetime.now() - self.start_time).total_seconds() * 1000

        if exc_val:
            # エラー発生時のログ出力
            logger.error(
                f"Operation '{self.context.operation}' failed: {exc_val}",
                extra={
                    'error_context': self.context.to_dict(),
                    'traceback': traceback.format_exc()
                }
            )

            # 回復戦略を決定
            if isinstance(exc_val, SatinException):
                recovery = ErrorRecoveryStrategy.determine_recovery(exc_val)
                logger.info(f"Recovery strategy: {recovery}")

        return False  # 例外を再発生させる

    def add_context(self, key: str, value: Any) -> None:
        """コンテキストに情報を追加"""
        self.context.extra_context[key] = value

    def record_retry(self) -> None:
        """リトライを記録"""
        self.context.retry_count += 1


# ========================================================================
# 5. デコレータ - エラーハンドリング統合
# ========================================================================

def handle_errors_gracefully(
    exceptions: tuple = (Exception,),
    fallback_value: Any = None,
    log_level: str = 'error',
    recovery_func: Optional[Callable] = None
) -> Callable:
    """
    エラーを優雅に処理するデコレータ

    Args:
        exceptions: キャッチする例外タプル
        fallback_value: エラー時の返却値
        log_level: ログレベル
        recovery_func: 回復関数

    Example:
        ```python
        @handle_errors_gracefully(
            exceptions=(YouTubeAPIError, RateLimitError),
            fallback_value=None,
            recovery_func=lambda: time.sleep(60)
        )
        def fetch_video(video_id):
            ...
        ```
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)

            except exceptions as e:
                # ログレベルに応じて出力
                log_func = getattr(logger, log_level, logger.error)

                if isinstance(e, SatinException):
                    log_func(f"{func.__name__} failed: {e.to_json()}")
                else:
                    log_func(
                        f"{func.__name__} failed: {e}",
                        exc_info=True
                    )

                # 回復関数を実行
                if recovery_func:
                    recovery_func()

                # フォールバック値を返却
                return fallback_value

        return wrapper
    return decorator


def with_error_context(operation: str) -> Callable:
    """
    エラーコンテキストをデコレータで自動管理

    Example:
        ```python
        @with_error_context("fetch_youtube_data")
        def fetch_video(video_id):
            ...
        ```
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            with ErrorContextManager(operation) as ctx:
                result = func(*args, **kwargs)
                logger.debug(f"Operation '{operation}' completed in {ctx.context.duration_ms:.1f}ms")
                return result

        return wrapper
    return decorator


# ========================================================================
# 6. エラーログフォーマッタ
# ========================================================================

class StructuredErrorFormatter(logging.Formatter):
    """
    構造化ログ形式でエラーを出力（JSON）
    OpenTelemetry / ELK Stack 統合対応
    """

    def format(self, record: logging.LogRecord) -> str:
        """レコードを構造化ログに変換"""
        log_data = {
            'timestamp': datetime.fromtimestamp(record.created).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
        }

        # エラー情報を追加
        if record.exc_info and record.exc_info[0] is not None:
            log_data['exception'] = {
                'type': record.exc_info[0].__name__,
                'message': str(record.exc_info[1]),
                'traceback': traceback.format_exception(*record.exc_info)
            }

        # カスタム属性を追加
        if hasattr(record, 'error_context'):
            log_data['error_context'] = record.error_context

        if hasattr(record, 'traceback'):
            log_data['traceback'] = record.traceback

        return json.dumps(log_data, default=str)


# ========================================================================
# 7. エラー統計・監視
# ========================================================================

@dataclass
class ErrorStatistics:
    """エラー統計情報"""
    total_errors: int = 0
    error_by_type: Dict[str, int] = field(default_factory=dict)
    error_by_operation: Dict[str, int] = field(default_factory=dict)
    recoverable_count: int = 0
    unrecoverable_count: int = 0
    last_error: Optional[Exception] = None
    last_error_time: Optional[datetime] = None

    def record_error(self, exception: Exception, operation: str = "unknown") -> None:
        """エラーを記録"""
        self.total_errors += 1
        self.last_error = exception
        self.last_error_time = datetime.now()

        # タイプ別カウント
        error_type = exception.__class__.__name__
        self.error_by_type[error_type] = self.error_by_type.get(error_type, 0) + 1

        # オペレーション別カウント
        self.error_by_operation[operation] = self.error_by_operation.get(operation, 0) + 1

        # 回復可能性
        if isinstance(exception, SatinException):
            recovery = ErrorRecoveryStrategy.determine_recovery(exception)
            if recovery.is_recoverable:
                self.recoverable_count += 1
            else:
                self.unrecoverable_count += 1

    def get_error_rate(self) -> Dict[str, float]:
        """エラー率を計算（%）"""
        total = self.total_errors
        if total == 0:
            return {}

        return {
            'recoverable_rate': (self.recoverable_count / total) * 100,
            'unrecoverable_rate': (self.unrecoverable_count / total) * 100
        }

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            'total_errors': self.total_errors,
            'error_by_type': self.error_by_type,
            'error_by_operation': self.error_by_operation,
            'recoverable_count': self.recoverable_count,
            'unrecoverable_count': self.unrecoverable_count,
            'error_rates': self.get_error_rate(),
            'last_error': str(self.last_error) if self.last_error else None,
            'last_error_time': self.last_error_time.isoformat() if self.last_error_time else None
        }


# グローバルエラー統計
global_error_stats = ErrorStatistics()


def get_error_statistics() -> Dict[str, Any]:
    """グローバルエラー統計を取得"""
    return global_error_stats.to_dict()


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # デモンストレーション
    try:
        raise YouTubeAPIError(
            "Video not found",
            api_error_code=404,
            error_code="YOUTUBE_NOT_FOUND",
            context={'video_id': 'abc123'}
        )
    except YouTubeAPIError as e:
        print(f"Error: {e.to_json()}")
        recovery = ErrorRecoveryStrategy.determine_recovery(e)
        print(f"Recovery: {recovery}")
