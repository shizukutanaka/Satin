import os
import json
import sys
from datetime import datetime

SUPPORTED_EXTS = [".vrm", ".fbx", ".glb", ".gltf"]

# 簡易メタデータ抽出: ファイル名・拡張子・サイズ・更新日時・パス

def extract_metadata(path):
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    ext = os.path.splitext(path)[1].lower()
    if ext not in SUPPORTED_EXTS:
        raise ValueError(f"未対応拡張子: {ext}")
    stat = os.stat(path)
    meta = {
        "filename": os.path.basename(path),
        "ext": ext,
        "size_bytes": stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "path": os.path.abspath(path)
    }
    # VRM/GLTF/FBXなどは今後ここで詳細メタデータ抽出可（例: VRM: title, author, version）
    return meta

def save_metadata(meta, out_path):
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使い方: python avatar_metadata_extractor.py <avatar_file>")
        sys.exit(1)
    meta = extract_metadata(sys.argv[1])
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    if len(sys.argv) >= 3:
        save_metadata(meta, sys.argv[2])
