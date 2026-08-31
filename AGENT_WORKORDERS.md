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
- **削除候補メモの類を根拠にコードを消さないこと。** かつて
  `main/README_REMOVE.txt` がフラグシップ GUI（`avatar_3d_autonomous_tts`）を
  削除候補に挙げていた（W-05 で撤去済み）。到達性は import グラフで確かめる。

### 0.2 このリポジトリの作業規約（必守）
1. **1 機能 = 1 コミット**。
2. **revert-verify**: テストを追加したら、修正コードを `git stash` して「修正が無いと
   新テストが落ちる」ことを必ず確認してから戻す。落ちないテストは無意味。
3. コミット前に **`python check.py` が緑**であること。これ 1 本が「緑の定義」で、
   py_compile / ruff / mypy / pytest / 設定検証 / 起動スモークを実行する（約 10 秒。
   編集中は `--fast` で起動スモークを省ける）。CI も同じコマンドを呼ぶので、
   手元が緑なら CI も緑になる。
   件数はここに書かない — かつて「2,939 件」と書かれていたが実数と乖離していた。
   コミットごとに変わる数を人手で同期し続けるのは負け戦である。
4. **実データ汚染禁止**: `tests/conftest.py` の autouse 隔離（会話ログ・ユーザー
   プロフィール・好感度）を壊さない。テスト実行後に `config/mood.json` /
   `config/mood_history.jsonl` / `config/user_profile.json` /
   `avatar_event_log.jsonl` が変化していないことを確認する。
   既定パスの解決そのものを検証したいテストだけが `@pytest.mark.real_paths` で
   隔離を外せる（差し替え後のパスを検証しても何も確かめたことにならないため）。
5. optional-import は既存様式に従う（`try: import X except Exception: X = None` →
   利用側でガード）。
6. ユーザー向け応答は必ず `_speak_reply()`（GUI）/ 対応する出力関数を経由し、
   `lang`（`persona.lang`）で日英を出し分ける。
7. ファイル保存は個人データなら 0600（`fsutil` / 各モジュールの `_atomic_write` を
   再利用）。
8. 作業ブランチから push → PR → `master` へ **merge**（履歴保持のため squash 不可）。
   ブランチ名はここに固定しない（セッションごとに変わる）。

---

## 1. 長所（維持すべき設計資産）

| # | 長所 | 根拠 |
|---|------|------|
| S1 | **no-LLM / オフライン / プライバシー第一**を貫いた決定論的な対話・感情・記憶 | `mood.py` / `conversation_log.py` / `user_wellbeing.py` |
| S2 | **研究駆動の安全設計**: 感情依存ガードレール・否定/強度対応感情判定・BM25 記憶想起・変化点検知・概日トーン・**別れぎわの引き止め文句ゼロ**・**再会時に不在を責めない**・**危機表明への相談先案内**・**日常のつらさへの共感**・**AI であることの定期開示**・**好感度の向き先補正**・**告白に実体のある関係を要求** | `usage_guardrails.py`, `mood.py`, `conversation_log.search_relevant`, `user_wellbeing.wellbeing_shift`, `persona.py`, `farewell_integrity.py`, `crisis_support.py`, `everyday_distress.py`, `ai_disclosure.py`, `sentiment_target.py`, `data_erasure.py`, `tests/test_greeting_integrity.py`、
両インターフェースの一致は `tests/test_interface_parity.py`。一覧は SPECIFICATION §3.8、詳細は `RESEARCH_DRIVEN_IMPROVEMENTS_PY.md` |
| S3 | **完全なデータ消去経路 + 保存期間**（プライバシーの実効性）: GUI `/forget-all` と CLI `data purge` が会話・好感度・プロフィール・アバター履歴を一括消去。加えて `conversation_retention_days` で時間軸の保持上限（既定 0 = 無期限） | `avatar_3d_autonomous_tts._erase_all_user_data`, `manage_satin.cmd_data_purge`, `log_retention.py` |
| S4 | **強固なテスト文化**: 2,939 件、revert-verify 規約、conftest によるデータ隔離、optional-import フォールバック様式 | `tests/`, `tests/conftest.py` |
| S5 | **セキュリティ修正済み**: CSRF・SSRF・CSV 式インジェクション・Zip Slip・原子的書き込み・0600 権限 | `dashboard.py`, `fsutil.py` ほか（CHANGELOG / SPECIFICATION 参照） |
| S6 | **単一エントリポイント + 依存の single-source** | `satin_launcher.py`, `dependency_manifest.py` |
| S7 | **多言語対応（会話 + GUI クローム）** | 全 `_cmd_*_gui` と `MainWindow._autonomous_label` が `lang` 出し分け |

---

## 2. 短所サマリ（詳細は §3 の各カード）

| ギャップ | 深刻度 | カード |
|----------|--------|--------|
| ~~多重起動ガードが無い（同時書き込みでデータ破損しうる）~~ ✅**実装済** | 高 | W-01 |
| ~~GUI 終了処理が不完全（スレッド join なし・タイマー停止なし）~~ ✅**実装済** | 高 | W-02 |
| ~~**危険な誤った削除メモ** `README_REMOVE.txt`~~ ✅**撤去済** | 高 | W-05 |
| ~~`__version__` 不在・`--version` フラグ無し~~ ✅**実装済** | 中 | W-03 |
| ~~孤児モジュール（`sync_to_cloud` 等）の整理~~ ✅**完了（59 モジュール削除）** | 中 | W-04 |
| ~~dashboard の多言語対応状況が未検証~~ ✅**検証・実装済** | 中 | W-06 |
| ~~型チェック（mypy）未導入~~ ✅**完了（main/ 全 37 モジュールを検査・免除リストは空）** | 中 | W-07 |
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
- ~~`sync_to_cloud`（Google Drive / Dropbox アップロード）~~ → W-04 で削除済み。
- ~~誤った削除メモ `README_REMOVE.txt`~~ → W-05 で撤去済み。

---

## 3. ワークオーダー（作業指示カード）

各カード形式: **背景 → 対象 → 実装前チェック → 実装方針 → テスト → 完了条件 → 触るな**

### W-01: 多重起動ガード（single-instance lock） — ✅**完了**

`main/single_instance.py` + `tests/test_single_instance.py`。`config/satin.lock`
に PID を書くロックファイル方式で、GUI の二重起動による `config/mood.json`・
会話ログ・`user_profile.json` の並行書き込み破損を防ぐ。

### W-02: closeEvent の完全シャットダウン — ✅**完了**

`main/avatar_3d_autonomous_tts.py` の `closeEvent` で全タイマーを停止し、
`tts_thread.stop()` + `join(timeout=2.0)` を行う。終了時にスレッドが取り残されない。

### W-03: `__version__` の単一宣言 + `--version` — ✅**完了**

`main/version.py` が唯一の真実の源で、`config/config.json` の `version` を読む。
`satin_launcher.py --version` で表示。`tests/test_version.py` が両者の一致を守る。

### W-04: 孤児モジュールの整理 — ✅**完了**

import グラフ（AST ベース）で到達不能なモジュールを判定し、**59 モジュール**と
複数のディレクトリを削除した。到達可能なコードは 1 行も減っていない。

**削除したもの（分類）**
- **ネットワーク統合層**: `youtube_integrator` / `paper_integrator` /
  `web_integrator` / `content_aggregator` / `async_integrator` /
  `sync_to_cloud`。「ローカル完結・オフライン・プライバシー第一」という
  第一原理と正面衝突しており、かつ参照ゼロだった。
- **サービス基盤**: サーキットブレーカ・レート制限・リトライ戦略・
  可観測性・プロファイリング・DI コンテナ・タスクスケジューラ・
  キャッシュ管理・ロギング管理ほか。単一ユーザーのデスクトップアプリに
  マイクロサービスの装備が積まれていた。
- **設定の多層化**: `config_manager` 系 6 モジュールと `main/config`
  パッケージ（§SPECIFICATION 3.4 参照）。
- **プラグイン機構**: `plugin_manager` / `plugin_base` / `plugin_system` /
  `plugins`。最後に残っていた `main/plugins` 配下の `cloud_backup` も削除した
  （参照ゼロ・パッケージ初期化ファイルすら無く・削除済みの `config_manager` を
  import するため import 不能・そのうえ Google Cloud Storage へユーザーデータを
  アップロードする内容だった）。`config/config.json` の `plugins` 配列も
  読み手が居なくなったので削除。
- **バックアップ機構**: `backup_manager` / `backup_scheduler` / `backup_cli`。
  手動の `manage_satin backup` とダッシュボードの `/sync` が残っている。
- **重複ビューア 7 本**: `avatar_3d_autonomous` / `avatar_3d_sync` /
  `avatar_3d_viewer` / `avatar_3d_gltf_viewer` / `autonomous_gltf_avatar` ほか。
  フラグシップは `avatar_3d_autonomous_tts` のみ。
- **ロケール 16 ファイル**: ルート直下にあった `locales` ディレクトリと
  `main/{ar,bn,…,zh}.json`。
  生きているのは `main/i18n/locales/{ja,en}.json` だけだった。**W-06 カードが
  編集先として指していたのは死んだほう**で、そこへキーを足しても実行時には
  一切効かなかった。

**この作業で得た教訓（次に大量削除をする人へ）**
1. **テストの削除をパターンマッチで決めない。** `grep -rl "\bconfig\b" tests/`
   が `conftest.py` を含む 44 ファイルに一致し、無関係なテストを巻き込んで
   消しかけた。正しい信号は `pytest --collect-only` の ERROR 出力だけである
   — 「対象が消えたので収集できない」テストだけが削除対象。
2. 削除の根拠は**コミットメッセージに列挙する**。後から「なぜ消したか」を
   git log だけで再構成できる状態にしておく。
3. 迷ったら消さない。可逆とはいえ、復元コストは非対称である。

### W-05: 危険な `README_REMOVE.txt` の撤去 — ✅**完了**

`main/README_REMOVE.txt` を削除した。フラグシップ GUI
（`avatar_3d_autonomous_tts`）を「削除候補」として挙げる誤ったメモで、
信じたエージェントが製品本体を消しかねなかった。

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
     `main/i18n/locales/{ja,en}.json`。ルート直下にあった locales ディレクトリ
     （18 キー）は参照ゼロの孤児で、ここへキーを足しても実行時には一切効かな
     かった（W-04 で撤去）。
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
- **最終状態**: **免除リストは空**。`mypy.ini` に `ignore_errors` セクションは
  1 つも無く、`main/` の全モジュールが検査対象である（W-04 の削除で母数が
  94 → 37 に減ったことと、残りを 3 段階で潰したことの両方による）。
  条件付き基底クラス 2 箇所の `# type: ignore[misc]` だけが唯一の局所的な逃げ。
- **見つかった実バグ（同コミットで修正）**: `user_wellbeing` と `usage_guardrails` の
  optional-import フォールバック `_find_archives` が、本物（`conversation_log`）の
  引数名 `logfile` に対し `path` と名乗っていた。**キーワード呼び出しが
  フォールバック時だけ TypeError になる**という、通常経路では絶対に表に出ない不整合。
  免除を削る過程でさらに 4 件: `backup_scheduler._apply_retention` の `int <= None`、
  `youtube_integrator._get_video_info_api` の `None.videos()`（どちらも呼び出し側
  だけがガードしていてメソッド単体では落ちる形）、
  `advanced_error_handling.rotate_proxy` の `-> str` 宣言で `return None`、
  `DependencyContainer._scopes` の注釈が `List[ServiceScope]` なのに実体は
  weakref（**コードが正しく注釈が誤っていた**ケース）。
- **CI（済）**: `python check.py` が mypy を**引数なし**で起動する。対象は
  mypy.ini が決めるので、コマンドラインにファイルを並べて検査漏れが起きる余地を
  作らない。`setup/requirements.txt` に `mypy>=1.8` / `ruff>=0.4` を追加。
- **テスト（済）**: `tests/test_mypy_config.py` は mypy を起動せず設定だけを守る
  — 存在しないモジュールへの陳腐化した免除、免除の重複、中核モジュール
  （対話・記憶・安全系）が免除リストへ紛れ込むこと、免除が過半数を超えること、
  ゲートがファイル名を並べて mypy を起動していないこと、CI が check.py へ
  委譲していること。加えて `tests/test_usage_guardrails.py` にフォールバック
  署名の実行時テスト（`conversation_log` を import 不能にしてリロードし、
  スタブを実際に検証）。
- **`warn_unused_ignores` を有効にしていない理由**: 任意依存のフォールバック行
  （`QOpenGLWidget = None` など）では、パッケージが入っていれば ignore が必要で、
  入っていなければ不要と**環境で反転する**。このチェックを入れると環境依存の
  失敗を生むので入れない。環境に関係なく死んでいた ignore 8 件は削除済み。
- **免除を再び足したくなったら**: まず
  `python -m mypy --config-file=/dev/null --ignore-missing-imports
  --follow-imports=silent main/<module>.py` で素の指摘を見て、直せないか考える
  こと（設定を噛ませると免除が効いて何も出ない）。mypy.ini にセクションが
  1 つも無い状態が正常であり、増えたら退行である。

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
  2. `autonomous_gltf_avatar`（当時存在した別ビューア。W-04 で削除済み）の
     自前インデックス読み出しが 3 通りに壊れていた（本カードが警告していた
     `.data` 誤用に加え、uint16 決め打ち・byteOffset 無視）。共通実装へ寄せて解消。
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
4. 依存 lock ファイル生成（`pip-tools` / `uv`）と Dependabot 設定
   （CI と同じく `.github` 配下。作成にはリポジトリ所有者の操作が必要）。

---

## 5. 現在地と次にやること

**W-01 〜 W-08 はすべて完了した。** 残る作業は 2 種類しかない。

1. **オーナー専用作業（§4）** — CI の有効化・タグ / Release・lock ファイル。
   このうち CI 有効化は最優先である。ゲート（`python check.py`）は既にあるが、
   `.github/workflows/` が無いため**一度も自動実行されていない**。それまでの
   唯一の防波堤は各自が手元で `check.py` を回すことで、これは規律に依存する。
2. **W-90（Tier B/C: ローカル ML / TTS / LLM）** — 実装前に人間の承認が必須。
   §0.1 の設計境界（no-LLM / オフライン / プライバシー第一）に触れるため。

新しいギャップを見つけた場合は、既存カードの様式（背景 / 対象 / 実装前チェック /
実装方針 / テスト / 完了条件 / 触るな）で追記すること。カードが完了したら
本文を未来形のまま残さず、**何をしたかの記録に畳む**（W-01 〜 W-05 がその形）。
未来形の指示が残っていると、次のエージェントが済んだ作業をやり直す。

### イーロン・マスクの 5 ステップアルゴリズム（本リポジトリの改善手順）

このリポジトリの直近の大規模改善は、**イーロン・マスク思考法**（Elon Musk の
5 ステップアルゴリズム／第一原理思考）に沿って進めた。順序に意味があるので、
次に着手する人も同じ順で回すこと。

1. **すべての要件を疑う（Question every requirement）**
   要件には必ず出所の人間がいる。「昔からこうなっている」は理由ではない。
   本リポジトリでは、ドキュメントの主張・製品の振る舞い・安全機構の適用範囲を
   一つずつ「これは何のためか」と問い直した。最も収穫が大きかったのは
   **実際に起動して一行ずつ読む**ことである（下記「ギャップの見つけ方」）。
2. **部品や工程を削除する（Delete any part or process you can）**
   「10% は戻すことになる。戻す量が足りないなら、削り足りていない。」
   到達不能な 59 モジュールに加え、**到達可能だが何もしていない**もの
   （通知サブシステム・ログ監視デーモン・Web 専用モジュール内のデスクトップ
   フォント表）も削除した。参照されているかではなく、何をしているかで判断する。
3. **簡素化・最適化する（Simplify and optimize）**
   **削除の後に行う。** 存在すべきでないものを最適化するのが典型的な誤りである。
   mypy の免除をゼロに、GLU 依存を必須経路から排除、GUI と CLI で割れていた
   文言を 1 箇所へ集約した。
4. **サイクルタイムを縮める（Accelerate cycle time）**
   `python check.py` が約 10 秒で全検証を終える。`--fast` で起動スモークを省ける。
5. **自動化する（Automate）**
   **最後に行う。** 手順が正しいと分かってから自動化する。検証ゲート・
   ドキュメントの死んだ参照検出・台詞の操作的表現の走査・GUI と CLI の
   突き合わせ・GUI 実起動スモーク（xvfb で自律モードを回し座標が可視範囲に
   留まることを確認）を、いずれも毎回の実行で行う形にした。

各ステップの適用にあたっては**ソクラテス問答法**を検証手段として併用した —
主張（「この部品は必要」「この挙動は正しい」）を問いで崩し、実測かテストで
答えられたものだけを採用する。その形式で行ったプロダクト全体の
長所・短所・改善点の棚卸しは `PRODUCT_REVIEW.md` にある。未着手の改善は
すべて同文書 §3 の表（Tier と適用ステップつき）に集約されている。

### ギャップの見つけ方（実績のある手順）

コードを読むだけでは見つからない欠陥がある。**まっさらな状態から実際に起動し、
ユーザーが通る道を一行ずつ読む**と出てくる。この方法で見つかったもの:

- 一度も会ったことのない相手への「おかえり！」（初回起動）
- 「またね！ところでストレス発散は？」（別れに質問を連結）
- 悪い知らせへの「そっか、いいね。」（フォールバックが一律で明るい）
- 出会って 3 メッセージでの愛の告白（好感度だけが条件だった）
- close レベルの挨拶 3 択すべてが不在を責める型
- /stats の「今回: 0 / 累計: 4」（同じ語で違う定義の数を並べていた）
- /summary だけ好感度が空欄（/mood には出ている）

手順:
1. `check.py` の `_personal_data_preserved()` で個人データを退避してから、
   `config/` の好感度・履歴を消して**新規ユーザーの状態**を作る。
2. `--chat` を日英それぞれで起動し、出力を一行ずつ読む。速く動かさない。
3. ダッシュボードは全ルートを両言語でレンダリングし、内部キー（`friendly` 等）や
   テンプレートの波括弧が漏れていないか見る。
4. 好感度を上げ切って高レベルの応答も読む。**最も熱心なユーザーが見る画面**は
   検証が手薄になりやすく、実際そこに集中して欠陥があった。
5. 特別イベント（告白・記念日・レベル節目）は自然には発火しないので、
   条件を作って明示的に発火させる。

各カードは 1 機能 = 1 コミット、revert-verify、`python check.py` が緑、
PR → master merge の規約（§0.2）で進めること。
