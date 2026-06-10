"""
バッチ設定ファイル操作の共有ユーティリティ。

comment_manager_batch / overlay_manager_batch / tts_manager_batch が
全く同一の validate + backup ロジックを重複して持っていたため共通化した。
各モジュールはこのモジュールを呼ぶ薄いラッパーになる。
"""
from __future__ import annotations

import datetime
import glob
import json
import os
import zipfile
from typing import List

from utils_batch import batch_process
from utils_profile import log_error, log_info


def validate_configs(
    search_dir: str,
    glob_pattern: str,
    required_keys: List[str],
    desc: str,
    error_summary: str,
    ok_message: str,
) -> List[str]:
    """設定ファイル群をバリデーションして、エラー文字列のリストを返す。

    エラーがなければ ok_message をログ出力し空リストを返す。
    """
    files = glob.glob(os.path.join(search_dir, glob_pattern))

    def validate_one(fname: str):
        try:
            with open(fname, encoding="utf-8") as f:
                data = json.load(f)
            for k in required_keys:
                if k not in data:
                    log_error(f"[WARN] {fname}: '{k}' 未設定")
                    return f"{fname}: '{k}' 未設定"
            return None
        except Exception as e:
            log_error(f"[ERROR] {fname} 読み込み失敗: {e}")
            return f"{fname}: 読み込み失敗: {e}"

    results = batch_process(validate_one, files, desc=desc)
    errors = [r for r in results if r]
    if errors:
        for e in errors:
            print(e)
        log_error(error_summary)
    else:
        log_info(ok_message)
    return errors


def backup_configs(
    search_dir: str,
    glob_pattern: str,
    zip_prefix: str,
    ok_message_template: str,
    error_prefix: str,
) -> None:
    """設定ファイル群を ZIP アーカイブへ一括バックアップする。

    zipfile.ZipFile はスレッドセーフでないため逐次書き込みする。
    """
    files = glob.glob(os.path.join(search_dir, glob_pattern))
    now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    zipname = f"{zip_prefix}_{now}.zip"
    try:
        with zipfile.ZipFile(zipname, "w", zipfile.ZIP_DEFLATED) as zf:
            for fname in files:
                zf.write(fname, arcname=os.path.basename(fname))
        log_info(ok_message_template.format(zipname=zipname))
    except Exception as e:
        log_error(f"[ERROR] {error_prefix}: {e}")
