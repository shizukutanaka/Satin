import os
import glob
import json
from utils_profile import profile_time, log_info, log_error
from utils_batch import batch_process

@profile_time
def batch_validate_configs(config_dir="."):
    """
    config.jsonや各種設定ファイルのバリデーションを並列実行＋ログ記録
    """
    files = glob.glob(os.path.join(config_dir, "*.json"))
    def validate_one(fname):
        try:
            with open(fname, encoding="utf-8") as f:
                data = json.load(f)
            # 例: 必須キーの確認
            required = ["stream_key", "tts_enabled"]
            for k in required:
                if k not in data:
                    log_error(f"[WARN] {fname}: '{k}' 未設定")
                    return f"{fname}: '{k}' 未設定"
            return None
        except Exception as e:
            log_error(f"[ERROR] {fname} 読み込み失敗: {e}")
            return f"{fname}: 読み込み失敗: {e}"
    results = batch_process(validate_one, files, desc="設定バリデーション中")
    errors = [r for r in results if r]
    if errors:
        for e in errors:
            print(e)
        log_error("設定ファイルバリデーションエラーあり")
    else:
        log_info("全設定ファイルが正常です")

@profile_time
def batch_backup_configs(config_dir="."):
    """
    設定ファイルを一括バックアップ(zip化)＋進捗表示
    """
    import zipfile, datetime
    files = glob.glob(os.path.join(config_dir, "*.json"))
    now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    zipname = f"satin_configs_backup_{now}.zip"
    try:
        with zipfile.ZipFile(zipname, 'w', zipfile.ZIP_DEFLATED) as zf:
            def add_file(fname):
                zf.write(fname)
                return fname
            batch_process(add_file, files, desc="バックアップ中")
        log_info(f"設定ファイルを {zipname} にバックアップしました")
    except Exception as e:
        log_error(f"[ERROR] バックアップ失敗: {e}")

if __name__ == "__main__":
    print("[INFO] Satin管理バッチツール")
    ans = input("全設定ファイルのバリデーションを実行しますか？ [y/N]: ")
    if ans.lower() == "y":
        batch_validate_configs()
    ans2 = input("全設定ファイルをバックアップ(zip)しますか？ [y/N]: ")
    if ans2.lower() == "y":
        batch_backup_configs()
