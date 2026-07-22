# Satin — 長所・短所・改善ワークオーダー（Opus / Sonnet 向け実装指示書）

> **これは何か**: Satin（Python 製デスクトップ 3D アバターコンパニオン）の現状を
> **長所 / 短所** として棚卸しし、Opus / Sonnet クラスのモデルが**このドキュメント
> だけを起点に単独で実装へ着手できる**ワークオーダー（作業指示カード）に落とした
> もの。既存の `RESEARCH_DRIVEN_IMPROVEMENTS_PY.md`（研究駆動の Tier 分類）を補完
> し、そちらが「何を作るか」なら本書は「どう実装し、何を確認すれば完了か」を扱う。
>
> **各ギャップは作成時点で file:line を確認済み**。ただしコードは変化するので、
> 各カードは着手時に「実装前チェック」の grep / Read を必ず先に実行すること。

---

## 0. 最初に読むこと（設計境界と作業規約）

### 0.1 侵してはいけない設計境界
- **意図的な no-LLM / オフライン / プライバシー第一設計**。対話・感情・記憶はすべて
  辞書 / ルール / キーワード / BM25 / 変化点検知など**決定論的アルゴリズム**で実装
  されている（`user_wellbeing.py` が設計方針として明記）。これを「機能不足」と
  誤認して LLM / クラウド API を導入する変更を**勝手に行わないこと**。該当提案は
  すべて Tier C（§3 W-90）扱いで、実装前に人間の承認が必須。
- `main/README_REMOVE.txt` は **信用しないこと**（§3 W-05 参照）。フラグシップ GUI
  を削除候補として挙げている壊れたメモ。

### 0.2 このリポジトリの作業規約（必守）
1. **1 機能 = 1 コミット**。
2. **revert-verify**: テストを追加したら、修正コードを `git stash` して「修正が無いと
   新テストが落ちる」ことを必ず確認してから戻す。落ちないテストは無意味。
3. コミット前に **`python -m pytest tests/ -q` が full green**（現状 **2,939 passed**）
   かつ **`ruff check main/ tests/` が clean**。
4. **実データ汚染禁止**: `tests/conftest.py` の autouse 隔離（会話ログ・ユーザー
   プロフィール）を壊さない。テスト実行後に `config/user_profile.json` /
   `avatar_event_log.jsonl` 等が生成されていないことを確認。
5. optional-import は既存様式に従う（`try: import X except Exception: X = None` →
   利用側でガード）。
6. ユーザー向け応答は必ず `_speak_reply()`（GUI）/ 対応する出力関数を経由し、
   `lang`（`persona.lang`）で日英を出し分ける。
7. ファイル保存は個人データなら 0600（`fsutil` / 各モジュールの `_atomic_write` を
   再利用）。
8. 開発ブランチ `claude/deepresearch-ultrathink-improvement-59Yhc` → push → PR →
   `master` へ **merge**（履歴保持のため squash 不可）。

---

## 1. 長所（維持すべき設計資産）

| # | 長所 | 根拠 |
|---|------|------|
| S1 | **no-LLM / オフライン / プライバシー第一**を貫いた決定論的な対話・感情・記憶 | `mood.py` / `conversation_log.py` / `user_wellbeing.py` |
| S2 | **研究駆動の安全設計**: 感情依存ガードレール・否定/強度対応感情判定・BM25 記憶想起・変化点検知・概日トーン | `usage_guardrails.py`, `mood.py`, `conversation_log.search_relevant`, `user_wellbeing.wellbeing_shift`, `persona.py`。詳細は `RESEARCH_DRIVEN_IMPROVEMENTS_PY.md` |
| S3 | **完全なデータ消去経路**（プライバシーの実効性）: GUI `/forget-all` と CLI `data purge` が会話・好感度・プロフィール・アバター履歴を一括消去 | `avatar_3d_autonomous_tts._erase_all_user_data`, `manage_satin.cmd_data_purge` |
| S4 | **強固なテスト文化**: 2,939 件、revert-verify 規約、conftest によるデータ隔離、optional-import フォールバック様式 | `tests/`, `tests/conftest.py` |
| S5 | **セキュリティ修正済み**: CSRF・SSRF・CSV 式インジェクション・Zip Slip・原子的書き込み・0600 権限 | `dashboard.py`, `fsutil.py`, `backup_manager.py` ほか（CHANGELOG / SPECIFICATION 参照） |
| S6 | **単一エントリポイント + 依存の single-source** | `satin_launcher.py`, `dependency_manifest.py` |
| S7 | **多言語対応（会話 + GUI クローム）** | 全 `_cmd_*_gui` と `MainWindow._autonomous_label` が `lang` 出し分け |

---

## 2. 短所サマリ（詳細は §3 の各カード）

| ギャップ | 深刻度 | カード |
|----------|--------|--------|
| ~~多重起動ガードが無い（同時書き込みでデータ破損しうる）~~ ✅**実装済** | 高 | W-01 |
| ~~GUI 終了処理が不完全（スレッド join なし・タイマー停止なし）~~ ✅**実装済** | 高 | W-02 |
| ~~**危険な誤った削除メモ** `README_REMOVE.txt`~~ ✅**撤去済** | 高 | W-05 |
| `__version__` 不在・`--version` フラグ無し | 中 | W-03 |
| 孤児モジュール（`sync_to_cloud.py` 等）の整理 | 中 | W-04 |
| dashboard の多言語対応状況が未検証 | 中 | W-06 |
| 型チェック（mypy）未導入 | 中 | W-07 |
| 3D 描画がワイヤーフレーム止まり（面・法線・シェーディング無し） | 低 | W-08 |
| CI 未有効化・lock ファイル無し（オーナー/方針事項） | — | §4 |
| Tier B/C（ローカル ML / TTS / LLM）は要方針判断 | — | W-90 |

---

## 3. ワークオーダー（作業指示カード）

各カード形式: **背景 → 対象 → 実装前チェック → 実装方針 → テスト → 完了条件 → 触るな**

### W-01: 多重起動ガード（single-instance lock） — [難易度 M / 優先度 高]
- **背景**: GUI（`satin_launcher.py` 既定モード）を 2 つ起動すると、両者が
  `config/mood.json`・会話ログ・`user_profile.json` を並行書き込みし、状態が破損
  しうる。市販アプリなら単一インスタンス化は標準。
- **対象**: `satin_launcher.py`（`main()` の各 GUI 起動前）。新規 `main/single_instance.py` も可。
- **実装前チェック**: `grep -rniE "lock|pid|single.?instance" main/ satin_launcher.py`
  で既存機構が無いことを再確認。
- **実装方針**: OS 非依存のロックファイル方式。`config/` に `satin.lock` を作り、
  PID を書く。起動時に (a) ロックが無ければ取得、(b) あれば中の PID が生存して
  いるか確認（生存なら「既に起動中」を表示して終了、死んでいれば stale として奪取）。
  終了時（`closeEvent` / `atexit`）に解放。`fsutil` の原子的書き込みを再利用。
  `--chat`/`--dashboard`/`--manage`/`--validate` はロック対象外（複数同時可）。
- **テスト**: `tests/test_single_instance.py` — 取得→再取得が失敗、解放後は再取得可、
  stale PID（存在しない PID を書いた lock）は奪取可、をヘッドレスで。
- **完了条件**: full suite green、2 回目の GUI 起動が明示メッセージで終了。
- **触るな**: ヘッドレスモード（chat/dashboard/manage/validate）の並行起動可能性。

### W-02: closeEvent の完全シャットダウン — [難易度 S / 優先度 高]
- **背景**: `avatar_3d_autonomous_tts.py` の `closeEvent`（L1416 付近）は
  `self.tts_thread.running = False` を立てるだけで **`join()` していない**。また
  `self.text_timer`（100ms）と `self.viewer.timer`（50ms）を停止していないため、
  ウィンドウ破棄後にタイマーが発火して破棄済みウィジェットにアクセスしうる。
  自律モード中なら break_reminder は止めているが、TTS スレッドの終了待ちが無い。
- **対象**: `avatar_3d_autonomous_tts.MainWindow.closeEvent`。
- **実装前チェック**: 当該メソッドを Read し、現状の停止処理を確認。
  `TTSThread` は `daemon=True`・`stop()` メソッド有り（`tts_thread.py`）。
- **実装方針**: `self.tts_thread.stop()` を呼び（`running=False` の直書きより意図明確）、
  `self.tts_thread.join(timeout=2.0)` で終了待ち。`self.text_timer.stop()` と
  `self.viewer.timer.stop()` を try/except で停止。既存の mood 保存はそのまま。
- **テスト**: `MainWindow` は Qt 必須なので `object.__new__` で生成し、`closeEvent` に
  必要な属性（`tts_thread`=Mock、`text_timer`/`viewer.timer`=Mock、mood 関連を
  patch）を差し込み、`closeEvent` 呼び出しで `stop()`/`join()`/`timer.stop()` が
  呼ばれることを検証。`event`=Mock（`accept()` 検証）。
- **完了条件**: closeEvent 後に TTS スレッドが停止・タイマーが停止していること。
- **触るな**: 既存の mood 保存ブロック。

### W-03: `__version__` の単一宣言 + `--version` — [難易度 S / 優先度 中]
- **背景**: 全 `.py` に `__version__`/`APP_VERSION` が無い（grep 0 件）。バージョンは
  `config/config.json` の `"version"` だけ。パッケージ配布・バグ報告で版が特定できない。
- **対象**: 新規 `main/version.py`（`__version__ = "1.1.0"`）。`satin_launcher.py` に
  `--version`。`config/config.json` と一致させる。
- **実装前チェック**: `grep -rn "__version__\|APP_VERSION" main/ satin_launcher.py`
  が 0 件、`config/config.json` の現行版を確認。
- **実装方針**: `main/version.py` に定数。`satin_launcher` の argparse に
  `--version`（`action="version"`）。整合テストで config.json と一致を保証。
- **テスト**: `tests/test_version.py` — `version.__version__` が semver 形式、
  `config/config.json["version"]` と一致。
- **完了条件**: `python satin_launcher.py --version` が版を表示、整合テスト green。
- **触るな**: config.json のスキーマ（既存テストが版文字列を参照）。

### W-04: 孤児モジュールの整理 — [難易度 S / 優先度 中]
- **背景**: 本体からもテストからも import されないモジュールが残存。特に
  **`sync_to_cloud.py`** は Google Drive / Dropbox へアップロードする CLI で、
  no-LLM / プライバシー第一の設計とも相反し、どこからも呼ばれていない。
- **対象（着手時に再検証必須）**: `sync_to_cloud.py`（本体/テスト参照ゼロを確認済み）。
  `batch_test_util.py` / `camera_tracking_sample.py` はテストのスモークのみ。
  `avatar_3d_autonomous.py` / `avatar_3d_sync.py` / `avatar_3d_viewer.py` は
  スタンドアロンのデモビューアで本体未使用。
- **実装前チェック（必須）**: 各候補について
  `grep -rl "\b<module>\b" main/ tests/ satin_launcher.py examples/ | grep -v <self> | grep -v __pycache__`
  を再実行し、**docstring/コメントのみのヒットは参照に数えない**（実 import かを Read で確認）。
- **実装方針**: 二択を候補ごとに判断。(a) 真の孤児（`sync_to_cloud.py`）は削除、または
  `examples/` へ移動して「参考実装・非サポート」と明記。(b) デモビューアは
  `examples/` へ移動しテストの smoke import 参照を更新。**判断に迷うものは削除せず
  据え置き、本カードに記録するだけにする**（誤削除は W-05 の教訓）。
- **テスト**: 移動/削除に合わせて `tests/test_avatar_modules.py` 等の import 参照を更新。
- **完了条件**: full suite green、削除/移動した各ファイルが本当に未使用だった根拠を
  コミットメッセージに列挙。
- **触るな**: `avatar_3d_autonomous_tts.py`（フラグシップ）、`avatar_loader.py`、
  `avatar_3d_gltf_viewer.py`、`autonomous_gltf_avatar.py`、`avatar_event_*` 系
  （ダッシュボード/ログで使用）。**README_REMOVE.txt を根拠に削除しないこと。**

### W-05: 危険な `README_REMOVE.txt` の撤去/修正 — [難易度 S / 優先度 高]
- **背景**: `main/README_REMOVE.txt` は「削除候補」として **`avatar_3d_autonomous_tts.py`
  （既定起動のフラグシップ GUI）**・`avatar_loader.py`（`--avatar-loader`）・
  `avatar_3d_gltf_viewer.py`（モデル読込）・`avatar_event_*`（ダッシュボード/ログ）を
  列挙し「新機能は autonomous_gltf_avatar.py に集約」と誤記。実態と正反対で、
  これを信じた将来のエージェントが**製品本体を削除しかねない**。
- **対象**: `main/README_REMOVE.txt`。
- **実装前チェック**: 列挙された各ファイルが実際に使われているか（W-04 の grep）で
  裏取り。特に `avatar_3d_autonomous_tts` は `satin_launcher._launch_avatar_gui` が
  import している。
- **実装方針**: 誤りなので**削除**するのが最善。もし整理方針の記録を残したいなら、
  W-04 の検証結果に基づき「実際に未使用のファイルのみ」を列挙した正確なメモに
  差し替える（フラグシップ等は絶対に含めない）。
- **テスト**: N/A（ドキュメント）。ただし削除後に full suite green を確認。
- **完了条件**: 誤ったメモが除去され、フラグシップ削除の地雷が消える。
- **触るな**: 実コード。

### W-06: dashboard の多言語対応（まず検証） — [難易度 M / 優先度 中]
- **背景**: `locales/{ja,en}.json` は 18 キーのみ。GUI クロームは W-07（済）で両言語化
  したが、**dashboard の HTML/文字列が locales を使っているか未検証**。英語ユーザーに
  日本語ダッシュボードが出る可能性。
- **対象**: `main/dashboard.py`、`main/i18n.py`（`t()` ヘルパ）、`locales/*.json`。
- **実装前チェック（このカードの前半＝調査）**: `dashboard.py` を Read し、
  (a) `i18n.t()` / `locales` を使っているか、(b) ハードコード文字列の言語、
  (c) 言語決定の仕組み（Accept-Language? 設定?）を確認。**調査結果次第で後半の
  実装内容が変わる**ため、まず所見をまとめる。
- **実装方針（調査後に確定）**: ハードコード日本語があれば `i18n.t(key, default)` 経由に
  移し、不足キーを `locales/{ja,en}.json` に追加（両ファイルのキー数一致を保つ）。
- **テスト**: locales の ja/en キー完全一致テスト、`i18n.t()` のフォールバック、
  dashboard のテンプレートレンダリングが言語で切替わること（既存の dashboard テスト
  様式に合わせる）。
- **完了条件**: full suite green、英語設定で英語ダッシュボード。
- **触るな**: セキュリティヘッダ（`no-store` 等）・CSRF トークン処理。

### W-07: mypy の段階導入 — [難易度 M / 優先度 中]
- **背景**: 型チェッカーが設定・依存・CI のいずれにも無い。ruff（F821 等）で
  実行時 NameError 級を後追い検出してきた経緯があり、静的型検査層が欠けている。
- **対象**: 新規 `mypy.ini`（または `pyproject` は無いので独立 ini）、`setup/requirements.txt`
  の開発依存、`setup/github-actions-ci.yml` に lint ジョブ追加。
- **実装前チェック**: `python -m mypy --version` で不在確認。中核モジュール
  （`mood.py`, `conversation_log.py`, `user_wellbeing.py`, `persona.py`,
  `avatar_model_store.py`）に対して緩い設定（`ignore_missing_imports=True`）で試走。
- **実装方針**: まず上記 5 モジュールだけを対象に緩い mypy を通す（既存の型注釈が
  多いので通る見込み）。CI に非ブロッキングで追加 → 段階的に対象拡大。
- **テスト**: CI 設定なので pytest 対象外。ローカルで `mypy <対象>` がエラー 0。
- **完了条件**: 中核 5 モジュールが mypy clean、requirements/CI に反映。
- **触るな**: 大規模な型注釈リファクタ（段階導入が原則）。

### W-08: 3D 描画の強化（面 + 単色シェーディング） — [難易度 L / 優先度 低]
- **背景**: `avatar_3d_autonomous_tts.paintGL` と `avatar_3d_gltf_viewer` は
  頂点の `GL_LINE_STRIP`（ワイヤーフレーム）のみ。市販アバターとしては見栄えが弱い。
- **対象**: `gltf_utils.py`（面インデックス抽出を追加）、
  `avatar_3d_autonomous_tts.AutonomousAvatarViewer.paintGL`、`_load_model_vertices`。
- **実装前チェック**: `gltf_utils.load_first_mesh_vertices` の実装と、pygltflib で
  `primitives[0].indices` から面を取る方法（`autonomous_gltf_avatar.py` に既存の
  試みあり — ただし `.data` 誤用の未修正バグがあるので流用時は W 実績の
  `_resolve_buffer_bytes` を使う）を確認。
- **実装方針**: `load_first_mesh_faces(gltf, np)` を新設（indices アクセサを
  `_resolve_buffer_bytes` + offset で正しく読む）。法線を面から計算し、
  `GL_TRIANGLES` + 単色ディフューズで描画。頂点のみ（面なし）モデルは
  従来のワイヤーフレームにフォールバック。
- **テスト**: 実 pygltflib で面付き GLB を組み立て → `load_first_mesh_faces` が
  正しい三角形インデックスを返す往復テスト（`skipUnless(pygltflib)`）。法線計算の
  純関数テスト。
- **完了条件**: full suite green、面付きモデルが陰影付きで描画（実 GPU での目視は
  ヘッドレス CI では不可なので、頂点/面/法線データの正しさをテストで担保）。
- **触るな**: テクスチャ・スキニング・アニメーション（本カードの範囲外。別途方針判断）。

### W-90: Tier B/C（ローカル ML / 表現力 TTS / ローカル LLM） — [実装するな・要人間承認]
- **背景**: 小型ローカル埋め込み記憶（A4 上位）、WRIME 学習の感情分類（A2 上位）、
  Style-Bert-VITS2 等の表現力 TTS、Ollama 等のローカル LLM 対話生成は、いずれも
  製品の **no-LLM 明言 / 依存最小 / オフライン**の設計境界に触れる。
- **指示**: これらは**勝手に実装しない**。必要と判断したら、まず本書 §0.1 の設計境界を
  引用しつつ人間に「導入可否」を問うこと。導入する場合も未導入時は現行の決定論的
  実装へ自動フォールバックする optional 依存として設計する（`RESEARCH_DRIVEN_IMPROVEMENTS_PY.md`
  の Tier B/C 記述に従う）。

---

## 4. オーナー専用作業（エージェント権限では不可）

以下はリポジトリオーナーの操作が必要（本セッションの git トークンでは 403 / 権限外）:
1. **CI 有効化**: `cp setup/github-actions-ci.yml .github/workflows/ci.yml` して push
   （`workflows` OAuth スコープが必要）。有効化後は `setup/` 側のコピーを削除して single-source 化。
2. **タグ / Release**: `git tag v1.1.0 <master HEAD> && git push origin v1.1.0`、
   または GitHub の Releases から作成。リリースノートは `CHANGELOG.md [1.1.0]` を流用。
3. **リポジトリ公開設定**の確認（Settings → Visibility）。
4. 依存 lock ファイル生成（`pip-tools` / `uv`）と Dependabot 設定（`.github/` 配下）。

---

## 5. 実行順の推奨

W-05（危険メモ撤去・即座）→ W-02（終了処理・小）→ W-01（多重起動・中）→
W-03（version・小）→ W-06（dashboard i18n・調査から）→ W-04（孤児整理・慎重に）→
W-07（mypy）→ W-08（描画強化）。W-90 とオーナー作業（§4）は別枠。

各カードは 1 機能 = 1 コミット、revert-verify、full suite green + ruff clean、
PR → master merge の規約（§0.2）で進めること。
