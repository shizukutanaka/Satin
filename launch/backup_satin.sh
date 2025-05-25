#!/bin/bash
# ====================================
# Satin バックアップ管理ツール (macOS版)
# 最終更新: 2025-05-25
# ====================================

# 管理者権限の確認
if [ "$(id -u)" -ne 0 ]; then
    echo "管理者権限が必要な場合があります。"
fi

# Pythonの存在確認
if ! command -v python3 &> /dev/null; then
    echo "エラー: Python3がインストールされていません。"
    echo "Homebrewを使用してインストールするには以下のコマンドを実行してください："
    echo "  /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
    echo "  brew install python"
    exit 1
fi

# 仮想環境の有効化 (存在する場合)
if [ -f "venv/bin/activate" ]; then
    source "venv/bin/activate"
fi

# メインスクリプトの実行
echo "Satin バックアップ管理ツールを起動しています..."
python3 backup_cli.py "$@"

# エラー時の処理
if [ $? -ne 0 ]; then
    echo "エラーが発生しました。終了コード: $?"
    read -p "続行するにはEnterキーを押してください..."
    exit $?
fi

read -p "続行するにはEnterキーを押してください..."
