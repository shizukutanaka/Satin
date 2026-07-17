from utils_profile import profile_time
from batch_config_utils import validate_configs, backup_configs

_GLOB = "tts_*.json"
_REQUIRED = ["voice_type", "enabled"]


@profile_time
def batch_validate_tts(tts_dir="."):
    """tts_*.json のバリデーションを並列実行＋進捗バー＋ログ"""
    validate_configs(
        search_dir=tts_dir,
        glob_pattern=_GLOB,
        required_keys=_REQUIRED,
        desc="TTS設定バリデーション中",
        error_summary="TTS設定ファイルバリデーションエラーあり",
        ok_message="全TTS設定ファイルが正常です",
    )


@profile_time
def batch_backup_tts(tts_dir="."):
    """TTS設定ファイルを一括バックアップ(zip化)＋進捗表示"""
    backup_configs(
        search_dir=tts_dir,
        glob_pattern=_GLOB,
        zip_prefix="satin_tts_backup",
        ok_message_template="TTS設定ファイルを {zipname} にバックアップしました",
        error_prefix="TTSバックアップ失敗",
    )


if __name__ == "__main__":
    print("[INFO] TTS管理バッチツール")
    ans = input("全TTS設定ファイルのバリデーションを実行しますか？ [y/N]: ")
    if ans.lower() == "y":
        batch_validate_tts()
    ans2 = input("全TTS設定ファイルをバックアップ(zip)しますか？ [y/N]: ")
    if ans2.lower() == "y":
        batch_backup_tts()
