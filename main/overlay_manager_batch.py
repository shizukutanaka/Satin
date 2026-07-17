from utils_profile import profile_time
from batch_config_utils import validate_configs, backup_configs

_GLOB = "overlay_*.json"
_REQUIRED = ["overlay_type", "enabled"]


@profile_time
def batch_validate_overlays(overlay_dir="."):
    """overlay_*.json のバリデーションを並列実行＋進捗バー＋ログ"""
    validate_configs(
        search_dir=overlay_dir,
        glob_pattern=_GLOB,
        required_keys=_REQUIRED,
        desc="オーバーレイ設定バリデーション中",
        error_summary="オーバーレイ設定ファイルバリデーションエラーあり",
        ok_message="全オーバーレイ設定ファイルが正常です",
    )


@profile_time
def batch_backup_overlays(overlay_dir="."):
    """オーバーレイ設定ファイルを一括バックアップ(zip化)＋進捗表示"""
    backup_configs(
        search_dir=overlay_dir,
        glob_pattern=_GLOB,
        zip_prefix="satin_overlays_backup",
        ok_message_template="オーバーレイ設定ファイルを {zipname} にバックアップしました",
        error_prefix="オーバーレイバックアップ失敗",
    )


if __name__ == "__main__":
    print("[INFO] オーバーレイ管理バッチツール")
    ans = input("全オーバーレイ設定ファイルのバリデーションを実行しますか？ [y/N]: ")
    if ans.lower() == "y":
        batch_validate_overlays()
    ans2 = input("全オーバーレイ設定ファイルをバックアップ(zip)しますか？ [y/N]: ")
    if ans2.lower() == "y":
        batch_backup_overlays()
