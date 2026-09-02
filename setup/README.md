# Satin — インストール

Satin はローカル完結・オフラインのデスクトップ 3D アバターコンパニオンです。
製品全体の説明は[リポジトリ root の README](../README.md) を参照してください。

このディレクトリにはインストールに必要なものだけが入っています。

| ファイル | 用途 |
|---|---|
| `requirements.txt` | Python 依存パッケージ（全 OS 共通） |
| `win/setup.bat` | Windows 用セットアップ（[手順](win/README_WIN.md)） |
| `mac/setup.sh` | macOS / Linux 用セットアップ（[手順](mac/README_MAC.md)） |
| `github-actions-ci.yml` | CI ワークフロー定義（有効化は所有者が手動で行う。ファイル冒頭を参照） |

## 検証を push 前に自動で走らせる

CI が有効化されるまでの間（および有効化後も一段目の防波堤として）、
リポジトリ同梱の pre-push フックを有効にできます。クローンごとに 1 回:

```bash
git config core.hooksPath .githooks
```

以後 `git push` のたびに `python check.py` が走り、赤なら push を中止します
（飛ばしたいときは `SATIN_SKIP_CHECK=1 git push` か `git push --no-verify`）。

## 自動セットアップ

リポジトリ root から実行します。スクリプトは自身の位置からリポジトリルートを
解決するので、どこから呼んでも構いません。

```bash
# Windows
setup\win\setup.bat

# macOS / Linux
chmod +x setup/mac/setup.sh
./setup/mac/setup.sh
```

いずれも pip を更新し、`setup/requirements.txt` を導入します。

## 手動セットアップ

スクリプトを使わない場合はこれだけです。

```bash
pip install -r setup/requirements.txt
```

## 起動

セットアップスクリプトとは**別のディレクトリ**にあります（`launch/`）。

```bash
# Windows
launch\win\run_satin.bat

# macOS / Linux
./launch/mac/run_satin.sh

# あるいは直接
python satin_launcher.py
```

## 動作確認

```bash
python satin_launcher.py --version
python check.py               # 全検証（テスト・lint・型・起動スモーク）
```

`check.py` は個人データ（好感度・会話履歴）を書き換えないので、
インストール直後の確認に使っても安全です。
