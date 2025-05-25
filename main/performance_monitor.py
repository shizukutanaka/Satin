"""
パフォーマンス監視システム
バージョン: 1.0.0
特徴:
- リアルタイムパフォーマンスモニタリング
- メモリ使用量監視
- CPU使用率監視
- ディスクIO監視
- ネットワークIO監視
- アラート通知機能
"""
import os
import psutil
import logging
import threading
import time
from datetime import datetime
from typing import Dict, Any, Optional
from config_manager import get_config_manager

logger = logging.getLogger(__name__)

class PerformanceMonitor:
    """パフォーマンス監視クラス"""
    def __init__(self):
        """初期化"""
        self.config = get_config_manager()
        self.settings = self.config.get_plugin_config("performance_monitor")
        
        if self.settings:
            self.interval = self.settings.get("interval", 5)  # 監視間隔（秒）
            self.thresholds = {
                "memory": self.settings.get("memory_threshold", 80),  # メモリ使用率閾値（%）
                "cpu": self.settings.get("cpu_threshold", 90),  # CPU使用率閾値（%）
                "disk": self.settings.get("disk_threshold", 90),  # ディスク使用率閾値（%）
                "network": self.settings.get("network_threshold", 1000000)  # ネットワークIO閾値（bps）
            }
            
            self.alert_enabled = self.settings.get("alert_enabled", True)
            self.alert_threshold = self.settings.get("alert_threshold", 3)  # 連続アラート閾値
            
            self.alert_count = 0
            self.last_alert = None
            
            # モニタリングスレッドの初期化
            self.monitor_thread = None
            self.running = False
            
    def start_monitoring(self) -> None:
        """モニタリングを開始"""
        if not self.running:
            self.running = True
            self.monitor_thread = threading.Thread(target=self._monitor)
            self.monitor_thread.daemon = True
            self.monitor_thread.start()
            logger.info("パフォーマンス監視を開始しました")
    
    def stop_monitoring(self) -> None:
        """モニタリングを停止"""
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join()
            logger.info("パフォーマンス監視を停止しました")
    
    def _monitor(self) -> None:
        """モニタリングループ"""
        while self.running:
            try:
                # パフォーマンスデータの収集
                stats = self._collect_stats()
                
                # アラートチェック
                if self._check_alerts(stats):
                    self._send_alert(stats)
                
                # ログ記録
                self._log_stats(stats)
                
                time.sleep(self.interval)
            except Exception as e:
                logger.error(f"パフォーマンス監視中にエラーが発生しました: {e}")
                time.sleep(self.interval)
    
    def _collect_stats(self) -> Dict[str, Any]:
        """パフォーマンス統計を収集"""
        return {
            "timestamp": datetime.now().isoformat(),
            "memory": {
                "total": psutil.virtual_memory().total,
                "used": psutil.virtual_memory().used,
                "percent": psutil.virtual_memory().percent
            },
            "cpu": {
                "usage": psutil.cpu_percent(interval=1),
                "count": psutil.cpu_count()
            },
            "disk": {
                "io_read": psutil.disk_io_counters().read_bytes,
                "io_write": psutil.disk_io_counters().write_bytes,
                "percent": psutil.disk_usage('/').percent
            },
            "network": {
                "io_sent": psutil.net_io_counters().bytes_sent,
                "io_recv": psutil.net_io_counters().bytes_recv
            }
        }
    
    def _check_alerts(self, stats: Dict[str, Any]) -> bool:
        """アラート条件をチェック"""
        alerts = []
        
        # メモリチェック
        if stats["memory"]["percent"] > self.thresholds["memory"]:
            alerts.append(f"メモリ使用率が{self.thresholds['memory']}%を超過")
        
        # CPUチェック
        if stats["cpu"]["usage"] > self.thresholds["cpu"]:
            alerts.append(f"CPU使用率が{self.thresholds['cpu']}%を超過")
        
        # ディスクチェック
        if stats["disk"]["percent"] > self.thresholds["disk"]:
            alerts.append(f"ディスク使用率が{self.thresholds['disk']}%を超過")
        
        # ネットワークチェック
        if stats["network"]["io_sent"] + stats["network"]["io_recv"] > self.thresholds["network"]:
            alerts.append(f"ネットワークIOが{self.thresholds['network']}bpsを超過")
        
        # アラート発生時
        if alerts:
            self.alert_count += 1
            if self.alert_count >= self.alert_threshold:
                return True
        else:
            self.alert_count = 0
        
        return False
    
    def _send_alert(self, stats: Dict[str, Any]) -> None:
        """アラートを送信"""
        if self.alert_enabled:
            message = f"パフォーマンス警告: {datetime.now().isoformat()}\n"
            message += f"メモリ: {stats['memory']['percent']}%\n"
            message += f"CPU: {stats['cpu']['usage']}%\n"
            message += f"ディスク: {stats['disk']['percent']}%\n"
            
            # アラート通知（プラットフォームに応じて）
            if os.name == 'nt':
                import win10toast
                toaster = win10toast.ToastNotifier()
                toaster.show_toast(
                    "Satin Performance Alert",
                    message,
                    duration=10
                )
            else:
                print(f"\n警告: {message}")
            
            self.last_alert = datetime.now()
            self.alert_count = 0
    
    def _log_stats(self, stats: Dict[str, Any]) -> None:
        """パフォーマンス統計をログに記録"""
        log_msg = f"パフォーマンス統計 - {stats['timestamp']}\n"
        log_msg += f"メモリ: {stats['memory']['percent']}%\n"
        log_msg += f"CPU: {stats['cpu']['usage']}%\n"
        log_msg += f"ディスク: {stats['disk']['percent']}%\n"
        log_msg += f"ネットワーク: {stats['network']['io_sent'] + stats['network']['io_recv']}bps\n"
        
        logger.info(log_msg)
