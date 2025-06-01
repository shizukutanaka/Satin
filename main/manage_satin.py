import os
import glob
import json

def validate_configs(config_dir="."):
    files = glob.glob(os.path.join(config_dir, "*.json"))
    required = ["stream_key", "tts_enabled"]
    errors = []
    for fname in files:
        try:
            with open(fname, encoding="utf-8") as f:
                data = json.load(f)
            for k in required:
                if k not in data:
                    msg = f"[WARN] {fname}: '{k}' 未設定"
                    print(msg)
                    errors.append(msg)
        except Exception as e:
            msg = f"[ERROR] {fname} 読み込み失敗: {e}"
            print(msg)
            errors.append(msg)
    if errors:
        print("設定ファイルバリデーションエラーあり")
    else:
        print("全設定ファイルが正常です")

if __name__ == "__main__":
    print("[INFO] Satin管理バッチツール (MVP版)")
    ans = input("全設定ファイルのバリデーションを実行しますか？ [y/N]: ")
    if ans.lower() == "y":
        validate_configs()
    else:
        print("キャンセルしました")
