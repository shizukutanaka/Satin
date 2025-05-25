# Satin Backup Utility

Satinのバックアップ管理ユーティリティは、設定ファイルやデータのバックアップを作成、管理、復元するためのツールです。

## 主な機能

- 📦 自動バックアップの作成
- 📊 バックアップの一覧表示
- 🔄 バックアップからの復元
- 🗑️ バックアップの削除
- 🔄 設定の自動同期

## クイックスタート

### Windows
```cmd
# バックアップを作成
backup_satin.bat create "C:\Users\User\Documents\satin_data"

# バックアップの一覧を表示
backup_satin.bat list

# バックアップから復元
backup_satin.bat restore "backups\backup_20250525_121904.zip" "C:\Users\User\Documents\satin_data"

# バックアップを削除
backup_satin.bat delete "backups\backup_20250525_121904.zip"
```

### macOS/Linux
```bash
# バックアップを作成
./backup_satin.sh create "/Users/User/Documents/satin_data"

# バックアップの一覧を表示
./backup_satin.sh list

# バックアップから復元
./backup_satin.sh restore "backups/backup_20250525_121904.zip" "/Users/User/Documents/satin_data"

# バックアップを削除
./backup_satin.sh delete "backups/backup_20250525_121904.zip"
```

## バックアップの自動化

### Windowsタスクスケジューラー
1. タスクスケジューラーを開く
2. 新しいタスクを作成
3. トリガー: 一定時間ごと（例：毎日）
4. アクション: プログラムの実行
5. プログラム: `backup_satin.bat`
6. 引数: `create "C:\Users\User\Documents\satin_data"`

### macOS/Linux crontab
```bash
# 毎日午前2時にバックアップを作成
0 2 * * * /path/to/backup_satin.sh create "/Users/User/Documents/satin_data"
```

## トラブルシューティング

### バックアップが作成できない場合
1. 対象ディレクトリのアクセス権を確認
2. 保存先ディレクトリの空き容量を確認
3. Pythonのインストール状態を確認

### バックアップの復元に失敗する場合
1. バックアップファイルの有効性を確認
2. 復元先ディレクトリのアクセス権を確認
3. ログファイルを確認（`logs/satin_backup.log`）

## ログ

バックアップ操作のログは以下のファイルに記録されます：
- `logs/satin_backup.log`
- `logs/satin_profile.log`
