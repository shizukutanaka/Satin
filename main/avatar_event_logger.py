import json
import time
import threading
from datetime import datetime

class AvatarEventLogger:
    def __init__(self, logfile="avatar_event_log.jsonl",
                 max_size=5 * 1024 * 1024, max_backups=5):
        self.logfile = logfile
        # 無制限増大を防ぐためのサイズ上限。max_size=0 で自動ローテーション無効。
        # コンパニオンは履歴を貯め続けるので、書き込み経路で自己上限化しないと
        # ディスクが膨張し、全リーダー（毎回ファイル全走査）も線形に遅くなる。
        self.max_size = max_size
        self.max_backups = max_backups
        self.lock = threading.Lock()

    def log_event(self, event_type, **kwargs):
        event = {
            "timestamp": time.time(),
            "event_type": event_type,
            "details": kwargs
        }
        with self.lock:
            with open(self.logfile, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
            # 上限超過時に gzip ローテート。ローテーション失敗はログ記録自体を
            # 壊さないよう握りつぶす（記録の堅牢性を最優先）。
            if self.max_size:
                try:
                    from avatar_event_log_rotate import rotate_log
                    rotate_log(self.logfile, self.max_size, self.max_backups,
                               quiet=True)
                except Exception:
                    pass

    def replay_events(self, callback, delay_factor=1.0):
        """
        callback(event)でイベントを再生
        delay_factor=1.0で実時間通り、<1.0で高速再生
        """
        events = []
        with open(self.logfile, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    # 壊れた行（クラッシュで途中まで書かれた等）はスキップ
                    continue
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
