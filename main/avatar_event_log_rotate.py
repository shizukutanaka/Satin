"""イベントログのサイズローテーション。

`AvatarEventLogger` が書き込みのたびに `rotate_log()` を呼ぶ。ローテート後の
アーカイブは ``<logfile>.<YYYYMMDD_HHMMSS>.gz`` で、`conversation_log` の
検索と `log_retention` の期限切れ削除がこの命名を前提にしている。

**常駐監視デーモンは置かない。** 以前は `monitor_and_rotate()` と `main()` が
あり、ログファイルを 30 秒ごとにポーリングして必要ならローテートする独立
プロセスとして起動できた。どこからも呼ばれていなかったが、それ以上に危険で、
本体と同時に走らせると**同じファイルを 2 つのプロセスが回す**競合になる。
書き込み時にローテートする方式なら、そもそも監視する対象が無い。
"""
import os
import re
import gzip
import shutil
from datetime import datetime


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
