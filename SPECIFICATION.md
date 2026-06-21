# Satin 仕様書 (Specification)

> 最終更新: 2026-06-20
> 対象リビジョン: `claude/deepresearch-ultrathink-improvement-59Yhc`
> ステータス: ドラフト（既存実装からのリバースエンジニアリングに基づく）

---

## 1. 概要 (Overview)

**Satin** は、3D アバターをデスクトップ上のコンパニオンとして動作させる
Python アプリケーションである。ユーザーの入力（テキスト／音声／Web カメラによる
表情トラッキング）に対し、**ルールベース**（LLM・外部 API 非依存）で応答し、
TTS で音声合成しながら 3D アバターを動かす。関係性（好感度）・記憶・特別な日
などの「育成シミュレーション」的な要素を持つ。

> **注記:** ルートの `README.md` 冒頭は本プロジェクトを
> *"a powerful and flexible configuration management system"* と記述しているが、
> 実体は **3D アバター・デスクトップコンパニオン**である。設定管理機構は
> その基盤コンポーネントの一つにすぎない。本仕様書は実装を真実の源とする。

### 1.1 設計原則 (Design Principles)

| 原則 | 内容 |
|------|------|
| **オフラインファースト** | LLM・外部 API への必須依存なし。応答はルールベース。 |
| **標準ライブラリ中心** | コア機能は Python 標準ライブラリのみで動作。GUI/TTS/カメラ等は任意依存。 |
| **グレースフルデグラデーション** | 任意依存が無い／設定が壊れていても、機能を縮退させて起動を継続する。 |
| **ヘッドレス対応** | GUI・GPU・ディスプレイ無し（SSH／CI／サーバ）でも CLI で全機能利用可。 |
| **プライバシーローカル主義** | 会話・好感度・プロフィールは全てローカル保存。`data purge` で完全消去可能。 |
| **原子的書き込み** | 設定・状態ファイルは `.tmp` + `os.replace()` で破損を防ぐ。 |

### 1.2 動作要件 (Requirements)

- Python 3.8+
- 必須: `tkinter`（標準）
- 任意: PyQt5 / Pillow / numpy / opencv-python / mediapipe / pyttsx3 /
  sounddevice / pygltflib / flask / psutil / tenacity / httpx / matplotlib /
  pydub / beautifulsoup4 / selenium / tqdm

---

## 2. アーキテクチャ (Architecture)

### 2.1 起動フロー

エントリポイントは `satin_launcher.py`。

```
satin_launcher.py
  ├─ 依存チェック (_check_deps)        必須=tkinter / 任意=上記一覧
  ├─ 設定チェック (_check_config)      config/ の存在確認
  └─ モード分岐
       ├─ (既定)        GUI: avatar_loader.AvatarLoaderApp (tkinter)
       ├─ --chat         CLI 会話: persona_cli.main()
       ├─ --dashboard    Web: dashboard.app (Flask)
       ├─ --manage […]   管理 CLI: manage_satin.main()
       └─ --validate     設定検証のみ実行
```

### 2.2 レイヤ構成

```
┌─────────────────────────────────────────────────────────────┐
│ プレゼンテーション層                                          │
│  avatar_loader / avatar_3d_*  (GUI)                          │
│  persona_cli / manage_satin   (CLI)                          │
│  dashboard                    (Web/Flask)                    │
├─────────────────────────────────────────────────────────────┤
│ ドメイン層 (コンパニオンの“人格・関係性”)                     │
│  persona       人格・対話・キーワード応答 (respond)          │
│  mood          好感度トラッキング・レベル・記念日            │
│  user_profile  呼び名・誕生日・趣味の記憶                    │
│  special_days / daily_mood / gifts / daily_summary          │
│  conversation_log  会話履歴 (JSONL + ローテーション)         │
├─────────────────────────────────────────────────────────────┤
│ 入出力・メディア層                                            │
│  tts_thread / tts_with_virtual_audio / tts_manager_batch    │
│  camera_thread (FaceMesh) / autonomous_behavior             │
│  notification_system / i18n                                  │
├─────────────────────────────────────────────────────────────┤
│ 基盤層 (Infrastructure)                                      │
│  config_manager(_enhanced) / config_validator / config_schema│
│  logging_manager / cache_manager / backup_manager / scheduler│
│  plugin_manager / error_handling / graceful_shutdown        │
│  utils_config / utils_profile / fsutil                      │
├─────────────────────────────────────────────────────────────┤
│ 外部統合層 (任意)                                            │
│  youtube_integrator / paper_integrator / web_integrator     │
│  content_aggregator / async_integrator                      │
│  advanced_rate_limiting / retry_strategies / circuit_breaker │
└─────────────────────────────────────────────────────────────┘
```

規模: `main/` 配下 **83 モジュール**、`tests/` 配下 **94 テストファイル**
（**2055 tests passing / 1 skipped**）。

---

## 3. コンポーネント仕様 (Components)

### 3.1 人格・対話 (`persona.py`)

- `config/persona.json` から人格設定を読み込む（シングルトン `get_persona()`）。
- 提供する発話:
  - `talk()` — アイドル時の独り言（直前と重複しない無作為選択 `_pick`）。
  - `rest()` — 休憩台詞。
  - `greeting()` — 時刻別（朝/昼/夕/夜）＋好感度別あいさつ。
  - `respond(text, lang)` — **ユーザー入力へのキーワードルール応答**。
    - 入力を正規化（`strip().lower()`）し `rules` を順次走査、
      最初に部分一致した `keyword` の `replies` から選択。
    - 不一致時は `fallback`。空入力は `""` を返し、呼び出し側がオウム返しへフォールバック。
  - `follow_up()` — 数回の応答ごとに挿入する追加質問（好感度で内容が変化）。
- 言語フォールバック: 要求言語 → `default_lang` → `en` → 任意（`en-US`→`en` 対応）。
- 設定欠落・破損時は組み込み既定（`_DEFAULT_DIALOGUE` / `_DEFAULT_RESPONSES`）へ縮退。

### 3.2 好感度 (`mood.py`)

- 0–100 のスコアを 5 レベルへ写像: distant / reserved / neutral / friendly / close。
- `register(text)` で肯定/否定語を検出し ±delta（1 回あたり最大 ±10、0–100 にクランプ）。
- `config/mood.json` に永続化、日次スナップショットを `config/mood_history.jsonl` に追記。
- 記念日（出会いから 7/30/100/180 日、以降毎年）を 1 回だけ祝う。
- ログインストリーク・最終ログイン日も追跡。

### 3.3 会話履歴 (`conversation_log.py`)

- 会話イベントを `avatar_event_log.jsonl` に追記（ユーザー発話・アバター応答）。
- ローテーション（`<path>.<timestamp>.gz`）に対応し、`recent(n)` / `search(kw)` は
  アーカイブも横断する。
- 書き込み失敗は発話・UI を止めない（防御的）。

### 3.4 設定管理 (`config_manager*.py` / `utils_config.py`)

- `config/config.json` を基底に、以下の優先順で上書き（12-factor 準拠）:
  ```
  base config.json  <  config.<env>.json  <  .env  <  実環境変数 (SATIN_*)
  ```
- `SATIN_SECTION__KEY` 形式でネストキーを上書き（型自動キャスト）。
- `EnhancedConfigManager`: diff / undo スタック / ホットリロード（watchdog 任意）/
  JSON Schema サブセット検証 / エクスポート・インポート。

### 3.5 TTS (`tts_thread.py` / `tts_with_virtual_audio.py`)

- `pyttsx3` ベースのバックグラウンドスレッド。`tts_queue` から読み上げ文を取得。
- 仮想オーディオ版は `save_to_file` + デバイス再生（VTuber 配信向け）。
- スレッドループは `queue.get` と処理を分離し、処理例外でスレッドが死なないよう
  `try/except/finally` で `is_speaking` リセット・一時ファイル削除を保証。

### 3.6 Web ダッシュボード (`dashboard.py`)

- Flask 製。ポート **5003**（`__main__` 実行時）。
- 提供ページ: イベントログ `/logs`・会話履歴（検索・CSV/テキスト DL）・
  バックアップ・クラウド同期・好感度（履歴チャート）・統計・日次サマリ・
  ヘルスチェック `/healthz`。
- プライバシー保護のため会話・好感度ページは `no-store`。

### 3.7 管理 CLI (`manage_satin.py`)

`validate` / `mood` / `log` / `backup` / `persona` / `summary` / `data purge`
の各サブコマンド。GUI 不要のサーバ運用・スクリプト向け。

### 3.8 外部統合 (任意)

- `youtube_integrator` / `paper_integrator`(arXiv/Scholar) / `web_integrator`。
- `content_aggregator` が 3 ソースを `ThreadPoolExecutor` で並列横断検索し、
  BM25 簡易版 + 人気度 + 鮮度で関連度スコアリング。
- `async_integrator`（httpx）・トークンバケットレート制限・サーキットブレーカ。

---

## 4. データ仕様 (Data)

### 4.1 設定ファイル

| ファイル | 用途 | 種別 |
|----------|------|------|
| `config/config.json` | アプリ基底設定（log_level / backup / plugins …） | 設定 |
| `config/persona.json` | 人格・対話・応答ルール・好感度語 | 設定 |
| `config/mood_config.json` | 感情語・delta 上書き | 設定 |
| `config/user_profile.json` | 呼び名・誕生日・趣味（**git-ignore / 個人情報**） | 記憶 |
| `config/mood.json` | 好感度状態（**個人情報**） | 記憶 |
| `config/mood_history.jsonl` | 日次好感度履歴（**個人情報**） | 記憶 |
| `avatar_event_log.jsonl` | 会話・イベントログ（**個人情報**） | 記憶 |

### 4.2 イベントログ行スキーマ (JSONL)

```jsonc
{ "timestamp": 1718800000.0, "event_type": "user_comment",
  "details": { "text": "こんにちは" } }
```

`event_type` は `conversation_log.USER_EVENT_TYPES` /
`AVATAR_EVENT_TYPES` で分類。各行は独立した JSON オブジェクト
（壊れた行・`null` 行はスキップする — §6 参照）。

---

## 5. 長所 (Strengths)

1. **堅牢なグレースフルデグラデーション**
   任意依存・設定欠落・破損 JSON のいずれでも起動を継続する設計が一貫している。
2. **ヘッドレス完全対応**
   GUI と同じ人格・応答・ロギングを CLI から利用でき、ユニットテスト可能
   （入出力関数を注入可能）。
3. **手厚いテスト**
   2055 件のテストが通過。境界値・null・スレッド耐性まで回帰テスト済み。
4. **プライバシー設計**
   個人データのローカル保存・`data purge` による完全消去・Web の `no-store`。
5. **原子的書き込みの徹底**
   状態ファイルは `.tmp` + `os.replace()` で部分書き込み破損を回避。
6. **12-factor 準拠の設定オーバーライド**
   環境変数・`.env`・環境別オーバレイの多層マージ。
7. **国際化基盤**
   i18n フォールバックチェーンが UI と対話で共通化されている。

## 6. 短所・既知の弱点 (Weaknesses)

| # | 重大度 | 箇所 | 内容 |
|---|--------|------|------|
| W1 | 中 | `satin_launcher.py` vs `dashboard.py` | ダッシュボードのポートが不整合。ランチャ既定=**5000**、`dashboard.py` 直接実行=**5003**、README=**5003**。`--dashboard` 起動時のみ 5000 になり、ドキュメント・直接実行と食い違う。 |
| W2 | 中 | `README.md` 冒頭 | 製品説明が実体（3D アバターコンパニオン）と乖離（"configuration management system"）。新規参加者が誤解する。 |
| W3 | 低 | ドキュメント | 体系的な仕様書が存在せず、知識が README と多数の `*_IMPROVEMENTS.md` に散在。 |
| W4 | 低 | `dashboard.py` | ハードコードされたポート（定数化されていない）。再利用・テスト時に変更しづらい。 |
| W5 | 低 | 任意依存の管理 | 依存一覧が `satin_launcher.py` 内にハードコードされ、`setup/requirements.txt` と二重管理。 |
| W6 | 情報 | `null`/型不正データ耐性 | 直近セッションで JSONL/設定の `null` 値クラッシュを多数修正済み（§ CHANGELOG）。同種の防御は今後も新規 I/O ごとに必要。 |

## 7. 改善点 (Improvements) — 本コミットで実装

- **[実装] I19 (静的解析 ruff 由来 — 3D 描画が NameError でクラッシュ):**
  `ruff` (F821 undefined-name) で、7 つの 3D アバタービューア
  (`avatar_3d_sync` / `avatar_3d_gltf_viewer` / `avatar_3d_autonomous` /
  `avatar_3d_autonomous_or_camera` / `avatar_3d_mic_tts_modes` /
  `autonomous_gltf_avatar` / `avatar_3d_autonomous_tts`) が `paintGL`/`draw`
  内で OpenGL 名 (`glClear` / `glBegin` / `GL_*` / `gluSphere` 等) を **import
  せず**使用していることを検出。import 共通化リファクタで各モジュールから
  `from OpenGL.GL import *` が抜け落ち、**アプリ中核の 3D 描画が初回 paint で
  `NameError` クラッシュ**する潜在バグだった（GUI/GPU/PyOpenGL 必須でテスト
  未到達のため見逃されていた）。`avatar_3d_viewer.py` の生存パターンに合わせ、
  各モジュールにガード付き `from OpenGL.GL/GLU import *` を追加。
  検証: ruff F821 解消 + py_compile + ヘッドレステスト全通過（実 GUI 描画は
  本環境に display/GPU が無く未実行）。
- **[実装] I18 (静的解析 ruff 由来 — ミュータブルデフォルト引数):** `ruff`
  (bugbear B006) で、手動 grep が見逃していた関数引数のミュータブルデフォルトを
  4件検出。`content_aggregator.search_all_sources` /
  `get_trending_content` / `create_knowledge_base` の `sources=[...]` と
  `youtube_integrator.get_transcript` の `languages=['ja','en']`。現状は読み取り
  専用で実害は無いが、全呼び出しで同一リストを共有する脆弱性のため `None`
  センチネルパターンへ統一。あわせて `config_validator` の `not X in Y`
  (誤読しやすいが機能的には正しい) を `not in` に明確化 (E713)。
  参考: [ミュータブルデフォルト引数の罠 (Qiita Vermee81)](https://qiita.com/Vermee81/items/eb6c43cae896b3a3bb48)

- **[実装] I1 (W1, W4 解消):** ダッシュボードのポートを単一の定数
  `DEFAULT_DASHBOARD_PORT = 5003` に集約し、`dashboard.py` の `__main__` と
  `satin_launcher.py --dashboard` の既定値を一致させる。環境変数
  `SATIN_DASHBOARD_PORT` でも上書き可能にする。
- **[実装] I2 (W2 解消):** `README.md` 冒頭の製品説明を実体に合わせて修正。
- **[実装] I3 (W3 解消):** 本仕様書 `SPECIFICATION.md` を新規作成（このファイル）。

- **[実装] I4 (W6 再発防止 / B3):** JSONL 読み込みの共通ローダ
  `fsutil.iter_jsonl_dicts()` / `load_jsonl_dicts()` を追加。空行・JSON 構文
  エラー行・`dict` 以外（`null`/配列/スカラ）を一元的にスキップする。
  `avatar_event_report.load_events` / `avatar_event_logger.replay` /
  `mood.load_mood_history` を本ローダへ移行し、重複していたガードを集約。

- **[実装] I17 (Qiita 由来 — テンプレ漏れ防御 / `{user}` 集約):** GUI の
  コメント応答で `{user}` プレースホルダ解決が `speak_comment` のみで行われ、
  別の出力経路 `_speak_reply()`（ギフト・プロフィール質問・スラッシュコマンド
  応答）を通らなかった。現状それらの台詞に `{user}` は無いが、将来追加すると
  literal `{user}` が読み上げ／表示へ漏れる脆さがあった。`{user}` 解決を全
  コメント応答の唯一の出口 `_speak_reply()` に集約し（personalize は `{user}`
  非含有なら無変換のため無害）、防御を一点に統一。
  参考: [str.format / テンプレートの波括弧と KeyError (Qiita)](https://qiita.com/FGtatsuro/items/a64066e2151203b7221a)

- **[実装] I16 (Qiita 由来 — 無制限キューでメモリ肥大):** `camera_thread` が
  無制限 `queue.Queue` に毎フレーム pose を `put` していたため、消費側 (Qt
  タイマー) が止まる/遅れる (ウィンドウ最小化・GL 停止等) と pose がメモリに
  際限なく溜まった。ライブ姿勢は最新のみ有効なので `_enqueue_pose()` で
  バックログを `_MAX_BACKLOG=2` に制限 (古いフレームを捨てて最新を保持)。
  参考: [queue.Queue の maxsize とバックプレッシャー (Qiita)](https://qiita.com/tomyox693/items/5624dd8f11305f9de7f0)
- **[実装] I15 (Zenn 由来 — 環境変数の非有限 float キャスト):** `config/env.py`
  の自動型キャストが `float()` をそのまま使い、環境変数 `inf` / `-inf` /
  `infinity` / `nan` / `1e999` を黙って `float('inf')` / `float('nan')` に
  変換していた。`nan` は全比較が False になり閾値判定を破壊、`inf` も数値
  ロジックを壊す。`math.isfinite()` で非有限値は数値扱いせず文字列へ
  フォールバック（正当な `1e3`=1000.0 等の有限値は従来通り数値）。
  参考: [浮動小数点の比較と誤差 / math.isclose (Zenn)](https://zenn.dev/sergicalsix/articles/f261d66bc1773b)
- **[実装] I14 (プライバシー — バックアップ zip が world-readable):**
  `backup_manager.create_backup()` および `dashboard._build_sync_backup()` が
  生成する zip は `mood.json` / `user_profile.json` / `avatar_event_log.jsonl`
  等の**個人データを含む**にも関わらず、umask 既定 (0o644) のまま放置で
  マルチユーザー環境の他ユーザーが読めた。これは既に `fsutil.restrict_to_owner`
  で対策していた個別ファイルと一貫しない抜け穴。生成直後に所有者のみ読み書き可
  (0o600) に制限する best-effort 処理を追加。
- **[実装] I12 (Snyk/Qiita 由来 — Zip Slip 脆弱性):**
  `backup_manager.restore_backup()` が `shutil.unpack_archive`（内部で
  `zipfile.extractall`）をパス検証なしで呼んでいたため、悪意ある zip 内に
  ``../etc/passwd`` 等のエントリがあると **target_dir 外への任意ファイル書き込み**
  が可能だった。`manage_satin.cmd_backup_restore` は既に同型ガードを実装済み
  だったため、その実装に揃えて各エントリの解決後パスを `realpath` で検証する
  方式に書き換え。
  参考: [Zip Slip 脆弱性の解説 (Snyk)](https://snyk.io/blog/behind-the-disclosure-the-zip-slip-vulnerability/)
- **[実装] I13 (Qiita 由来 — exc_info 欠落でスタックトレース消失):**
  `backup_scheduler` / `logging_manager` の重要 except 節が
  `logger.error(f"...{e}")` だけでスタックトレースを残さず、根本原因の切り分け
  が困難だった。クリティカル経路 3 箇所に `exc_info=True` を追加。
  参考: [logger による例外のログ出力 (Qiita)](https://qiita.com/AirhAurum/items/de28ad28cbf91514bcf3)
- **[実装] I11 (Zenn 由来 — 非原子的書き込みで基底設定が破損):** アプリ全体で
  最も使われる設定書き込みパス `utils_config.save_config()` だけが、他全モジュール
  が使う原子的パターンを使わず **インプレース `open(path,'w')`** で書いており、
  書き込み中のクラッシュ／`json.dump` 例外で `config.json` が切り詰められ次回
  起動でアプリ全体が壊れる危険があった。同一ディレクトリの一時ファイルへ
  全量書き込み→`fsync`→`os.replace` の原子的書き込みに変更（失敗時は元ファイル
  を保全し一時ファイルも残さない）。
  参考: [sync コマンドのデータ同期と I/O エラー検出 (Zenn)](https://zenn.dev/satoru_takeuchi/articles/248574593145ed)
- **[実装] I10 (Qiita 由来 — naive/aware datetime 混在):** `content_aggregator`
  で YouTube Data API 由来の **aware** datetime と yt-dlp/論文/Web 由来の
  **naive** datetime が混在し、(a) `datetime.now() - aware` で TypeError →
  関連度スコアリングが例外で **YouTube 結果が丸ごと欠落**、(b) `min/max(dates)`
  も同型 TypeError。変換 funnel で `_to_naive()`（aware→UTC naive）に一律正規化。
  参考: [utcnow() の代わりに now(UTC) を / naive・aware の落とし穴 (Qiita)](https://qiita.com/ayu_ko_mimo/items/ac334dcc9a073aac28f7)
- **[実装] I8 (Qiita 由来 — RotatingFileHandler 重複登録):** `LoggingManager`
  を 2 回インスタンス化するとルートロガーに同一ハンドラが二重に追加され、
  全ログ行が重複出力、Windows ではローテーション時に PermissionError になる。
  ハンドラに ``satin.rotating_file`` / ``satin.console`` のマーカー名を付け、
  既存検出で重複登録を防止。
  参考: [RotatingFileHandler の重複ハンドラ落とし穴 (Qiita)](https://qiita.com/KAZAMAI_NaruTo/items/a1dc89e4ae0ecab56c77)
- **[実装] I9 (Zenn 由来 — シングルトン スレッドセーフ):**
  `get_enhanced_config_manager()` がロック無しの素朴な ``if is None: create``
  実装で、並行コンテキストで 2 インスタンス生成され得た（undo/listener 状態が
  分裂し最後勝ち）。double-checked locking パターンに統一。
  参考: [Singleton の罠 — スレッドセーフ実装 (Zenn)](https://zenn.dev/koduki/articles/47ebe8d93e27e0)
- **[実装] I6 (Zenn 由来 — Flask セッション強化):** ダッシュボードのセッション
  Cookie に `HTTPONLY=True` / `SAMESITE='Lax'` / `PERMANENT_SESSION_LIFETIME=12h`
  / `SECURE` を環境変数 `SATIN_DASHBOARD_HTTPS=1` でオプトイン可能化。Flask の
  素のデフォルト (SAMESITE 未設定・31日 lifetime) は CSRF/リプレイに弱いため。
  参考: [Flask セッション管理とセキュリティ (Zenn)](https://zenn.dev/saiki_toshiki/articles/946e4a3c2eb4c5)
- **[実装] I7 (Qiita 由来 — Windows tempfile 競合):** `tts_with_virtual_audio.py`
  で `NamedTemporaryFile(delete=False)` を `with` で保持したまま
  `pyttsx3.save_to_file()` を呼んでいたため、Windows で **共有違反**となり
  TTS が黙って失敗していた。`tf.close()` 後にパスだけ渡すよう修正。
  参考: [NamedTemporaryFile の Windows 落とし穴 (Qiita)](https://qiita.com/yuji38kwmt/items/c6f50e1fc03dafdcdda0)
- **[実装] I5 (W5 / B1):** 任意・必須依存の単一宣言 `dependency_manifest.py`
  （重い import を行わない純データ）を追加し、`satin_launcher.py` の依存チェック
  をここから生成。ランチャ内のハードコード一覧を撤去し二重管理を解消。
  各依存に「有効化する機能」の説明を付与（ドキュメント用）。

### 7.1 将来の改善候補 (Backlog, 未実装)

- B2: 散在する `*_IMPROVEMENTS.md` を `docs/` 配下へ整理し本仕様書から相互参照。
- B5: `dependency_manifest` を `setup/requirements*.txt` 生成にも利用し、
  インストール定義の二重管理（W5 の残り半分）も解消する。
- B4: `daily_summary._load_jsonl`（gz アーカイブ対応）と `conversation_log`
  （event_type フィルタ + ストリーミング早期終了）も、gz・フィルタに対応した
  共通ローダへ将来的に統合可能（現状は専用実装を維持）。

---

## 8. 検証 (Verification)

```bash
cd /home/user/Satin
python -m pytest tests/ -q          # 全回帰 (現在 2055 passed)
python satin_launcher.py --validate # 設定検証
python main/dashboard.py            # http://127.0.0.1:5003
python satin_launcher.py --dashboard  # 同一ポートで起動すること (I1)
```
