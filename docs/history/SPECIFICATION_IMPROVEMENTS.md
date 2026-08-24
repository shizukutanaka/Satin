# 実装済み改善の記録（旧 SPECIFICATION.md §7）

> **これはアーカイブである。** 過去に実施した改善の記録であり、
> 「現在このリポジトリがこうである」という主張ではない。ここに出てくる
> モジュール名の多くは既に削除されている（それが正しい — 当時は存在した）。
> 現在の仕様は [`SPECIFICATION.md`](../../SPECIFICATION.md)、
> 変更履歴は [`CHANGELOG.md`](../../CHANGELOG.md) を参照。
>
> 元は SPECIFICATION.md の §7「改善点 — 本コミットで実装」だった。
> 423 行の仕様書のうち 180 行（43%）を占めており、しかも見出しの
> 「本コミットで」は複数コミットにまたがった時点で既に嘘になっていた。
> 仕様書は「今どうであるか」を書く場所なので、記録はここへ分離した。

## 実装済み改善一覧

- **[実装] I26 (W7 完了 — 選んだアバターを本体 GUI が描画):**
  `--avatar-loader` で選んだモデルを本体 3D GUI が実際に描画するよう統合。
  新規 `avatar_model_store.py`（cwd 非依存の canonical な選択履歴・アトミック
  保存・拡張子/実在チェック付き解決）を受け渡し口として `avatar_loader.py` と
  `avatar_3d_autonomous_tts.py` を接続。`gltf_utils.load_first_mesh_vertices` を
  実 pygltflib 1.16（GLB の頂点は `Buffer.get_data()`/`.data` ではなく
  `gltf.binary_blob()` にある）に対応させ、bufferView/accessor のオフセットも
  尊重するよう修正（この不整合で従来は実 GLB を渡しても何も描画されなかった）。
  `gltf_utils.normalize_vertices` で重心中心・最大半径 1 に正規化。`GLTFModel`
  の読み込みを try/except で保護し、存在しない/壊れたファイルでもクラッシュせず
  球体へフォールバック。GUI に `/avatar` コマンド追加。テスト 30 件超追加
  （store・normalize・実 GLB 往復・ロード堅牢性・コマンド）。
- **[実装] I25 (W7 解消 — 既定起動が本体 GUI に繋がっていなかった):**
  `satin_launcher.py` の既定モードを `avatar_loader.AvatarLoaderApp`（ファイル
  選択のみで何も起動しない tkinter ダイアログ）から、TTS・好感度・会話ログ・
  スラッシュコマンドを持つ本体 GUI (`avatar_3d_autonomous_tts.MainWindow`) の
  起動 (`_launch_avatar_gui`) に変更。旧ダイアログは `--avatar-loader` で引き
  続き利用可能。3D モデル読み込み（glTF/VRM の実パース・描画）を本体 GUI に
  統合する作業は別途の設計判断が必要なため対象外（`avatar_3d_gltf_viewer.py`
  にのみ実装済み、ワイヤーフレームのみ）。テスト 4 件追加（既定モードの
  dispatch・`--avatar-loader` の dispatch・import 失敗時のエラー処理）。
- **[実装] I23 (新機能 — ユーザーの気分への寄り添い / wellbeing):** ソクラテス式
  問答（「コンパニオンが chatbot ではなく『生きている』と感じる要素は？」→ 記憶
  ＋自発性＋**あなた固有の共感**）から導出。`mood.py` がアバターの好感度を扱う
  のに対し、新規 `user_wellbeing.py` は**ユーザー自身の最近の気分**を会話ログの
  発話感情から推定し、落ち込み時はそっと気づかい・上向き時は一緒に喜ぶ一言を返す
  （データ不足・中立時は何も言わない）。感情分類は `mood.classify_sentiment`
  （新設の純関数）を単一の真実の源として再利用し LLM 非依存。CLI に
  `/feeling`（別名 `/checkin`）コマンドを追加。テスト 24 件追加。
- **[実装] I24 (I23 の改良 — wellbeing の自発化):** S/W/I 分析で「リアクティブ
  のみ（`/feeling` を打たないと働かない＝ソクラテスの自発性が欠落）」を最大の
  短所と特定。セッション開始のあいさつ直後に、明確なトレンドがある時だけ寄り添い
  の一言を**自発的に**添えるよう `run_chat` を改良（トレンド無し/データ不足/mood
  無効時は無言で通常あいさつを邪魔しない）。集計は実際の書き込み先 `conv_log` を
  参照しテスト容易性も確保。テスト 3 件追加（low トレンド時に追加・無トレンド時
  沈黙・mood 無効時沈黙）。残課題: GUI 連携、ログ全走査の効率化。


- **[実装] I22 (静的解析 ruff 由来 — 未使用 import のクリーンアップ):** `ruff`
  (F401) の **安全な autofix のみ**（`[*]` 印付き 199 件）を適用し、74 ファイルから
  純粋に未使用の import を除去。`try: import x; X_AVAILABLE=True` 形式の可用性
  プローブ（19 件）は ruff が autofix 対象外として保守的に保持。あわせて
  `logging_manager` の陳腐化したテスト（未使用になった `time` import の存在を
  要求していた）を実態（`threading` のみ必要）に合わせて更新。
- **[実装] I21 (静的解析 ruff 由来 — `List` 未 import で plugin が import 不能 +
  lint ゲート導入):** `ruff` (F821) で `plugins/cloud_backup.py` が戻り値注釈に
  `List[...]` を使うのに `from typing import` へ `List` が無く（`__future__
  annotations` も無し）、google-cloud-storage 導入環境で **モジュール import 時に
  `NameError`** になる実バグを検出・修正。あわせて、今セッションで見つけた
  F821/B006/B904 級のバグを将来自動検出するため `ruff.toml` を新規追加。
  correctness 系ルール（B006/B904/E711-714/E722/F811/F821/F823/PLE）を enforced
  set として緑に保ち、CI/pre-commit ゲート化できる状態にした（F401/F841 等の
  hygiene 系は将来クリーンアップ対象として除外）。
  参考: [Python のセキュリティ/品質を静的解析で守る — ruff/Bandit (Qiita kina006097)](https://qiita.com/kina006097/items/436c012504b1d60a5c5f)
- **[実装] I20 (静的解析 ruff 由来 — 例外チェーン欠落 B904):** `except` 節内で
  別の例外を送出する際 `from e` を付けず、元例外のトレースバックが失われていた
  18 箇所を修正（`config_validator` / `plugin_manager` / `config_version_manager`
  / `backup_scheduler` / `schema_validators` / `config/schema`）。`raise ... from e`
  で連鎖を保持し、設定読込・プラグイン・バックアップ失敗時の根本原因追跡を
  容易にした（純加算的変更で挙動不変）。
  参考: [例外の再送出と from / 例外チェーン (Qiita hasoya)](https://qiita.com/hasoya/items/05d4e49d492869875cca)
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

