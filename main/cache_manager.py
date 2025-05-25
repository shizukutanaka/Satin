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
from typing import Any, Callable, Dict, Optional, Tuple
from datetime import datetime, timedelta
from config_manager import get_config_manager

logger = logging.getLogger(__name__)

class CacheManager:
    """キャッシュ管理クラス"""
    def __init__(self):
        """初期化"""
        self.config = get_config_manager()
        self.settings = self.config.get_plugin_config("cache_manager")
        
        if self.settings:
            self.memory_cache_size = self.settings.get("memory_cache_size", 1024)  # メモリキャッシュサイズ（MB）
            self.disk_cache_size = self.settings.get("disk_cache_size", 1024)  # ディスクキャッシュサイズ（MB）
            self.cache_ttl = self.settings.get("cache_ttl", 3600)  # キャッシュ有効時間（秒）
            self.cleanup_interval = self.settings.get("cleanup_interval", 3600)  # クリーンアップ間隔（秒）
            
            # キャッシュディレクトリの初期化
            self.cache_dir = Path(self.config.config_path).parent / "cache"
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            
            # メモリキャッシュの初期化
            self.memory_cache = {}
            self.memory_cache_size_bytes = self.memory_cache_size * 1024 * 1024
            
            # キャッシュクリーンアップスレッドの開始
            self.cleanup_thread = threading.Thread(target=self._cleanup_cache)
            self.cleanup_thread.daemon = True
            self.cleanup_thread.start()
            
            # キャッシュ統計の初期化
            self.cache_hits = 0
            self.cache_misses = 0
            self.last_stats_update = datetime.now()
            
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
    
    def _cleanup_cache(self) -> None:
        """キャッシュのクリーンアップ"""
        while True:
            try:
                # メモリキャッシュのクリーンアップ
                self._cleanup_memory_cache()
                
                # ディスクキャッシュのクリーンアップ
                self._cleanup_disk_cache()
                
                # キャッシュ統計の更新
                self._update_cache_stats()
                
                time.sleep(self.cleanup_interval)
            except Exception as e:
                logger.error(f"キャッシュクリーンアップ中にエラーが発生しました: {e}")
                time.sleep(self.cleanup_interval)
    
    def _cleanup_memory_cache(self) -> None:
        """メモリキャッシュのクリーンアップ"""
        current_size = sum(len(str(v[0])) for v in self.memory_cache.values())
        if current_size > self.memory_cache_size_bytes:
            # キャッシュサイズの制限を超えた場合、古いキャッシュを削除
            sorted_cache = sorted(
                self.memory_cache.items(),
                key=lambda x: x[1][1],  # タイムスタンプでソート
                reverse=True
            )
            for key, (value, timestamp) in sorted_cache:
                if current_size <= self.memory_cache_size_bytes:
                    break
                del self.memory_cache[key]
                current_size -= len(str(value))
    
    def _cleanup_disk_cache(self) -> None:
        """ディスクキャッシュのクリーンアップ"""
        current_size = 0
        cache_files = []
        
        # キャッシュファイルのリストとサイズの取得
        for cache_file in self.cache_dir.glob("*.json"):
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
