# Satin for macOS / Linux

パスはすべて**リポジトリ root からの相対**です。セットアップと起動は
別のディレクトリにある点に注意してください（`setup/` と `launch/`）。

## 1. 前提条件

- macOS 10.15 (Catalina) 以降、または一般的な Linux ディストリビューション
- Python 3.10 以降を推奨（CI が検証しているのは 3.10 / 3.11 / 3.12。
  構文上は 3.8 でも読めますが、その組み合わせは検証していません）

macOS で Python が入っていない場合:

```bash
xcode-select --install
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install python
```

## 2. セットアップ

```bash
chmod +x setup/mac/setup.sh
./setup/mac/setup.sh
```

スクリプトは自身の位置からリポジトリルートを解決するので、どこから呼んでも
同じ結果になります。実行内容は pip の更新と `setup/requirements.txt` の
インストール、それに `launch/mac/run_satin.sh` への実行権限付与だけです。
仮想環境は作らないので、venv を使いたい場合は先に有効化してから実行して
ください。

## 3. 起動

```bash
./launch/mac/run_satin.sh
```

`setup/mac/` ではなく `launch/mac/` にあります。直接起動することもできます。

```bash
python3 satin_launcher.py
```

## トラブルシューティング

### 依存関係のインストールに失敗する

```bash
python3 -m pip install --upgrade pip
pip3 install -r setup/requirements.txt
```

`PyQt5` / `PyOpenGL` の導入に失敗しても、対話 CLI
（`python3 satin_launcher.py --chat`）と Web ダッシュボードは動きます。
3D アバター GUI だけが使えません。

### パーミッションエラー

```bash
chmod +x setup/mac/setup.sh launch/mac/run_satin.sh
```

### 起動しない

```bash
python3 satin_launcher.py --version   # ここが通らなければ Python 側の問題
python3 check.py                       # 何が壊れているかを一括で表示
```

Satin はログファイルを作りません。エラーはターミナルにそのまま出ます。

## アンインストール

Satin はリポジトリの外に何も書きません。ディレクトリごと削除すれば完了です。
導入した Python パッケージも消したい場合:

```bash
pip3 uninstall -r setup/requirements.txt -y
```
