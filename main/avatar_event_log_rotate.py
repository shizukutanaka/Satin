import os
import time
import gzip
import shutil
from datetime import datetime
import argparse

def rotate_log(logfile, max_size=5*1024*1024, max_backups=5):
    if not os.path.exists(logfile):
        return
    size = os.path.getsize(logfile)
    if size < max_size:
        return
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    rotated = f"{logfile}.{ts}.gz"
    with open(logfile, 'rb') as f_in, gzip.open(rotated, 'wb') as f_out:
        shutil.copyfileobj(f_in, f_out)
    with open(logfile, 'w', encoding='utf-8') as f:
        pass  # 空ファイルで再作成
    # 古いバックアップ削除
    backups = sorted([f for f in os.listdir('.') if f.startswith(os.path.basename(logfile)+'.') and f.endswith('.gz')])
    if len(backups) > max_backups:
        for old in backups[:-max_backups]:
            try:
                os.remove(old)
            except Exception:
                pass
    print(f"ログローテート: {rotated}")

def monitor_and_rotate(logfile, max_size, max_backups, interval):
    print(f"{logfile} を監視し、{max_size//1024}KB超でローテート 最大{max_backups}世代保存")
    while True:
        try:
            rotate_log(logfile, max_size, max_backups)
        except Exception as e:
            print(f"ローテートエラー: {e}")
        time.sleep(interval)

def main():
    parser = argparse.ArgumentParser(description='アバターイベントログ自動ローテーション')
    parser.add_argument('logfile', help='監視対象ログファイル')
    parser.add_argument('--max_size', type=int, default=5*1024*1024, help='最大サイズ(byte)')
    parser.add_argument('--max_backups', type=int, default=5, help='保存世代数')
    parser.add_argument('--interval', type=int, default=30, help='監視間隔(秒)')
    args = parser.parse_args()
    monitor_and_rotate(args.logfile, args.max_size, args.max_backups, args.interval)

if __name__ == '__main__':
    main()
