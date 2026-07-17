from utils_profile import profile_time
from batch_config_utils import validate_configs, backup_configs

_GLOB = "comment_manager_*.json"
_REQUIRED = ["comment_source", "output_enabled"]


@profile_time
def batch_validate_comments(comment_dir="."):
    """comment_manager_*.json のバリデーションを並列実行＋進捗バー＋ログ"""
    validate_configs(
        search_dir=comment_dir,
        glob_pattern=_GLOB,
        required_keys=_REQUIRED,
        desc="コメント設定バリデーション中",
        error_summary="コメント設定ファイルバリデーションエラーあり",
        ok_message="全コメント設定ファイルが正常です",
    )


@profile_time
def batch_backup_comments(comment_dir="."):
    """コメント設定ファイルを一括バックアップ(zip化)＋進捗表示"""
    backup_configs(
        search_dir=comment_dir,
        glob_pattern=_GLOB,
        zip_prefix="satin_comments_backup",
        ok_message_template="コメント設定ファイルを {zipname} にバックアップしました",
        error_prefix="コメントバックアップ失敗",
    )


if __name__ == "__main__":
    print("[INFO] コメント管理バッチツール")
    ans = input("全コメント設定ファイルのバリデーションを実行しますか？ [y/N]: ")
    if ans.lower() == "y":
        batch_validate_comments()
    ans2 = input("全コメント設定ファイルをバックアップ(zip)しますか？ [y/N]: ")
    if ans2.lower() == "y":
        batch_backup_comments()
