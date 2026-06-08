"""
Graceful Shutdown 実装
シグナルハンドリング、リソースクリーンアップ、進行中タスク完了待機
"""

import asyncio
import signal
import logging
import sys
from typing import Callable, Optional, List, Dict, Any
from dataclasses import dataclass
from datetime import datetime
from functools import wraps

logger = logging.getLogger(__name__)


# ========================================================================
# 1. Graceful Shutdown マネージャ
# ========================================================================

@dataclass
class ShutdownEvent:
    """シャットダウンイベント"""
    signal_name: str
    timestamp: datetime
    reason: str
    is_forced: bool = False  # Ctrl+C 二回押下など


class GracefulShutdownManager:
    """
    Graceful Shutdown の統一インターフェース

    - シグナルハンドリング
    - リソースクリーンアップ
    - 進行中タスク完了待機
    - ロギング
    """

    def __init__(self, shutdown_timeout: float = 30.0):
        """
        Args:
            shutdown_timeout: シャットダウン最大待機時間（秒）
        """
        self.shutdown_timeout = shutdown_timeout
        self.is_shutting_down = False
        self.shutdown_event = asyncio.Event()
        self.cleanup_handlers: List[Tuple[str, Callable]] = []
        self.active_tasks: List[asyncio.Task] = []
        self.logger = logger

    def register_cleanup(self, name: str, handler: Callable) -> None:
        """
        クリーンアップハンドラを登録

        Args:
            name: ハンドラ名
            handler: クリーンアップ関数 (async or sync)
        """
        self.cleanup_handlers.append((name, handler))
        self.logger.debug(f"Registered cleanup handler: {name}")

    def register_task(self, task: asyncio.Task) -> None:
        """実行中のタスクを登録"""
        self.active_tasks.append(task)

    def unregister_task(self, task: asyncio.Task) -> None:
        """タスク完了時に登録解除"""
        try:
            self.active_tasks.remove(task)
        except ValueError:
            pass

    async def _run_cleanup(self) -> None:
        """すべてのクリーンアップハンドラを実行"""
        self.logger.info("Running cleanup handlers...")

        for name, handler in self.cleanup_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await asyncio.wait_for(
                        handler(),
                        timeout=self.shutdown_timeout / len(self.cleanup_handlers)
                    )
                else:
                    handler()

                self.logger.info(f"✓ Cleaned up: {name}")

            except asyncio.TimeoutError:
                self.logger.error(f"✗ Cleanup timeout: {name}")
            except Exception as e:
                self.logger.error(f"✗ Cleanup error in {name}: {e}")

    async def _cancel_tasks(self) -> None:
        """進行中のタスクをキャンセル"""
        if not self.active_tasks:
            return

        self.logger.info(f"Cancelling {len(self.active_tasks)} active tasks...")

        # 全タスクキャンセル
        for task in self.active_tasks:
            if not task.done():
                task.cancel()
                self.logger.debug(f"Cancelled task: {task.get_name()}")

        # キャンセル完了を待機
        try:
            await asyncio.wait_for(
                asyncio.gather(*self.active_tasks, return_exceptions=True),
                timeout=5.0
            )
        except asyncio.TimeoutError:
            self.logger.warning("Task cancellation timeout - forcing shutdown")

    async def shutdown(self, signal_name: str = "UNKNOWN") -> None:
        """
        グレースフルシャットダウン実行

        Args:
            signal_name: シグナル名
        """
        if self.is_shutting_down:
            self.logger.warning("Shutdown already in progress")
            return

        self.is_shutting_down = True
        self.logger.info(f"=== Graceful Shutdown initiated by {signal_name} ===")

        start_time = datetime.now()

        try:
            # ステップ 1: クリーンアップハンドラ実行
            await self._run_cleanup()

            # ステップ 2: 進行中タスクのキャンセル
            await self._cancel_tasks()

            # ステップ 3: シャットダウン完了通知
            self.shutdown_event.set()

        finally:
            elapsed = (datetime.now() - start_time).total_seconds()
            self.logger.info(f"=== Shutdown completed in {elapsed:.2f}s ===")


# ========================================================================
# 2. シグナルハンドラ統合
# ========================================================================

class SignalHandler:
    """
    シグナルハンドリングの統一インターフェース

    - SIGTERM (正常終了)
    - SIGINT (Ctrl+C)
    - SIGHUP (設定再読込)
    """

    def __init__(self, shutdown_manager: GracefulShutdownManager):
        self.shutdown_manager = shutdown_manager
        self.logger = logger
        self._shutdown_count = 0

    def register_handlers(self) -> None:
        """システムシグナルハンドラを登録"""
        if sys.platform != 'win32':
            # Unix/Linux — must be called from within a running event loop
            loop = asyncio.get_running_loop()

            loop.add_signal_handler(
                signal.SIGTERM,
                lambda: asyncio.create_task(self._handle_sigterm())
            )

            loop.add_signal_handler(
                signal.SIGINT,
                lambda: asyncio.create_task(self._handle_sigint())
            )

            self.logger.debug("Signal handlers registered (Unix/Linux)")
        else:
            # Windows (制限あり)
            signal.signal(signal.SIGTERM, self._handle_sigterm_win32)
            self.logger.debug("Signal handlers registered (Windows)")

    async def _handle_sigterm(self) -> None:
        """SIGTERM ハンドラ (正常終了)"""
        self.logger.info("Received SIGTERM")
        await self.shutdown_manager.shutdown("SIGTERM")

    async def _handle_sigint(self) -> None:
        """SIGINT ハンドラ (Ctrl+C)"""
        self._shutdown_count += 1

        if self._shutdown_count == 1:
            self.logger.info("Received SIGINT - graceful shutdown initiated")
            await self.shutdown_manager.shutdown("SIGINT")
        else:
            self.logger.warning(f"SIGINT received {self._shutdown_count} times - forcing shutdown")
            sys.exit(1)

    def _handle_sigterm_win32(self, signum, frame):
        """Windows SIGTERM ハンドラ"""
        self.logger.info("Received SIGTERM (Windows)")
        # Windows では asyncio.create_task が安全でないため、フラグ設定
        self.shutdown_manager.is_shutting_down = True


# ========================================================================
# 3. Async アプリケーション用 Graceful Shutdown
# ========================================================================

class AsyncApplication:
    """
    Graceful Shutdown を統合した非同期アプリケーション基盤
    """

    def __init__(self, name: str, shutdown_timeout: float = 30.0):
        """
        Args:
            name: アプリケーション名
            shutdown_timeout: シャットダウンタイムアウト（秒）
        """
        self.name = name
        self.shutdown_manager = GracefulShutdownManager(shutdown_timeout)
        self.signal_handler = SignalHandler(self.shutdown_manager)
        self.logger = logger

    def register_cleanup(self, name: str, handler: Callable) -> None:
        """クリーンアップハンドラ登録"""
        self.shutdown_manager.register_cleanup(name, handler)

    def track_task(self, task: asyncio.Task) -> None:
        """タスク登録"""
        self.shutdown_manager.register_task(task)

    async def run(self, main_coro) -> None:
        """
        アプリケーション実行

        Args:
            main_coro: メインコルーチン
        """
        self.logger.info(f"Starting {self.name}...")

        # シグナルハンドラ登録
        self.signal_handler.register_handlers()

        main_task = asyncio.create_task(main_coro)
        self.track_task(main_task)

        try:
            # メインコルーチン実行
            await main_task

        except asyncio.CancelledError:
            self.logger.info("Main task cancelled")

        except Exception as e:
            self.logger.error(f"Error in main task: {e}", exc_info=True)

        finally:
            # グレースフルシャットダウン実行
            if not self.shutdown_manager.is_shutting_down:
                await self.shutdown_manager.shutdown("NORMAL_EXIT")


# ========================================================================
# 4. デコレータ - Graceful Shutdown 対応
# ========================================================================

def with_graceful_shutdown(
    shutdown_manager: GracefulShutdownManager
) -> Callable:
    """
    デコレータ: 非同期関数を Graceful Shutdown 対応にする

    Example:
        ```python
        @with_graceful_shutdown(manager)
        async def my_async_function():
            try:
                # 処理
                pass
            finally:
                # クリーンアップ
                pass
        ```
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            task = asyncio.current_task()
            if task:
                shutdown_manager.register_task(task)

            try:
                return await func(*args, **kwargs)
            finally:
                if task:
                    shutdown_manager.unregister_task(task)

        return wrapper

    return decorator


# ========================================================================
# 5. リソースコンテキストマネージャ - Graceful Shutdown 対応
# ========================================================================

class AsyncContextResource:
    """
    非同期リソース管理（Graceful Shutdown 統合）
    """

    def __init__(
        self,
        name: str,
        init_func: Callable,
        cleanup_func: Callable,
        shutdown_manager: Optional[GracefulShutdownManager] = None
    ):
        self.name = name
        self.init_func = init_func
        self.cleanup_func = cleanup_func
        self.shutdown_manager = shutdown_manager
        self.resource = None

    async def __aenter__(self):
        """初期化"""
        if asyncio.iscoroutinefunction(self.init_func):
            self.resource = await self.init_func()
        else:
            self.resource = self.init_func()

        # Graceful Shutdown に登録
        if self.shutdown_manager:
            self.shutdown_manager.register_cleanup(
                self.name,
                lambda: self.cleanup_func(self.resource)
            )

        return self.resource

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """クリーンアップ"""
        if self.resource:
            if asyncio.iscoroutinefunction(self.cleanup_func):
                await self.cleanup_func(self.resource)
            else:
                self.cleanup_func(self.resource)


# ========================================================================
# 6. ヘルスチェック機能
# ========================================================================

@dataclass
class HealthStatus:
    """ヘルスチェック状態"""
    is_healthy: bool
    message: str
    checks: Dict[str, bool]
    timestamp: datetime


class HealthChecker:
    """
    アプリケーションヘルスチェック

    Graceful Shutdown 中は unhealthy を返す
    """

    def __init__(self, shutdown_manager: GracefulShutdownManager):
        self.shutdown_manager = shutdown_manager
        self.checks: Dict[str, Callable] = {}
        self.logger = logger

    def register_check(self, name: str, check_func: Callable[[],  bool]) -> None:
        """ヘルスチェック関数を登録"""
        self.checks[name] = check_func

    async def check(self) -> HealthStatus:
        """ヘルスチェック実行"""
        check_results = {}

        for name, check_func in self.checks.items():
            try:
                if asyncio.iscoroutinefunction(check_func):
                    result = await asyncio.wait_for(check_func(), timeout=5.0)
                else:
                    result = check_func()

                check_results[name] = result

            except asyncio.TimeoutError:
                self.logger.warning(f"Health check timeout: {name}")
                check_results[name] = False

            except Exception as e:
                self.logger.error(f"Health check error: {name}: {e}")
                check_results[name] = False

        is_healthy = (
            not self.shutdown_manager.is_shutting_down and
            all(check_results.values())
        )

        message = (
            "Shutting down" if self.shutdown_manager.is_shutting_down
            else "Healthy" if is_healthy
            else f"Unhealthy: {[k for k, v in check_results.items() if not v]}"
        )

        return HealthStatus(
            is_healthy=is_healthy,
            message=message,
            checks=check_results,
            timestamp=datetime.now()
        )


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # デモンストレーション
    async def main():
        app = AsyncApplication("DemoApp")

        # クリーンアップハンドラ登録
        app.register_cleanup("database", lambda: print("Closing database..."))
        app.register_cleanup("cache", lambda: print("Flushing cache..."))

        # メイン処理
        async def dummy_main():
            try:
                print("Application running...")
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                print("Main task cancelled")

        await app.run(dummy_main())

    asyncio.run(main())
