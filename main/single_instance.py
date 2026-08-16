"""
多重起動ガード — PID ロックファイルによる単一インスタンス化（依存なし・OS 非依存）。

GUI 本体（`satin_launcher.py` の既定モード）を 2 つ起動すると、両者が
`config/mood.json`・会話ログ・`user_profile.json` を並行して書き込み、状態が
破損しうる。起動時にロックファイルへ自分の PID を書き、既存ロックの PID が
生存していれば「既に起動中」として起動を拒否する。プロセスが異常終了して
残った stale ロック（PID が死んでいる）は自動的に奪取する。

ヘッドレスモード（--chat/--dashboard/--manage/--validate）は複数同時起動が
正当なのでロック対象外。
"""
from __future__ import annotations

import os
import tempfile
from typing import Callable, Optional


def _default_lock_path() -> str:
    """既定のロックファイル（config/satin.lock）。cwd 非依存。"""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "config", "satin.lock")


def _pid_alive(pid: int) -> bool:
    """PID のプロセスが生存しているかを返す（OS 非依存・best-effort）。"""
    if pid <= 0:
        return False
    if os.name == "nt":  # pragma: no cover - Windows 専用パス
        try:
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            # windll は Windows ビルドの ctypes にしか存在しないので、
            # 他プラットフォームで型検査すると attr-defined になる。実行は
            # os.name == "nt" でガード済み。
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid)
            if not handle:
                return False
            code = ctypes.c_ulong()
            ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            kernel32.CloseHandle(handle)
            return bool(ok) and code.value == STILL_ACTIVE
        except Exception:
            return False
    try:
        os.kill(pid, 0)  # シグナル 0 = 存在確認（送信はしない）
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # 他ユーザーのプロセスだが存在はする
    except OSError:
        return False
    return True


def _read_pid(path: str) -> Optional[int]:
    """ロックファイルから PID を読む。無い/壊れていれば None。"""
    try:
        with open(path, encoding="utf-8") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def _write_pid_atomic(path: str, pid: int) -> None:
    """PID をロックファイルへアトミックに書き込む。"""
    _dir = os.path.dirname(path) or "."
    os.makedirs(_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(str(pid))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class SingleInstance:
    """PID ロックファイルによる単一インスタンスガード。

    pid / is_alive を注入可能にしてあり、単一プロセスのテストでも「別の生存
    インスタンスがロックを保持している」状況を再現できる。
    """

    def __init__(self, lock_path: Optional[str] = None,
                 pid: Optional[int] = None,
                 is_alive: Optional[Callable[[int], bool]] = None) -> None:
        self.lock_path = lock_path or _default_lock_path()
        self._pid = pid if pid is not None else os.getpid()
        self._is_alive = is_alive if is_alive is not None else _pid_alive
        self.acquired = False

    def acquire(self) -> bool:
        """ロックを取得できたら True。別の生存インスタンスが保持中なら False。"""
        existing = _read_pid(self.lock_path)
        if (existing is not None and existing != self._pid
                and self._is_alive(existing)):
            return False
        _write_pid_atomic(self.lock_path, self._pid)
        self.acquired = True
        return True

    def release(self) -> None:
        """自分が保持しているロックのみ解放する（他者のロックは消さない）。"""
        if not self.acquired:
            return
        if _read_pid(self.lock_path) == self._pid:
            try:
                os.remove(self.lock_path)
            except OSError:
                pass
        self.acquired = False

    def __enter__(self) -> "SingleInstance":
        return self

    def __exit__(self, *exc) -> None:
        self.release()
