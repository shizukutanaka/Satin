"""
設定管理の拡張クラス。

ConfigManager を継承し、以下の機能を追加する:
  - スキーマ検証（JSON Schema サブセット）
  - 設定の diff（変更点の可視化）
  - undo スタック（最大 N 世代の変更履歴）
  - ファイル監視によるホットリロード（watchdog がある場合のみ）
  - 設定のエクスポート／インポート（JSON）
"""
from __future__ import annotations

import copy
import json
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

from config_manager import ConfigManager

_UNDO_LIMIT = 20


class ConfigDiff:
    """2 つの設定辞書の差分を表す。"""

    def __init__(self, before: dict, after: dict):
        self.added: Dict[str, Any] = {}
        self.removed: Dict[str, Any] = {}
        self.changed: Dict[str, Tuple[Any, Any]] = {}
        self._compute(before, after, prefix="")

    def _compute(self, before: dict, after: dict, prefix: str) -> None:
        all_keys = set(before) | set(after)
        for k in all_keys:
            full_key = f"{prefix}.{k}" if prefix else k
            if k not in before:
                self.added[full_key] = after[k]
            elif k not in after:
                self.removed[full_key] = before[k]
            elif isinstance(before[k], dict) and isinstance(after[k], dict):
                self._compute(before[k], after[k], prefix=full_key)
            elif before[k] != after[k]:
                self.changed[full_key] = (before[k], after[k])

    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.changed)

    def summary(self) -> str:
        lines = []
        for k, v in sorted(self.added.items()):
            lines.append(f"+ {k}: {v!r}")
        for k, v in sorted(self.removed.items()):
            lines.append(f"- {k}: {v!r}")
        for k, (old, new) in sorted(self.changed.items()):
            lines.append(f"~ {k}: {old!r} -> {new!r}")
        return "\n".join(lines) if lines else "(no changes)"


class EnhancedConfigManager(ConfigManager):
    """ConfigManager に diff / undo / ホットリロード機能を追加した拡張クラス。"""

    def __init__(self, config_path: Optional[str] = None, undo_limit: int = _UNDO_LIMIT):
        super().__init__(config_path=config_path)
        self._undo_limit = undo_limit
        self._undo_stack: List[dict] = []
        self._change_listeners: List[Callable[[ConfigDiff], None]] = []
        self._watcher = None
        self._last_mtime: float = 0.0

    # ------------------------------------------------------------------
    # File I/O — read/write config_path directly so tests can use tmp paths
    # ------------------------------------------------------------------

    def load(self) -> dict:
        """config_path からJSON を直接読み込む。"""
        try:
            with open(self.config_path, encoding="utf-8") as fh:
                self.current_config = json.load(fh)
        except (OSError, json.JSONDecodeError):
            self.current_config = {}
        return self.current_config

    def _write(self, data: dict) -> bool:
        """config_path へ原子書き込みする。"""
        tmp = self.config_path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self.config_path)
            self.current_config = copy.deepcopy(data)
            return True
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            return False

    # ------------------------------------------------------------------
    # Undo stack
    # ------------------------------------------------------------------

    def _push_undo(self, snapshot: dict) -> None:
        self._undo_stack.append(copy.deepcopy(snapshot))
        if len(self._undo_stack) > self._undo_limit:
            self._undo_stack.pop(0)

    def save(self, new_config: dict) -> bool:
        before = copy.deepcopy(self.current_config) if self.current_config is not None else {}
        ok = self._write(new_config)
        if ok:
            self._push_undo(before)
            diff = ConfigDiff(before, new_config)
            for cb in list(self._change_listeners):
                try:
                    cb(diff)
                except Exception:
                    pass
        return ok

    def undo(self) -> bool:
        """直前の save() を元に戻す。スタックが空なら False。"""
        if not self._undo_stack:
            return False
        prev = self._undo_stack.pop()
        return self._write(prev)

    def undo_depth(self) -> int:
        return len(self._undo_stack)

    # ------------------------------------------------------------------
    # Diff
    # ------------------------------------------------------------------

    def diff(self, other: dict) -> ConfigDiff:
        """現在設定と other の差分を返す。"""
        current = self.current_config or {}
        return ConfigDiff(current, other)

    # ------------------------------------------------------------------
    # Change listeners
    # ------------------------------------------------------------------

    def add_change_listener(self, cb: Callable[[ConfigDiff], None]) -> None:
        """設定変更時に呼ばれるコールバックを登録する。"""
        self._change_listeners.append(cb)

    def remove_change_listener(self, cb: Callable[[ConfigDiff], None]) -> None:
        try:
            self._change_listeners.remove(cb)
        except ValueError:
            pass

    # ------------------------------------------------------------------
    # Hot-reload (optional watchdog)
    # ------------------------------------------------------------------

    def start_watching(self) -> bool:
        """watchdog がインストール済みなら設定ファイルを監視してホットリロードする。"""
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler

            path = os.path.abspath(self.config_path)
            watch_dir = os.path.dirname(path)
            mgr = self

            class _Handler(FileSystemEventHandler):
                def on_modified(self, event):
                    if os.path.abspath(event.src_path) == path:
                        mgr._hot_reload()

            observer = Observer()
            observer.schedule(_Handler(), watch_dir, recursive=False)
            observer.start()
            self._watcher = observer
            return True
        except Exception:
            return False

    def stop_watching(self) -> None:
        if self._watcher is not None:
            try:
                self._watcher.stop()
                self._watcher.join(timeout=2)
            except Exception:
                pass
            self._watcher = None

    def _hot_reload(self) -> None:
        before = copy.deepcopy(self.current_config) if self.current_config is not None else {}
        try:
            new = self.load()
        except Exception:
            return
        diff = ConfigDiff(before, new)
        if not diff.is_empty():
            for cb in list(self._change_listeners):
                try:
                    cb(diff)
                except Exception:
                    pass

    def poll_reload(self) -> bool:
        """mtime を確認して変更があれば再読み込みし True を返す。watchdog 不要。"""
        try:
            mtime = os.path.getmtime(self.config_path)
        except OSError:
            return False
        if self._last_mtime == 0.0:
            self._last_mtime = mtime
            return False
        if mtime != self._last_mtime:
            self._last_mtime = mtime
            self._hot_reload()
            return True
        return False

    # ------------------------------------------------------------------
    # Export / import
    # ------------------------------------------------------------------

    def export_json(self, path: str, indent: int = 2) -> bool:
        """現在の設定を JSON ファイルにエクスポートする（原子書き込み）。"""
        if self.current_config is None:
            self.load()
        try:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.current_config, fh, ensure_ascii=False, indent=indent)
            os.replace(tmp, path)
            return True
        except Exception:
            return False

    def import_json(self, path: str, merge: bool = False) -> bool:
        """JSON ファイルから設定をインポートする。merge=True なら上書きマージ。"""
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                return False
            if merge and self.current_config is not None:
                merged = copy.deepcopy(self.current_config)
                _deep_update(merged, data)
                data = merged
            return self.save(data)
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Schema validation (JSON Schema subset: type/required/properties/items)
    # ------------------------------------------------------------------

    def validate_schema(self, schema: dict) -> List[str]:
        """簡易スキーマ検証。エラーメッセージのリストを返す（空なら合格）。"""
        if self.current_config is None:
            self.load()
        return _validate_against_schema(self.current_config or {}, schema, path="")


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _deep_update(target: dict, source: dict) -> None:
    for k, v in source.items():
        if isinstance(v, dict) and isinstance(target.get(k), dict):
            _deep_update(target[k], v)
        else:
            target[k] = v


_TYPE_MAP: Dict[str, Any] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
    "null": type(None),
}


def _validate_against_schema(value: Any, schema: dict, path: str) -> List[str]:
    errors: List[str] = []
    expected_type = schema.get("type")
    if expected_type and expected_type in _TYPE_MAP:
        expected = _TYPE_MAP[expected_type]
        if not isinstance(value, expected):
            label = path or "(root)"
            errors.append(f"{label}: expected {expected_type}, got {type(value).__name__}")
            return errors

    if isinstance(value, dict):
        for req in schema.get("required", []):
            if req not in value:
                label = path or "(root)"
                errors.append(f"{label}.{req}: required field missing")
        for prop, sub_schema in schema.get("properties", {}).items():
            if prop in value:
                sub_path = f"{path}.{prop}" if path else prop
                errors.extend(_validate_against_schema(value[prop], sub_schema, sub_path))

    if isinstance(value, list):
        item_schema = schema.get("items")
        if item_schema:
            for i, item in enumerate(value):
                errors.extend(_validate_against_schema(item, item_schema, f"{path}[{i}]"))

    if isinstance(value, (int, float)):
        min_val = schema.get("minimum")
        max_val = schema.get("maximum")
        label = path or "(root)"
        if min_val is not None and value < min_val:
            errors.append(f"{label}: {value} < minimum {min_val}")
        if max_val is not None and value > max_val:
            errors.append(f"{label}: {value} > maximum {max_val}")

    if isinstance(value, str):
        min_len = schema.get("minLength")
        max_len = schema.get("maxLength")
        label = path or "(root)"
        if min_len is not None and len(value) < min_len:
            errors.append(f"{label}: length {len(value)} < minLength {min_len}")
        if max_len is not None and len(value) > max_len:
            errors.append(f"{label}: length {len(value)} > maxLength {max_len}")

    return errors


# ------------------------------------------------------------------
# Singleton
# ------------------------------------------------------------------

_enhanced_manager: Optional[EnhancedConfigManager] = None


def get_enhanced_config_manager(config_path: Optional[str] = None) -> EnhancedConfigManager:
    """EnhancedConfigManager のシングルトンを返す。"""
    global _enhanced_manager
    if _enhanced_manager is None:
        _enhanced_manager = EnhancedConfigManager(config_path=config_path)
    return _enhanced_manager


def reset_enhanced_config_manager() -> None:
    """テスト用: シングルトンをリセットする。"""
    global _enhanced_manager
    _enhanced_manager = None
