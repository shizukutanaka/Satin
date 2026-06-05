"""
Observability 統合基盤
ロギング・トレーシング・メトリクス・ヘルスチェック
OpenTelemetry 対応
"""

import logging
import json
import time
import threading
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
import traceback
from functools import wraps
import uuid

logger = logging.getLogger(__name__)


# ========================================================================
# 1. 構造化ログ基盤
# ========================================================================

class LogLevel(Enum):
    """ログレベル"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class StructuredLog:
    """構造化ログエントリ"""
    timestamp: datetime
    level: LogLevel
    logger_name: str
    message: str
    trace_id: str
    span_id: str
    service_name: str = "satin"
    environment: str = "production"

    # オペレーション情報
    operation: Optional[str] = None
    operation_duration_ms: Optional[float] = None

    # エラー情報
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    error_stacktrace: Optional[List[str]] = None

    # ビジネスロジック情報
    user_id: Optional[str] = None
    request_id: Optional[str] = None
    resource_id: Optional[str] = None

    # パフォーマンス情報
    latency_ms: Optional[float] = None
    cache_hit: Optional[bool] = None

    # カスタム属性
    custom_attributes: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        data = asdict(self)
        data['timestamp'] = self.timestamp.isoformat()
        data['level'] = self.level.value
        if self.error_stacktrace:
            data['error_stacktrace'] = '\n'.join(self.error_stacktrace)
        return data

    def to_json(self) -> str:
        """JSON 形式に変換"""
        return json.dumps(self.to_dict(), default=str)


class StructuredLogHandler(logging.Handler):
    """
    Python logging 用の構造化ログハンドラ
    """

    def __init__(self, trace_provider=None):
        super().__init__()
        self.trace_provider = trace_provider
        self.logs: List[StructuredLog] = []

    def emit(self, record: logging.LogRecord):
        """ログレコードを構造化ログに変換して出力"""
        try:
            # トレース情報の取得
            trace_id = getattr(record, 'trace_id', str(uuid.uuid4()))
            span_id = getattr(record, 'span_id', str(uuid.uuid4()))

            # エラー情報
            error_info = None
            error_stacktrace = None
            if record.exc_info:
                error_info = record.exc_info[0].__name__
                error_stacktrace = traceback.format_exception(*record.exc_info)

            # 構造化ログを生成
            structured = StructuredLog(
                timestamp=datetime.fromtimestamp(record.created),
                level=LogLevel[record.levelname],
                logger_name=record.name,
                message=record.getMessage(),
                trace_id=trace_id,
                span_id=span_id,
                operation=getattr(record, 'operation', None),
                operation_duration_ms=getattr(record, 'operation_duration_ms', None),
                error_type=error_info,
                error_message=str(record.exc_info[1]) if record.exc_info else None,
                error_stacktrace=error_stacktrace,
                user_id=getattr(record, 'user_id', None),
                request_id=getattr(record, 'request_id', None),
                resource_id=getattr(record, 'resource_id', None),
                latency_ms=getattr(record, 'latency_ms', None),
                cache_hit=getattr(record, 'cache_hit', None),
                custom_attributes=getattr(record, 'custom_attributes', {})
            )

            self.logs.append(structured)

            # 標準出力（JSON）
            print(structured.to_json())

        except Exception:
            self.handleError(record)

    def get_logs(self) -> List[Dict[str, Any]]:
        """すべてのログを取得"""
        return [log.to_dict() for log in self.logs]


# ========================================================================
# 2. 分散トレーシング (OpenTelemetry 対応)
# ========================================================================

@dataclass
class Span:
    """トレーシングスパン"""
    span_id: str
    trace_id: str
    parent_span_id: Optional[str] = None
    operation_name: str = "unknown"
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    status: str = "UNSET"  # UNSET, OK, ERROR
    attributes: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None

    def end(self, status: str = "OK", error: Optional[str] = None) -> None:
        """スパンを終了"""
        self.end_time = datetime.now()
        self.status = status
        self.error = error

    def duration_ms(self) -> float:
        """実行時間（ミリ秒）を取得"""
        end = self.end_time or datetime.now()
        return (end - self.start_time).total_seconds() * 1000

    def add_event(self, name: str, attributes: Optional[Dict[str, Any]] = None) -> None:
        """スパンにイベントを追加"""
        self.events.append({
            'name': name,
            'timestamp': datetime.now().isoformat(),
            'attributes': attributes or {}
        })

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            'span_id': self.span_id,
            'trace_id': self.trace_id,
            'parent_span_id': self.parent_span_id,
            'operation_name': self.operation_name,
            'start_time': self.start_time.isoformat(),
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'duration_ms': self.duration_ms(),
            'status': self.status,
            'attributes': self.attributes,
            'events': self.events,
            'error': self.error
        }


class TraceProvider:
    """
    分散トレーシング提供者
    OpenTelemetry との統合ポイント
    """

    def __init__(self):
        self.spans: Dict[str, Span] = {}
        self.active_trace_id: Optional[str] = None
        self.active_span_stack: List[str] = []

    def start_span(
        self,
        operation_name: str,
        trace_id: Optional[str] = None,
        parent_span_id: Optional[str] = None
    ) -> Span:
        """新しいスパンを開始"""
        trace_id = trace_id or str(uuid.uuid4())
        span_id = str(uuid.uuid4())

        span = Span(
            span_id=span_id,
            trace_id=trace_id,
            parent_span_id=parent_span_id,
            operation_name=operation_name
        )

        self.spans[span_id] = span
        self.active_span_stack.append(span_id)
        self.active_trace_id = trace_id

        logger.debug(f"Span started: {operation_name} (span_id: {span_id})")
        return span

    def end_span(self, span_id: str, status: str = "OK", error: Optional[str] = None) -> None:
        """スパンを終了"""
        if span_id in self.spans:
            self.spans[span_id].end(status, error)
            if self.active_span_stack and self.active_span_stack[-1] == span_id:
                self.active_span_stack.pop()

    def get_traces(self) -> Dict[str, List[Dict[str, Any]]]:
        """すべてのトレースを取得"""
        traces = {}
        for span in self.spans.values():
            trace_id = span.trace_id
            if trace_id not in traces:
                traces[trace_id] = []
            traces[trace_id].append(span.to_dict())

        return traces


# ========================================================================
# 3. メトリクス収集
# ========================================================================

@dataclass
class Metrics:
    """アプリケーションメトリクス"""
    operation_latencies: Dict[str, List[float]] = field(default_factory=dict)
    api_call_counts: Dict[str, int] = field(default_factory=dict)
    error_counts: Dict[str, int] = field(default_factory=dict)
    cache_hit_rates: Dict[str, float] = field(default_factory=dict)
    active_connections: int = 0
    memory_usage_mb: float = 0.0
    # Guards the read-modify-write counter updates below so increments are not
    # lost when recorded from multiple threads (e.g. ThreadPoolExecutor workers).
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False,
                                  repr=False, compare=False)
    # Keep at most this many latency samples per operation (bounds memory).
    _MAX_LATENCY_SAMPLES: int = field(default=1000, init=False, repr=False, compare=False)

    def record_operation_latency(self, operation: str, latency_ms: float) -> None:
        """オペレーションレイテンシを記録"""
        with self._lock:
            samples = self.operation_latencies.setdefault(operation, [])
            samples.append(latency_ms)
            if len(samples) > self._MAX_LATENCY_SAMPLES:
                del samples[0]

    def record_api_call(self, api_name: str) -> None:
        """API 呼び出しをカウント"""
        with self._lock:
            self.api_call_counts[api_name] = self.api_call_counts.get(api_name, 0) + 1

    def record_error(self, error_type: str) -> None:
        """エラーをカウント"""
        with self._lock:
            self.error_counts[error_type] = self.error_counts.get(error_type, 0) + 1

    def get_summary(self) -> Dict[str, Any]:
        """メトリクスサマリーを取得"""
        import statistics

        # Take a consistent snapshot under the lock, then compute outside it.
        with self._lock:
            latencies_snapshot = {op: list(v) for op, v in self.operation_latencies.items()}
            api_calls = dict(self.api_call_counts)
            errors = dict(self.error_counts)
            cache_hit_rates = dict(self.cache_hit_rates)
            active_connections = self.active_connections
            memory_usage_mb = self.memory_usage_mb

        latency_stats = {}
        for op, latencies in latencies_snapshot.items():
            if latencies:
                latency_stats[op] = {
                    'mean_ms': statistics.mean(latencies),
                    'median_ms': statistics.median(latencies),
                    'max_ms': max(latencies),
                    'min_ms': min(latencies),
                    'count': len(latencies)
                }

        return {
            'operation_latencies': latency_stats,
            'api_calls': api_calls,
            'errors': errors,
            'cache_hit_rates': cache_hit_rates,
            'active_connections': active_connections,
            'memory_usage_mb': memory_usage_mb
        }


# グローバルメトリクス
global_metrics = Metrics()


# ========================================================================
# 4. ヘルスチェック・ライブネス検査
# ========================================================================

@dataclass
class HealthCheckResult:
    """ヘルスチェック結果"""
    status: str  # "UP", "DEGRADED", "DOWN"
    checks: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    uptime_seconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class HealthChecker:
    """
    アプリケーションヘルスチェック
    Kubernetes probe 統合対応
    """

    def __init__(self):
        self.checks: Dict[str, Callable] = {}
        self.start_time = datetime.now()

    def register_check(self, name: str, check_func: Callable) -> None:
        """ヘルスチェック関数を登録"""
        self.checks[name] = check_func

    async def check_health(self) -> HealthCheckResult:
        """ヘルスチェック実行"""
        results = {}
        overall_status = "UP"

        for check_name, check_func in self.checks.items():
            try:
                result = await self._execute_check(check_func)
                results[check_name] = {
                    'status': 'UP' if result else 'DOWN',
                    'message': 'Healthy' if result else 'Unhealthy'
                }

                if not result:
                    overall_status = "DEGRADED"

            except Exception as e:
                overall_status = "DEGRADED"
                results[check_name] = {
                    'status': 'ERROR',
                    'message': str(e)
                }

        uptime = (datetime.now() - self.start_time).total_seconds()

        return HealthCheckResult(
            status=overall_status,
            checks=results,
            uptime_seconds=uptime
        )

    async def _execute_check(self, check_func: Callable) -> bool:
        """ヘルスチェック関数を実行"""
        import asyncio
        import inspect

        if inspect.iscoroutinefunction(check_func):
            return await asyncio.wait_for(check_func(), timeout=5.0)
        else:
            return check_func()


# ========================================================================
# 5. デコレータ - Observability 統合
# ========================================================================

def trace_operation(operation_name: str):
    """
    デコレータ: 自動トレーシング
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            trace_provider = TraceProvider()
            span = trace_provider.start_span(operation_name)

            start_time = time.time()
            try:
                result = func(*args, **kwargs)

                elapsed_ms = (time.time() - start_time) * 1000
                span.end(status="OK")

                # メトリクス記録
                global_metrics.record_operation_latency(operation_name, elapsed_ms)

                return result

            except Exception as e:
                span.end(status="ERROR", error=str(e))
                global_metrics.record_error(type(e).__name__)
                raise

        return wrapper
    return decorator


def observe_metrics(operation_name: str):
    """
    デコレータ: メトリクス自動記録
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()

            try:
                result = func(*args, **kwargs)
                elapsed_ms = (time.time() - start_time) * 1000
                global_metrics.record_operation_latency(operation_name, elapsed_ms)
                return result

            except Exception as e:
                global_metrics.record_error(type(e).__name__)
                raise

        return wrapper
    return decorator


# ========================================================================
# 6. ログ・トレース・メトリクス統合取得
# ========================================================================

class ObservabilityExporter:
    """
    Observability データを統合エクスポート
    """

    def __init__(self, log_handler: StructuredLogHandler, trace_provider: TraceProvider):
        self.log_handler = log_handler
        self.trace_provider = trace_provider

    def export_all(self) -> Dict[str, Any]:
        """すべての Observability データをエクスポート"""
        return {
            'timestamp': datetime.now().isoformat(),
            'logs': self.log_handler.get_logs(),
            'traces': self.trace_provider.get_traces(),
            'metrics': global_metrics.get_summary()
        }

    def export_json(self) -> str:
        """JSON 形式でエクスポート"""
        return json.dumps(self.export_all(), indent=2, default=str)


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)

    # デモンストレーション
    log_handler = StructuredLogHandler()
    trace_provider = TraceProvider()

    # トレーシング
    span = trace_provider.start_span("demo_operation")
    span.add_event("operation_started")
    time.sleep(0.1)
    span.add_event("processing_complete")
    span.end("OK")

    # メトリクス記録
    global_metrics.record_operation_latency("demo", 100.5)
    global_metrics.record_api_call("youtube_api")

    # エクスポート
    exporter = ObservabilityExporter(log_handler, trace_provider)
    print(exporter.export_json())
