"""
バックアップ管理のコマンドラインインターフェース
"""
import os
import sys
import json
import logging
import argparse
from typing import Optional
from backup_manager import get_backup_manager
from config_manager import get_config_manager

logger = logging.getLogger(__name__)

def create_backup(args):
    """バックアップを作成"""
    try:
        backup_manager = get_backup_manager()
        backup_path = backup_manager.create_backup(
            args.target_dir,
            args.backup_name
        )
        print(f"バックアップを作成しました: {backup_path}")
        return 0
    except Exception as e:
        logger.error(f"バックアップの作成に失敗しました: {e}")
        return 1

def list_backups(args):
    """バックアップの一覧を表示"""
    try:
        backup_manager = get_backup_manager()
        backups = backup_manager.list_backups()
        
        if not backups:
            print("バックアップが見つかりません")
            return 0
        
        print("バックアップ一覧:")
        print("-" * 80)
        print(f"{'名前':<30} {'サイズ':>10} {'作成日時':<20} {'状態':<10}")
        print("-" * 80)
        
        for backup in backups:
            size_mb = f"{backup['size'] / (1024 * 1024):.2f} MB"
            status = "有効" if backup['is_valid'] else "無効"
            print(f"{backup['name']:<30} {size_mb:>10} {backup['created']:<20} {status:<10}")
        
        return 0
    except Exception as e:
        logger.error(f"バックアップの一覧表示に失敗しました: {e}")
        return 1

def restore_backup(args):
    """バックアップから復元"""
    try:
        backup_manager = get_backup_manager()
        success = backup_manager.restore_backup(
            args.backup_file,
            args.target_dir
        )
        
        if success:
            print(f"バックアップを復元しました: {args.backup_file}")
            return 0
        else:
            print("バックアップの復元に失敗しました")
            return 1
    except Exception as e:
        logger.error(f"バックアップの復元に失敗しました: {e}")
        return 1

def delete_backup(args):
    """バックアップを削除"""
    try:
        backup_manager = get_backup_manager()
        success = backup_manager.delete_backup(args.backup_file)
        
        if success:
            print(f"バックアップを削除しました: {args.backup_file}")
            return 0
        else:
            print("バックアップの削除に失敗しました")
            return 1
    except Exception as e:
        logger.error(f"バックアップの削除に失敗しました: {e}")
        return 1

def main():
    """メイン関数"""
    parser = argparse.ArgumentParser(description="Satinバックアップ管理ツール")
    subparsers = parser.add_subparsers(title="コマンド")
    
    # バックアップ作成コマンド
    create_parser = subparsers.add_parser("create", help="バックアップを作成")
    create_parser.add_argument("target_dir", help="バックアップ対象のディレクトリ")
    create_parser.add_argument("--backup-name", help="バックアップ名（指定なしの場合、日時を含む名前を使用）")
    create_parser.set_defaults(func=create_backup)
    
    # バックアップ一覧表示コマンド
    list_parser = subparsers.add_parser("list", help="バックアップの一覧を表示")
    list_parser.set_defaults(func=list_backups)
    
    # バックアップ復元コマンド
    restore_parser = subparsers.add_parser("restore", help="バックアップから復元")
    restore_parser.add_argument("backup_file", help="復元するバックアップファイル")
    restore_parser.add_argument("target_dir", help="復元先ディレクトリ")
    restore_parser.set_defaults(func=restore_backup)
    
    # バックアップ削除コマンド
    delete_parser = subparsers.add_parser("delete", help="バックアップを削除")
    delete_parser.add_argument("backup_file", help="削除するバックアップファイル")
    delete_parser.set_defaults(func=delete_backup)
    
    args = parser.parse_args()
    
    if not hasattr(args, 'func'):
        parser.print_help()
        return 1
    
    return args.func(args)

if __name__ == "__main__":
    sys.exit(main())
