# Satin

<div align="center">
  <img src="https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-blue" alt="Platform">
  <img src="https://img.shields.io/badge/Python-3.8+-yellow" alt="Python 3.8+">
  <img src="https://img.shields.io/badge/License-MIT-green" alt="License: MIT">
</div>

**Satin** はVRChat配信・コメント管理・TTS・オーバーレイ専用の統合ツールです。

## 🌟 主な特徴

- 🎙️ VRChat配信向けコメント読み上げ・管理
- 🖥️ マルチプラットフォーム対応 (Windows/macOS/Linux)
- 🌐 マルチ言語対応 (日本語/English)
- 🎮 コメントオーバーレイ (Twitch/YouTube/Nico 対応)
- 🛠️ 配信補助機能・管理用GUI
- 🔄 自動バックアップ・復元機能

## 🚀 クイックスタート

### セットアップ方法

#### Windows ユーザー向け
1. `win` フォルダ内の `setup.bat` をダブルクリック
2. 管理者権限を求められたら「はい」を選択
3. セットアップ完了を待つ

#### macOS ユーザー向け
```bash
# 実行権限を付与
chmod +x mac/setup.sh

# セットアップを実行
./mac/setup.sh
```

### 起動方法

#### Windows
- `win` フォルダ内の `run_satin.bat` をダブルクリック

#### macOS / Linux
```bash
./mac/run_satin.sh
```

## 🛠 ツール一覧

Satinには以下の便利なツールが含まれています：

| ツール名 | 説明 | 対応OS |
|---------|------|-------|
| `manage_satin.py` | 設定ファイル全体の管理 | 全OS |
| `comment_manager_batch.py` | コメント管理設定の検証・最適化 | 全OS |
| `tts_manager_batch.py` | TTS設定の検証・最適化 | 全OS |
| `overlay_manager_batch.py` | オーバーレイ設定の検証・最適化 | 全OS |

## 🔧 高度な使い方

### バッチ処理の実行例
```bash
# 設定ファイルのバリデーション
python manage_satin.py --validate

# バックアップの作成
python manage_satin.py --backup

# コメント管理設定の最適化
python comment_manager_batch.py --optimize
```

### コマンドラインオプション
```
-h, --help      ヘルプを表示
-v, --verbose   詳細なログを出力
--validate      設定ファイルの検証を実行
--backup        設定ファイルのバックアップを作成
--optimize      設定の最適化を実行
```

## 🛠 トラブルシューティング

### よくある問題

1. **Pythonがインストールされていない場合**
   - [Python公式サイト](https://www.python.org/downloads/)から最新版をインストール
   - インストール時に「Add Python to PATH」にチェックを入れる

2. **パッケージのインストールに失敗する場合**
   ```bash
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```

3. **権限エラーが発生する場合**
   - Windows: 管理者として実行
   - macOS/Linux: `sudo` を付与して実行
- ログファイル（satin_profile.log等）でエラーや実行時間を確認
- バックアップ(zip)からの復旧は、zipを展開し元ファイルを上書きするだけ
- バリデーションエラー時はエラーログ参照＋必要に応じて手動修正

### 今後の拡張予定
- バッチ処理結果のGUI可視化やWebダッシュボード対応
- 自動リストア・バージョン管理・ワンクリック復旧
- 重大エラー時の自動ロールバック・リトライ

## フォルダ構成例

- comment_manager_*.py, comment_reader_*.py ... コメント管理・読み上げ
- manage_satin.py ... 配信補助・管理
- config.json ... 配信設定ファイル
- tts_manager_batch.py, overlay_manager_batch.py ... TTS/オーバーレイ管理バッチ
- batch_utilities_README.md ... バッチ最適化ガイド

---

ご質問・要望はIssuesへ！
