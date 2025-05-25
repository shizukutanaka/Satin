import json
import time
import threading
from datetime import datetime

class AvatarEventLogger:
    def __init__(self, logfile="avatar_event_log.jsonl"):
        self.logfile = logfile
        self.lock = threading.Lock()

    def log_event(self, event_type, **kwargs):
        event = {
            "timestamp": time.time(),
            "event_type": event_type,
            "details": kwargs
        }
        with self.lock, open(self.logfile, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def replay_events(self, callback, delay_factor=1.0):
        """
        callback(event)でイベントを再生
        delay_factor=1.0で実時間通り、<1.0で高速再生
        """
        with open(self.logfile, encoding="utf-8") as f:
            events = [json.loads(line) for line in f if line.strip()]
        if not events:
            return
        base = events[0]["timestamp"]
        for i, event in enumerate(events):
            t = event["timestamp"]
            if i > 0:
                dt = (t - events[i-1]["timestamp"]) * delay_factor
                if dt > 0:
                    time.sleep(dt)
            callback(event)

# サンプル利用例
if __name__ == "__main__":
    logger = AvatarEventLogger()
    # イベント記録例
    logger.log_event("move", x=1.0, y=0.5, mode="autonomous")
    logger.log_event("speak", text="こんにちは！", tts=True)
    logger.log_event("mouth", open=0.8, by="mic")
    logger.log_event("mode_change", mode="camera_tracking")
    print("イベントを記録しました。リプレイします↓")
    def print_event(ev):
        ts = datetime.fromtimestamp(ev["timestamp"]).strftime("%H:%M:%S.%f")
        print(f"[{ts}] {ev['event_type']}: {ev['details']}")
    logger.replay_events(print_event, delay_factor=0.5)
