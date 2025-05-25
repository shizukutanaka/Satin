# Satin for macOS

## セットアップ手順

### 1. 前提条件
- macOS 10.15 (Catalina) 以降
- Python 3.8 以降（Homebrew推奨）
- コマンドラインツール（Xcode Command Line Tools）

### 2. コマンドラインツールのインストール

ターミナルを開き、以下のコマンドを実行：

```bash
xcode-select --install
```

### 3. Homebrewのインストール（未インストールの場合）

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

### 4. Pythonのインストール（未インストールの場合）

```bash
brew install python
```

### 5. Satinのセットアップ

1. ターミナルでSatinのディレクトリに移動：
   ```bash
   cd /path/to/Satin
   ```

2. セットアップスクリプトに実行権限を付与：
   ```bash
   chmod +x mac/setup.sh
   ```

3. セットアップを実行：
   ```bash
   ./mac/setup.sh
   ```

## 起動方法

```bash
./mac/run_satin.sh
```

## トラブルシューティング

### セキュリティ警告が表示される場合

1. システム環境設定 > セキュリティとプライバシー を開く
2. 「一般」タブで「開く」ボタンをクリック

### パーミッションエラーが発生する場合

```bash
chmod +x mac/*.sh
```

### 依存関係のインストールに失敗する場合

```bash
python3 -m pip install --upgrade pip
pip3 install -r requirements.txt
```

## アンインストール

1. 仮想環境を削除：
   ```bash
   rm -rf venv
   ```
2. インストールしたパッケージを削除：
   ```bash
   pip3 uninstall -r requirements.txt -y
   ```

## サポート

問題が解決しない場合は、以下の情報を添えてサポートチケットを作成してください：
- エラーメッセージ全体
- 実行したコマンド
- 環境情報（`sw_vers` と `python3 --version` の出力）
