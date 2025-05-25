import os
import glob
import json
import shutil
import datetime
from utils_profile import profile_time, log_info, log_error

VERSIONS_DIR = "config_versions"

@profile_time
def save_config_version(config_path="config.json"):
    """
    config.jsonのスナップショットをバージョン管理ディレクトリに保存
    """
    if not os.path.exists(config_path):
        log_error(f"{config_path} が見つかりません")
        return
    os.makedirs(VERSIONS_DIR, exist_ok=True)
    now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    base = os.path.basename(config_path)
    dest = os.path.join(VERSIONS_DIR, f"{base}.{now}.bak")
    shutil.copy2(config_path, dest)
    log_info(f"{config_path} のバージョンを {dest} として保存")

@profile_time
def list_config_versions(config_path="config.json"):
    """
    config.jsonのバージョン一覧を表示
    """
    base = os.path.basename(config_path)
    pattern = os.path.join(VERSIONS_DIR, f"{base}.*.bak")
    files = sorted(glob.glob(pattern))
    for f in files:
        print(f)
    log_info(f"{len(files)}件のバージョンを検出")
    return files

@profile_time
def restore_config_version(version_file, config_path="config.json"):
    """
    指定したバージョンファイルからconfig.jsonを復元
    """
    if not os.path.exists(version_file):
        log_error(f"{version_file} が見つかりません")
        return
    shutil.copy2(version_file, config_path)
    log_info(f"{version_file} から {config_path} を復元")

if __name__ == "__main__":
    print("[INFO] 設定ファイル バージョン管理ツール")
    ans = input("現在のconfig.jsonをバージョン保存しますか？ [y/N]: ")
    if ans.lower() == "y":
        save_config_version()
    ans2 = input("バージョン一覧を表示しますか？ [y/N]: ")
    if ans2.lower() == "y":
        files = list_config_versions()
        if files:
            idx = input(f"復元したい番号を指定(0-{len(files)-1}) またはEnterでスキップ: ")
            if idx.isdigit() and 0 <= int(idx) < len(files):
                restore_config_version(files[int(idx)])
