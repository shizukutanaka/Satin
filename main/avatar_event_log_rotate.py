import os
import re
import time
import gzip
import shutil
from datetime import datetime
import argparse


def _backup_sort_key(fname: str) -> tuple:
    """ファイル名内のタイムスタンプでソートする。復元後に mtime が変わっても正しい順序。"""
    m = re.search(r"\.(\d{8}_\d{6})\.gz$", fname)
    if m:
        return (0, m.group(1))
    return (1, fname)


def rotate_log(logfile, max_size=5*1024*1024, max_backups=5, quiet=False):
    if not os.path.exists(logfile):
        return
    size = os.path.getsize(logfile)
    if size < max_size:
        return
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    rotated = f"{logfile}.{ts}.gz"
    # アーカイブ書き込みが失敗した場合でもライブログを失わないように、
    # 成功後にのみライブログを空にする（失敗時は中途半端なアーカイブを削除）。
    try:
        with open(logfile, 'rb') as f_in, gzip.open(rotated, 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)
    except Exception:
        try:
            os.remove(rotated)
        except OSError:
            pass
        raise
    # アーカイブを所有者のみ読み書き可に制限（会話ログは個人情報）
    try:
        from fsutil import restrict_to_owner
        restrict_to_owner(rotated)
    except Exception:
        pass
    with open(logfile, 'w', encoding='utf-8') as f:
        pass  # 空ファイルで再作成
    # 古いバックアップ削除（ファイル名内タイムスタンプ順 — mtime 非依存）
    log_dir = os.path.dirname(os.path.abspath(logfile))
    backups = sorted(
        [f for f in os.listdir(log_dir)
         if f.startswith(os.path.basename(logfile) + '.') and f.endswith('.gz')],
        key=_backup_sort_key,
    )
    # max_backups=0 means keep none; list[:-0] == list[:0] == [] so guard explicitly.
    to_remove = backups[:-max_backups] if max_backups > 0 else backups
    for old in to_remove:
        try:
            os.remove(os.path.join(log_dir, old))
        except Exception:
            pass
    if not quiet:
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
