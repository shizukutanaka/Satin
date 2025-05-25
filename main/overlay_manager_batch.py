import glob
import os
import json
from utils_profile import profile_time, log_info, log_error
from utils_batch import batch_process

@profile_time
def batch_validate_overlays(overlay_dir="."):
    """
    overlay設定ファイル(overlay_*.json)のバリデーションを並列実行＋進捗バー＋ログ
    """
    files = glob.glob(os.path.join(overlay_dir, "overlay_*.json"))
    def validate_one(fname):
        try:
            with open(fname, encoding="utf-8") as f:
                data = json.load(f)
            # 例: 必須キーの確認
            required = ["overlay_type", "enabled"]
            for k in required:
                if k not in data:
                    log_error(f"[WARN] {fname}: '{k}' 未設定")
                    return f"{fname}: '{k}' 未設定"
            return None
        except Exception as e:
            log_error(f"[ERROR] {fname} 読み込み失敗: {e}")
            return f"{fname}: 読み込み失敗: {e}"
    results = batch_process(validate_one, files, desc="オーバーレイ設定バリデーション中")
    errors = [r for r in results if r]
    if errors:
        for e in errors:
            print(e)
        log_error("オーバーレイ設定ファイルバリデーションエラーあり")
    else:
        log_info("全オーバーレイ設定ファイルが正常です")

@profile_time
def batch_backup_overlays(overlay_dir="."):
    """
    オーバーレイ設定ファイルを一括バックアップ(zip化)＋進捗表示
    """
    import zipfile, datetime
    files = glob.glob(os.path.join(overlay_dir, "overlay_*.json"))
    now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    zipname = f"satin_overlays_backup_{now}.zip"
    try:
        with zipfile.ZipFile(zipname, 'w', zipfile.ZIP_DEFLATED) as zf:
            def add_file(fname):
                zf.write(fname)
                return fname
            batch_process(add_file, files, desc="オーバーレイバックアップ中")
        log_info(f"オーバーレイ設定ファイルを {zipname} にバックアップしました")
    except Exception as e:
        log_error(f"[ERROR] オーバーレイバックアップ失敗: {e}")

if __name__ == "__main__":
    print("[INFO] オーバーレイ管理バッチツール")
    ans = input("全オーバーレイ設定ファイルのバリデーションを実行しますか？ [y/N]: ")
    if ans.lower() == "y":
        batch_validate_overlays()
    ans2 = input("全オーバーレイ設定ファイルをバックアップ(zip)しますか？ [y/N]: ")
    if ans2.lower() == "y":
        batch_backup_overlays()
