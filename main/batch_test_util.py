import os
import glob
import json
import shutil
from utils_profile import profile_time, log_info, log_error
from utils_batch import batch_process

@profile_time
def generate_dummy_configs(target_dir="test_configs", kind="config", count=10, inject_invalid=False):
    """
    ダミー設定ファイル(config_*.json, comment_manager_*.json, tts_*.json, overlay_*.json)を一括生成
    inject_invalid=Trueで一部を不正値・キー欠損にして異常系テストも可能
    """
    import random
    os.makedirs(target_dir, exist_ok=True)
    def make_one(idx):
        fname = os.path.join(target_dir, f"{kind}_{idx:03d}.json")
        # 通常データ
        if kind == "config":
            data = {"stream_key": f"dummykey{idx}", "tts_enabled": bool(idx%2)}
            required = ["stream_key", "tts_enabled"]
        elif kind == "comment_manager":
            data = {"comment_source": f"source{idx}", "output_enabled": bool(idx%2)}
            required = ["comment_source", "output_enabled"]
        elif kind == "tts":
            data = {"voice_type": f"type{idx}", "enabled": bool(idx%2)}
            required = ["voice_type", "enabled"]
        elif kind == "overlay":
            data = {"overlay_type": f"type{idx}", "enabled": bool(idx%2)}
            required = ["overlay_type", "enabled"]
        else:
            data = {"dummy": idx}
            required = []
        # 異常系を混ぜる
        if inject_invalid and idx % 5 == 0:
            err_type = random.choice(["missing_key", "invalid_type"])
            if err_type == "missing_key" and required:
                # 必須キーを1つ消す
                del data[random.choice(required)]
            elif err_type == "invalid_type" and required:
                # 必須キーの型を不正化
                k = random.choice(required)
                data[k] = ["unexpected", 123] if isinstance(data[k], str) else "not_a_bool"
        with open(fname, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return fname
    batch_process(make_one, range(count), desc=f"{kind} ダミーファイル生成")
    log_info(f"{count}件の{kind}_*.jsonを{target_dir}に生成 (異常系: {inject_invalid})")

@profile_time
def cleanup_dummy_configs(target_dir="test_configs"):
    """
    ダミー設定ファイルディレクトリを一括削除
    """
    if os.path.exists(target_dir):
        shutil.rmtree(target_dir)
        log_info(f"{target_dir}を削除しました")
    else:
        log_info(f"{target_dir}は存在しません")

import argparse

def main():
    parser = argparse.ArgumentParser(description="バッチテスト用ダミーデータ生成/削除ツール")
    subparsers = parser.add_subparsers(dest='command')

    gen_parser = subparsers.add_parser('generate', help='ダミー設定ファイルを生成')
    gen_parser.add_argument('--kind', choices=['config','comment_manager','tts','overlay'], default='config')
    gen_parser.add_argument('--count', type=int, default=10)
    gen_parser.add_argument('--invalid', action='store_true', help='異常系データ混入')
    gen_parser.add_argument('--dir', default='test_configs')

    del_parser = subparsers.add_parser('cleanup', help='ダミー設定ファイルを一括削除')
    del_parser.add_argument('--dir', default='test_configs')

    args = parser.parse_args()
    try:
        if args.command == 'generate':
            generate_dummy_configs(target_dir=args.dir, kind=args.kind, count=args.count, inject_invalid=args.invalid)
        elif args.command == 'cleanup':
            cleanup_dummy_configs(target_dir=args.dir)
        else:
            print("[INFO] 対話モードで起動します")
            ans = input("ダミー設定ファイルを生成しますか？ [y/N]: ")
            if ans.lower() == "y":
                kind = input("種類(config/comment_manager/tts/overlay): ") or "config"
                count = int(input("個数: ") or "10")
                inv = input("異常系データを混入しますか？ [y/N]: ").lower() == 'y'
                generate_dummy_configs(kind=kind, count=int(count), inject_invalid=inv)
            ans2 = input("ダミー設定ファイルを一括削除しますか？ [y/N]: ")
            if ans2.lower() == "y":
                cleanup_dummy_configs()
    except Exception as e:
        log_error(f"バッチ処理中にエラー: {e}")

if __name__ == "__main__":
    main()
