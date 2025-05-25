import json
import argparse
from collections import Counter, defaultdict
from datetime import datetime
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import os

def load_events(logfile):
    events = []
    with open(logfile, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            events.append(json.loads(line))
    return events

def event_stats(events):
    event_types = [ev['event_type'] for ev in events]
    counts = Counter(event_types)
    times = [datetime.fromtimestamp(ev['timestamp']) for ev in events]
    by_hour = defaultdict(int)
    for t in times:
        by_hour[t.hour] += 1
    return counts, by_hour, times

def plot_stats(counts, by_hour, times, outdir):
    os.makedirs(outdir, exist_ok=True)
    # イベント種別ごと発生回数
    plt.figure(figsize=(6,4))
    plt.bar(counts.keys(), counts.values(), color='skyblue')
    plt.ylabel('回数')
    plt.title('イベント種別ごとの発生回数')
    plt.tight_layout()
    plt.savefig(os.path.join(outdir, 'event_counts.png'))
    plt.close()
    # 時間帯ヒートマップ
    hours = list(range(24))
    hour_counts = [by_hour.get(h,0) for h in hours]
    plt.figure(figsize=(7,3))
    plt.bar(hours, hour_counts, color='lightgreen')
    plt.xlabel('時')
    plt.ylabel('イベント数')
    plt.title('時間帯ごとのイベント発生数')
    plt.tight_layout()
    plt.savefig(os.path.join(outdir, 'event_by_hour.png'))
    plt.close()
    # タイムライン
    plt.figure(figsize=(8,2))
    plt.hist(times, bins=48, color='orange', rwidth=0.9)
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    plt.xlabel('時刻')
    plt.ylabel('イベント数')
    plt.title('イベントタイムライン')
    plt.tight_layout()
    plt.savefig(os.path.join(outdir, 'event_timeline.png'))
    plt.close()

def main():
    parser = argparse.ArgumentParser(description='アバターイベントログ自動レポート')
    parser.add_argument('logfile', help='イベントログファイル(jsonl)')
    parser.add_argument('--outdir', default='event_report', help='レポート出力先')
    args = parser.parse_args()
    events = load_events(args.logfile)
    counts, by_hour, times = event_stats(events)
    plot_stats(counts, by_hour, times, args.outdir)
    print(f'レポート画像を{args.outdir}に出力しました')

if __name__ == '__main__':
    main()
