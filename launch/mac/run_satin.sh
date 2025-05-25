#!/bin/bash
# ====================================
# Satin 起動用スクリプト (macOS版)
# 最終更新: 2025-05-24
# ====================================

# 管理者権限の確認
if [ "$(id -u)" -ne 0 ]; then
    echo "管理者権限が必要な場合があります。"
fi

# Pythonの存在確認
if ! command -v python3 &> /dev/null; then
    echo "エラー: Python3がインストールされていないか、パスが通っていません。"
    exit 1
fi

# 仮想環境の有効化 (存在する場合)
if [ -f "venv/bin/activate" ]; then
    source "venv/bin/activate"
fi

# メインスクリプトの実行
echo "Satinを起動しています..."
python3 satin_launcher.py

# エラー時の処理
if [ $? -ne 0 ]; then
    echo "エラーが発生しました。終了コード: $?"
    read -p "続行するにはEnterキーを押してください..."
    exit $?
fi

read -p "続行するにはEnterキーを押してください..."
