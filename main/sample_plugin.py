# サンプルプラグイン: 起動時とプリセットロード時にメッセージを出す
# 他のプラグイン作成時はこのファイルをコピーして利用してください。
from typing import Dict, Any

def on_startup() -> None:
    """起動時に呼ばれるフック"""
    print("[PLUGIN] サンプルプラグインが起動しました")

def on_preset_load(preset: Dict[str, Any]) -> None:
    """プリセットロード時に呼ばれるフック
    :param preset: プリセット情報の辞書
    """
    if not isinstance(preset, dict):
        print("[PLUGIN] [WARN] presetがdict型ではありません")
        return
    print(f"[PLUGIN] プリセットがロードされました: {preset.get('name', 'unknown')}")
