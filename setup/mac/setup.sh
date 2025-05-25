#!/bin/bash
# ====================================
# Satin セットアップスクリプト (macOS版)
# 最終更新: 2025-05-24
# ====================================

# 管理者権限の確認
if [ "$(id -u)" -ne 0 ]; then
    echo "管理者権限が必要な場合があります。"
    echo "セットアップを続行しますが、問題が発生した場合は 'sudo' を付けて実行してください。"
fi

# Pythonの存在確認
if ! command -v python3 &> /dev/null; then
    echo "エラー: Python3がインストールされていません。"
    echo "Homebrewを使用してインストールするには以下のコマンドを実行してください："
    echo "  /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
    echo "  brew install python"
    exit 1
fi

# pipのアップグレード
echo "pipをアップグレードしています..."
python3 -m pip install --upgrade pip
if [ $? -ne 0 ]; then
    echo "エラー: pipのアップグレードに失敗しました。"
    exit 1
fi

# 必要なパッケージのインストール
echo "必要なパッケージをインストールしています..."
pip3 install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "エラー: 依存関係のインストールに失敗しました。"
    exit 1
fi

# 実行権限の付与
chmod +x run_satin.sh

# 完了メッセージ
echo
echo "===================================="
echo "Satinのセットアップが完了しました！"
echo "以下のコマンドで起動できます："
echo "./run_satin.sh"
echo "===================================="
echo ""

# ユーザーに確認を求める
read -p "Satinを今すぐ起動しますか？ (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    ./run_satin.sh
fi
