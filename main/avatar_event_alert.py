import time
import json
import requests
import argparse
from datetime import datetime

def send_slack_alert(webhook_url, message):
    payload = {"text": message}
    try:
        r = requests.post(webhook_url, json=payload, timeout=5)
        r.raise_for_status()
    except Exception as e:
        print(f"Slack通知失敗: {e}")

def monitor_log(logfile, webhook_url, poll_interval=5):
    print(f"監視開始: {logfile}")
    seen = set()
    while True:
        try:
            with open(logfile, encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    ev = json.loads(line)
                    key = (ev.get('timestamp'), ev.get('event_type'))
                    if key in seen:
                        continue
                    seen.add(key)
                    # 異常イベント検知例
                    if ev['event_type'] in ('error', 'tts_fail', 'disconnect'):
                        ts = datetime.fromtimestamp(ev['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
                        msg = f"[Satin異常検知] {ts} {ev['event_type']}\n詳細: {json.dumps(ev['details'], ensure_ascii=False)}"
                        send_slack_alert(webhook_url, msg)
        except Exception as e:
            print(f"監視エラー: {e}")
        time.sleep(poll_interval)

def main():
    parser = argparse.ArgumentParser(description='アバターイベントログ異常検知＆Slack通知')
    parser.add_argument('logfile', help='監視対象ログファイル')
    parser.add_argument('--slack', required=True, help='Slack Incoming Webhook URL')
    parser.add_argument('--interval', type=int, default=5, help='監視間隔(秒)')
    args = parser.parse_args()
    monitor_log(args.logfile, args.slack, args.interval)

if __name__ == '__main__':
    main()
