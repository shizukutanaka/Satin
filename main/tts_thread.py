"""
共有 TTSThread — pyttsx3 でキュー内テキストを読み上げるワーカースレッド。

avatar_3d_autonomous_tts / avatar_3d_mic_tts_modes が同一実装を重複して
持っていたため一本化した。pyttsx3 未インストール時は即座に返る(no-op)。
is_speaking は読み上げ中フラグ（口パク同期などに利用可能）。
"""
from __future__ import annotations

import queue
import threading

from optional_deps import pyttsx3


class TTSThread(threading.Thread):
    def __init__(self, tts_queue: "queue.Queue") -> None:
        super().__init__()
        self.tts_queue = tts_queue
        self.engine = pyttsx3.init() if pyttsx3 is not None else None
        self.daemon = True
        self.running = True
        self.is_speaking = False

    def run(self) -> None:
        if self.engine is None:
            return
        while self.running:
            try:
                text = self.tts_queue.get(timeout=0.1)
                if text:
                    self.is_speaking = True
                    self.engine.say(text)
                    self.engine.runAndWait()
                    self.is_speaking = False
            except queue.Empty:
                continue

    def stop(self) -> None:
        self.running = False
