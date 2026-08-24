# Satin for Windows

パスはすべて**リポジトリ root からの相対**です。セットアップと起動は
別のディレクトリにある点に注意してください（`setup\` と `launch\`）。

## 1. 前提条件

- Windows 10 以降
- Python 3.10 以降を推奨（CI が検証しているのは 3.10 / 3.11 / 3.12。
  構文上は 3.8 でも読めますが、その組み合わせは検証していません）
- インストール時に「Add Python to PATH」にチェックが入っていること

## 2. セットアップ

`setup\win\setup.bat` をダブルクリック、またはコマンドプロンプトから実行します。

```
setup\win\setup.bat
```

スクリプトは自身の位置からリポジトリルートを解決するので、どこから呼んでも
同じ結果になります。実行内容は pip の更新と `setup\requirements.txt` の
インストールだけで、システムには何も書き込みません。

管理者権限は**必須ではありません**。UAC が出たら「はい」で構いませんが、
拒否しても通常はそのまま完了します。

## 3. 起動

```
launch\win\run_satin.bat
```

`setup\win\` ではなく `launch\win\` にあります。直接起動することもできます。

```
python satin_launcher.py
```

## トラブルシューティング

### セットアップに失敗する

pip の導入だけ手動でやり直してください。

```
python -m pip install --upgrade pip
pip install -r setup\requirements.txt
```

`PyQt5` / `PyOpenGL` の導入に失敗しても、対話 CLI
（`python satin_launcher.py --chat`）と Web ダッシュボードは動きます。
3D アバター GUI だけが使えません。

### 起動しない

```
python satin_launcher.py --version    # ここが通らなければ Python 側の問題
python check.py                        # 何が壊れているかを一括で表示
```

Satin はログファイルを作りません。エラーはコンソールにそのまま出ます。

## アンインストール

Satin はリポジトリの外に何も書きません。フォルダごと削除すれば完了です。
導入した Python パッケージも消したい場合:

```
pip uninstall -r setup\requirements.txt -y
```
