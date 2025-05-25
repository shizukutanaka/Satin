import glob
import os
import json
from utils_profile import profile_time, log_info, log_error
from utils_batch import batch_process

@profile_time
def batch_validate_comments(comment_dir="."):
    """
    comment_manager_*.pyやコメント用設定jsonのバリデーションを並列実行＋進捗バー＋ログ
    """
    files = glob.glob(os.path.join(comment_dir, "comment_manager_*.json"))
    def validate_one(fname):
        try:
            with open(fname, encoding="utf-8") as f:
                data = json.load(f)
            # 例: 必須キーの確認
            required = ["comment_source", "output_enabled"]
            for k in required:
                if k not in data:
                    log_error(f"[WARN] {fname}: '{k}' 未設定")
                    return f"{fname}: '{k}' 未設定"
            return None
        except Exception as e:
            log_error(f"[ERROR] {fname} 読み込み失敗: {e}")
            return f"{fname}: 読み込み失敗: {e}"
    results = batch_process(validate_one, files, desc="コメント設定バリデーション中")
    errors = [r for r in results if r]
    if errors:
        for e in errors:
            print(e)
        log_error("コメント設定ファイルバリデーションエラーあり")
    else:
        log_info("全コメント設定ファイルが正常です")

@profile_time
def batch_backup_comments(comment_dir="."):
    """
    コメント設定ファイルを一括バックアップ(zip化)＋進捗表示
    """
    import zipfile, datetime
    files = glob.glob(os.path.join(comment_dir, "comment_manager_*.json"))
    now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    zipname = f"satin_comments_backup_{now}.zip"
    try:
        with zipfile.ZipFile(zipname, 'w', zipfile.ZIP_DEFLATED) as zf:
            def add_file(fname):
                zf.write(fname)
                return fname
            batch_process(add_file, files, desc="コメントバックアップ中")
        log_info(f"コメント設定ファイルを {zipname} にバックアップしました")
    except Exception as e:
        log_error(f"[ERROR] コメントバックアップ失敗: {e}")

if __name__ == "__main__":
    print("[INFO] コメント管理バッチツール")
    ans = input("全コメント設定ファイルのバリデーションを実行しますか？ [y/N]: ")
    if ans.lower() == "y":
        batch_validate_comments()
    ans2 = input("全コメント設定ファイルをバックアップ(zip)しますか？ [y/N]: ")
    if ans2.lower() == "y":
        batch_backup_comments()
