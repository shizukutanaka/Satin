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
| S2 | **研究駆動の安全設計**: 感情依存ガードレール・否定/強度対応感情判定・BM25 記憶想起・変化点検知・概日トーン・**別れぎわの引き止め文句ゼロ**・**危機表明への相談先案内**・**AI であることの定期開示**・**好感度の向き先補正** | `usage_guardrails.py`, `mood.py`, `conversation_log.search_relevant`, `user_wellbeing.wellbeing_shift`, `persona.py`, `farewell_integrity.py`, `crisis_support.py`, `ai_disclosure.py`, `sentiment_target.py`。詳細は `RESEARCH_DRIVEN_IMPROVEMENTS_PY.md` |
| S3 | **完全なデータ消去経路 + 保存期間**（プライバシーの実効性）: GUI `/forget-all` と CLI `data purge` が会話・好感度・プロフィール・アバター履歴を一括消去。加えて `conversation_retention_days` で時間軸の保持上限（既定 0 = 無期限） | `avatar_3d_autonomous_tts._erase_all_user_data`, `manage_satin.cmd_data_purge`, `log_retention.py` |
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
| 孤児モジュール（`sync_to_cloud.py` 等）の整理 🔸**ロケール 16 ファイルは削除済** | 中 | W-04 |
| ~~dashboard の多言語対応状況が未検証~~ ✅**検証・実装済** | 中 | W-06 |
| ~~型チェック（mypy）未導入~~ ✅**導入済（73/94 モジュールを検査・免除リストは削減中）** | 中 | W-07 |
| ~~3D 描画がワイヤーフレーム止まり（面・法線・シェーディング無し）~~ ✅**実装済** | 低 | W-08 |
| CI 未有効化・lock ファイル無し（オーナー/方針事項） | — | §4 |
| Tier B/C（ローカル ML / TTS / LLM）は要方針判断 | — | W-90 |

---

## 2.5 第一原理からの分析（First Principles）

チェックリスト比較ではなく、「**この製品は根源的に何のためにあるか**」から必要機能を
導出し、実コードと突き合わせた結果。

**還元不能な目的**: ユーザーが向き合ったときに *そこにいて*、*自分を覚えていて*、
*意味のある反応を返し*、*依存させて害を与えず*、*プライバシーを守る* 存在。

導かれる必須能力と充足状況:

| 必須能力 | 根拠 | 状況 |
|----------|------|------|
| **存在**（起動して見える・状態が持続する） | 目的の前提 | ✅ 既定起動が本体 GUI（PR #2）、モデル描画（#3）、多重起動ガード（#8） |
| **記憶の永続性**（クラッシュしても関係が消えない） | 「覚えている」が成立する条件 | ✅ 検証済: 好感度は `speak_comment` 内で毎ターン保存、会話ログは追記型。graceful exit 依存ではない |
| **反応**（入力に意味ある応答） | 目的の中核 | ✅ 辞書/ルール応答 + BM25 記憶想起 |
| **安全**（依存を助長しない） | 2025-26 研究の第一級課題 | ✅ A1 ガードレール |
| **プライバシー**（ローカル完結・完全消去可能） | 製品の売り | ✅ `/forget-all`・`data purge`（#4） |
| **価値の発見可能性**（ユーザーが「何ができるか」を知れる） | どんなに優れた能力も、**知られなければ存在しないのと同じ** | ❌ → ✅ **本イテレーションで解消** |

### 発見: 価値が初回接触時に不可視だった（最重要の不足）
初回起動でユーザーが見るのは (a) 静止アバター、(b)「自律モードON」という内部用語の
ボタン、(c)「コメントを入力して Enter で**読み上げ**」というプレースホルダ **のみ**。
自律モードは既定 OFF（`is_autonomous = False`）、`talk_label` は空文字で開始するため
**アバターは沈黙・静止**。唯一の手がかりであるプレースホルダが *TTS ツール* を示唆する
ため、記憶・好感度・スラッシュコマンドという中核価値が一切見えないまま離脱しうる。
コードベース全体に初回オンボーディングは存在しなかった（grep 済み）。

**対処（実装済み）**: `first_run.py` を追加し、過去の利用痕跡（交流回数・呼び名・
会話履歴）が **1 つも無いときだけ** アバター自身の台詞で「できること」を案内。
プレースホルダも「話しかけて Enter — 「/help」で使えることの一覧」へ改訂。

### 過剰（あるべきでないもの）
- `sync_to_cloud.py`（Google Drive / Dropbox アップロード）: **参照ゼロ**かつ
  「ローカル完結・プライバシー第一」という第一原理と正面衝突。→ W-04 で整理対象。
- 誤った削除メモ `README_REMOVE.txt` → W-05 で撤去済み。

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

### W-04: 孤児モジュールの整理 — [難易度 S / 優先度 中] — 🔸**一部完了**
- **完了分（ロケールファイル 16 個を削除）**: W-06 の調査で、ロケールファイルが
  3 世代並存していたことが判明した。生きているのは `main/i18n/locales/{ja,en}.json`
  のみ。削除したのは以下で、いずれもリポジトリ全体 grep で**コード参照ゼロ**:
  - ルート `locales/{ja,en}.json`（18 キー）— dashboard が使う 37 キーのうち 27 が
    欠落し、共通キーのうち 4 つは値がドリフト。**W-06 カードが編集先として指していた
    のはこれ**で、ここへキーを足しても実行時には一切効かなかった。
  - `main/{ar,bn,de,en,es,fr,hi,id,ja,ko,pt,ru,ur,zh}.json`（14 ファイル）— 別のキー
    空間（`menu_file`/`btn_ok`/`ng_words` 等、全キーが grep 0 件）。`i18n.py:94` の
    コメントアウト済み tkinter デモの残骸で、`main/{ja,en}.json` は
    `msg_loading`/`msg_error`/`msg_success` を**二重定義**している。
  - 両者とも初期コミット (b69d170) 以来未更新。`main/i18n/locales/` は更新継続中。
- **残り（未着手）**: 以下は本カードの元の対象のまま。着手時は下記「実装前チェック」の
  grep を必ず再実行すること。
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

### W-06: dashboard の多言語対応 — ✅**完了**
- **調査結果（このカードの前半）**: 懸念だった「英語ユーザーに日本語ダッシュボード」は
  **ほぼ杞憂**だった。dashboard は既に `i18n.t()` を 37 キーで使い、両ロケールに全キーが
  存在していた。ただし 3 つの実在の問題が見つかった:
  1. `/stats`・`/summary` と CSV リンク 2 箇所（計 16 対 32 リテラル）が
     `if is_en else` の直書きターナリ。切り替わりはするが第三言語を追加できず、
     `{name} replies` / `{name}の返答` の語順もコードに固定されていた。
  2. **生の内部レベルキーの漏れ**: `mood_history.jsonl` の `level`/`prev_level` は
     `"friendly"` 等の英語識別子で保存されるため、日本語 UI に英語が混ざっていた
     （/mood・/mood/history・/summary の 4 箇所）。時刻軸の `00h` も英語固定。
  3. **このカード自身が死んだディレクトリを指していた**: 実際に読まれるのは
     `main/i18n/locales/{ja,en}.json`。ルート `locales/`（18 キー）は参照ゼロの孤児で、
     ここへキーを足しても実行時には一切効かない（W-04 で撤去）。
- **実装（済）**: 上記 32 リテラルを `main/i18n/locales/{ja,en}.json` の 15 新キーへ移設。
  `mood.level_label(level_key, lang)` を追加（`_LEVELS` を単一の真実の源に保つ）し
  dashboard の 4 箇所で使用。`get_lang()` に Accept-Language 折衝（RFC 9110）を追加し、
  優先順位を `?lang → session → SATIN_LANG → Accept-Language → OS ロケール → en` に。
- **テスト（済）**: `tests/test_dashboard_i18n.py`（30 件・レンダリング + 折衝 +
  `level_label`）、`tests/test_i18n.py` に ja/en キーセット一致・ネスト構造一致・
  `{name}` プレースホルダ保持を追加。`_DASHBOARD_KEYS` は**陳腐化していた**ため
  （32 件のハードコードに対し実使用 37 件）dashboard.py のソースから導出する方式へ変更。
- **触らなかったもの**: セキュリティヘッダ（`no-store`）・CSRF トークン処理・
  `_render_page` の SSTI 対策・`?lang` の {en,ja} クランプ。

### W-07: mypy の段階導入 — ✅**完了**
- **実装（済）**: `mypy.ini` を新設。カード当初案の「検査対象を列挙する」方式ではなく
  **逆向き**にした: `files = main` で既定を全件検査とし、まだ通らないモジュールだけを
  `ignore_errors` で免除列挙する。列挙する側を「これから直すもの」にしておくと
  リストは縮む方向にしか動かず、**新規モジュールは黙って検査対象外にならない**。
  （検査側を列挙する設計の失敗例が同じリポジトリにある — `tests/test_i18n.py` の
  `_DASHBOARD_KEYS` は 32 件のハードコードのまま実使用 37 件に取り残されていた。）
- **導入時点の実績**: main/ 94 モジュール中 **52 がクリーン**、42 を免除。
  免除の大半は GUI/3D ウィジェット（`QOpenGLWidget if X is not None else object`
  の条件付き基底クラスを mypy が解けない）と Web/インフラ系。
- **見つかった実バグ（同コミットで修正）**: `user_wellbeing` と `usage_guardrails` の
  optional-import フォールバック `_find_archives` が、本物（`conversation_log`）の
  引数名 `logfile` に対し `path` と名乗っていた。**キーワード呼び出しが
  フォールバック時だけ TypeError になる**という、通常経路では絶対に表に出ない不整合。
  他に `plugin_system.PluginManager.modules` の注釈欠落（隣の `plugins` は注釈済み）、
  `single_instance` の `ctypes.windll`（Windows 専用属性・type: ignore で明示）。
- **CI（済）**: `setup/github-actions-ci.yml` に ruff と mypy のジョブを追加。
  mypy は**引数なし**で起動する（対象は mypy.ini が決めるので、コマンドラインに
  ファイルを並べて検査漏れが起きる余地を作らない）。`setup/requirements.txt` に
  `mypy>=1.8` / `ruff>=0.4` を追加。
- **テスト（済）**: `tests/test_mypy_config.py`（12 件）は mypy を起動せず設定だけを
  守る — 存在しないモジュールへの陳腐化した免除、免除の重複、中核モジュール
  （対話・記憶・安全系）が免除リストへ紛れ込むこと、免除が過半数を超えること、
  CI がファイル名を並べて起動していないこと。加えて
  `tests/test_usage_guardrails.py` にフォールバック署名の実行時テスト
  （`conversation_log` を import 不能にしてリロードし、スタブを実際に検証）。
- **免除リストの削減（継続中）**: 導入時 52/42 → **現在 73 モジュール検査 / 21 免除**。
  この過程でさらに実バグが 4 件見つかった:
  `backup_scheduler._apply_retention` の `int <= None`、
  `youtube_integrator._get_video_info_api` の `None.videos()`（どちらも呼び出し側
  だけがガードしていてメソッド単体では落ちる形）、
  `advanced_error_handling.rotate_proxy` の `-> str` 宣言で `return None`、
  `DependencyContainer._scopes` の注釈が `List[ServiceScope]` なのに実体は
  weakref（**コードが正しく注釈が誤っていた**ケース）。
- **次に進める人へ**: `python -m mypy --config-file=/dev/null --ignore-missing-imports
  main/<module>.py` で素の指摘を見てから直し、mypy.ini の該当ブロックを消す
  （設定を噛ませると免除が効いて何も出ないので注意）。残りは `error_handling`(5)・
  `observability`(7)・`config_manager_enhanced`(8)・`web_integrator`(10) 等。
  GUI/3D ウィジェット 9 件は条件付き基底クラスが主因なので、`# type: ignore[misc]`
  を 1 行足すだけで済むものが多い（`tts_with_virtual_audio` /
  `avatar_event_timeline_viewer` で実績あり）。
  GUI/3D ウィジェット群は条件付き基底クラスが原因なので `# type: ignore[misc]`
  を 1 行足すだけで済むものが多い（`tts_with_virtual_audio` /
  `avatar_event_timeline_viewer` で実績あり）。

### W-08: 3D 描画の強化（面 + 単色シェーディング） — ✅**完了**
- **実装（済）**: `gltf_utils` に `load_first_mesh_faces` / `load_first_mesh_normals`
  / `compute_face_normals` / `shade_factor` を追加し、
  `AutonomousAvatarViewer._paint_solid` が `GL_TRIANGLES` + 面ごとの拡散シェー
  ディングで描画する。`_load_model_geometry` が (頂点, 面, 面法線) を返し、
  面なしモデルは従来のワイヤーフレーム、モデル無しは球体へフォールバック。
  glTF 2.0 仕様準拠: `primitive.mode` 既定 4、5/6 は三角形リストへ展開
  （strip の交互巻き方向を補正しないと隣り合う面の陰影が反転する）、
  indices の componentType は 5121/5123/5125、`indices` 無しは 0..count-1 の
  暗黙連番、NORMAL 非搭載時はフラット法線をクライアント計算。
  シェーディングは `GL_LIGHTING` ではなく色の乗算で行い、他ウィジェットと共有
  している GL ステート（光源・マテリアル）を汚さない。
- **調査で見つかった実バグ 2 件（同コミットで修正）**:
  1. **`bufferView.byteStride` を無視していた**ため、POSITION と NORMAL を
     インターリーブした glTF で 2 頂点目以降が法線の値を座標として読まれ、
     モデルが崩れて描画されていた。仕様は「2 つ以上のアクセサが同じ bufferView
     を使う場合 byteStride 必須」なので、インターリーブは例外ではなく通常。
  2. `autonomous_gltf_avatar` の自前インデックス読み出しが 3 通りに壊れていた
     （本カードが警告していた `.data` 誤用に加え、uint16 決め打ち・byteOffset
     無視）。共通実装へ寄せて解消。
- **テスト（済）**: `tests/test_gltf_faces.py`（39 件）。実 pygltflib で GLB を
  組み立てる往復テスト（インターリーブ・5121/5123/5125・strip/fan・暗黙連番・
  範囲外インデックス・点/線モード）、法線計算とシェーディング係数の純関数テスト、
  GL 呼び出しをキャプチャした `_paint_solid` の検証。
- **触らなかったもの**: テクスチャ・スキニング・アニメーション（範囲外）。

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
