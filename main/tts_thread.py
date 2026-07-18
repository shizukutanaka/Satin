"""
共有 TTSThread — pyttsx3 でキュー内テキストを読み上げるワーカースレッド。

avatar_3d_autonomous_tts / avatar_3d_mic_tts_modes が同一実装を重複して
持っていたため一本化した。pyttsx3 未インストール時は即座に返る(no-op)。
is_speaking は読み上げ中フラグ（口パク同期などに利用可能）。
"""
from __future__ import annotations

import logging
import queue
import threading

from optional_deps import pyttsx3

logger = logging.getLogger(__name__)


def _init_engine():
    """pyttsx3 エンジンを初期化する。不可なら None（無音フォールバック）。

    pyttsx3 が未インストールなら None。インストール済みでも、音声ドライバや
    音声データが無い環境（espeak 未導入の Linux、SAPI ボイスの無い Windows 等）
    では pyttsx3.init() が例外を投げる。TTS はあくまで任意機能なので、その失敗で
    アプリ全体（3D GUI 起動）を巻き込まないよう握りつぶして無音動作にする。
    """
    if pyttsx3 is None:
        return None
    try:
        return pyttsx3.init()
    except Exception as e:  # pragma: no cover - environment-specific
        logger.warning("TTS エンジンの初期化に失敗しました（無音で継続）: %s", e)
        return None


class TTSThread(threading.Thread):
    def __init__(self, tts_queue: "queue.Queue") -> None:
        super().__init__()
        self.tts_queue = tts_queue
        self.engine = _init_engine()
        self.daemon = True
        self.running = True
        self.is_speaking = False

    def run(self) -> None:
        if self.engine is None:
            return
        while self.running:
            try:
                text = self.tts_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if text:
                self.is_speaking = True
                try:
                    self.engine.say(text)
                    self.engine.runAndWait()
                except Exception:
                    pass
                finally:
                    self.is_speaking = False

    def stop(self) -> None:
        self.running = False
