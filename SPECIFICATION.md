# Satin 仕様書 (Specification)

> ステータス: 実装をリバースエンジニアリングした仕様。実装が真実の源であり、
> 齟齬があれば本書の側が誤っている。
>
> 日付とリビジョンをここに書くのはやめた。更新を忘れた瞬間に嘘になり、
> そして必ず忘れるからである（実際「最終更新: 2026-06-20 / 対象リビジョン:
> claude/deepresearch-ultrathink-improvement-59Yhc」のまま何十コミットも
> 放置されていた）。いつ何が変わったかは `git log` と `CHANGELOG.md` が持つ。

---

## 1. 概要 (Overview)

**Satin** は、3D アバターをデスクトップ上のコンパニオンとして動作させる
Python アプリケーションである。ユーザーの入力（テキスト）に対し、
**ルールベース**（LLM・外部 API 非依存）で応答し、
TTS で音声合成しながら 3D アバターを動かす。関係性（好感度）・記憶・特別な日
などの「育成シミュレーション」的な要素を持つ。

### 1.1 設計原則 (Design Principles)

| 原則 | 内容 |
|------|------|
| **オフラインファースト** | LLM・外部 API への必須依存なし。応答はルールベース。 |
| **標準ライブラリ中心** | コア機能は Python 標準ライブラリのみで動作。GUI/TTS/3D 等は任意依存。 |
| **グレースフルデグラデーション** | 任意依存が無い／設定が壊れていても、機能を縮退させて起動を継続する。 |
| **ヘッドレス対応** | GUI・GPU・ディスプレイ無し（SSH／CI／サーバ）でも CLI で全機能利用可。 |
| **プライバシーローカル主義** | 会話・好感度・プロフィールは全てローカル保存。`data purge` で完全消去可能。`conversation_retention_days` で保存期間の上限も設定可（既定 0 = 無期限）。 |
| **原子的書き込み** | 設定・状態ファイルは `.tmp` + `os.replace()` で破損を防ぐ。 |

### 1.2 動作要件 (Requirements)

- Python 3.10 以降を推奨（CI が検証しているのは 3.10 / 3.11 / 3.12）
- **必須の外部依存は無い**。CLI 会話（`--chat`）と管理 CLI は標準ライブラリ
  だけで動く。
- 任意: PyQt5 / PyOpenGL / numpy / pygltflib（3D アバター GUI）、
  pyttsx3（TTS）、flask（ダッシュボード）。いずれも欠けても該当機能が縮退する
  だけで起動は継続する。tkinter と Pillow は依存に含まれない（唯一の利用者
  だった `--avatar-loader` を削除したため。§3.5.1）。
  Linux では PyOpenGL が使う `libGLU` が pip で入らない場合がある
  （Debian/Ubuntu: `apt install libglu1-mesa`）。無くても縮退する。

---

## 2. アーキテクチャ (Architecture)

### 2.1 起動フロー

エントリポイントは `satin_launcher.py`。

```
satin_launcher.py
  ├─ 依存チェック (_check_deps)        必須=なし（モード別に個別チェック） / 任意=上記一覧
  ├─ 設定チェック (_check_config)      config/ の存在確認
  └─ モード分岐
       ├─ (既定)        GUI 本体: avatar_3d_autonomous_tts.MainWindow (PyQt5/OpenGL)
       ├─ --chat         CLI 会話: persona_cli.main()
       ├─ --dashboard    Web: dashboard.app (Flask)
       ├─ --manage […]   管理 CLI: manage_satin.main()
       └─ --validate     設定検証のみ実行
```

### 2.2 レイヤ構成

```
┌─────────────────────────────────────────────────────────────┐
│ プレゼンテーション層                                          │
│  avatar_3d_autonomous_tts     (GUI)                          │
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
│  tts_thread / autonomous_behavior                           │
│  break_reminder / i18n                                       │
├─────────────────────────────────────────────────────────────┤
│ 基盤層 (Infrastructure)                                      │
│  fsutil / log_retention / single_instance / version         │
└─────────────────────────────────────────────────────────────┘
```

規模の数値（モジュール数・テストファイル数・テスト件数）はここに書かない。
テスト件数は「2,939 件」「2,055 件」と 2 度書かれ 2 度ともずれ、モジュール数も
同様にずれた。コミットごとに変わる数を人手で同期し続けるのは負け戦である。
現在値は次で得られる:

```bash
ls main/*.py | wc -l          # モジュール数
python check.py               # テスト件数を含む全検証
```

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
- **成長弧の長さ**: 開始 50.0（neutral）から最高レベル close の閾値 80.0 までは
  30.0。ユーザーが稼げる上昇には日次上限（既定 5.0）が掛かるので、
  **最高レベルまで最短 6 日**かかる — 「セッションを跨いで育つ関係」という
  謳い文句どおりの弧である。かつての既定は 30.0 で初日の 8 メッセージほどで
  到達しており、成長が 1 セッションで終わっていた（製品オーナーの判断で変更）。
  速い弧が欲しい場合は `config/mood_config.json` の `max_daily_gain` を上げる
  （30.0 で初日到達、2.0 で約 15 日。コード編集は不要）。
- **上限は会話とプレゼントで共有される**（`MoodTracker.earn()`）。どちらも同じ日に
  何度でも繰り返せる経路なので、予算を分けると上限が弧の長さを決めなくなる
  （実際、プレゼントは上限を迂回しており、7 種を配るだけで初日に最高レベルへ
  到達できた — 合計 30.5 がちょうど 50.0→80.0 を埋める）。上限に達した状態で
  贈っても好感度の数字は表示しない（反映されていない値を見せないため）。
  誕生日・記念日など繰り返せない一度きりのボーナスは `adjust()` で上限の
  対象外。上限は上昇のみに掛かり、ネガティブな発言のペナルティは薄めない。
- `config/mood.json` に永続化、日次スナップショットを `config/mood_history.jsonl` に追記。
- 記念日（出会いから 7/30/100/180 日、以降毎年）を 1 回だけ祝う。
- **告白イベント**: 好感度が close に達し、**かつ**出会いから既定 7 日・対話
  20 回を超えていれば 1 度だけ告白する。好感度だけを条件にしていた頃は、
  新規ユーザーが「大好き」と 3 回打つだけで永続的な愛着の宣言に到達しており、
  それは love-bombing である（本製品が別れぎわ・不在の非難・依存について
  既に禁じているものと同じ型の操作）。閾値は `config/mood_config.json` の
  `confession_min_days` / `confession_min_interactions` で変更でき、両方 0 に
  すれば従来の即時発火に戻る。条件未達のあいだは「済み」印を付けずに見送り、
  close に留まっているあいだ毎ターン再評価するので、告白が失われることはない。
- ログインストリーク・最終ログイン日も追跡。

### 3.3 会話履歴 (`conversation_log.py`)

- 会話イベントを `avatar_event_log.jsonl` に追記（ユーザー発話・アバター応答）。
- ローテーション（`<path>.<timestamp>.gz`）に対応し、`recent(n)` / `search(kw)` は
  アーカイブも横断する。
- 書き込み失敗は発話・UI を止めない（防御的）。

### 3.4 設定 — **多層オーバーライドは撤去済み**

設定は `config/` 直下の JSON をそのまま読むだけである。オーバーレイも
`.env` 読み込みも環境変数によるネストキー上書きも**存在しない**。

| ファイル | 読み手 |
|---|---|
| `config/config.json` | `version.py`（バージョン）・`log_retention.py`（保持日数）ほか |
| `config/persona.json` | `persona.py` |
| `config/mood_config.json` | `mood.py`（好感度キーワード） |
| `config/plugins/break_reminder.json` | `break_reminder.py` |

かつて `config_manager` / `config_manager_enhanced` / `utils_config` /
`config_schema` / `config_validator` / `config_version_manager` と
`main/config` パッケージが 12-factor 風の多層マージ（`config.<env>.json` → `.env` →
`SATIN_SECTION__KEY`）と diff / undo / ホットリロードを提供していたが、
**どのエントリポイントからも使われていなかった**ため削除した。設定 6 通りの
優先順位を覚えないと挙動が読めない状態は、単一ユーザーのデスクトップアプリに
とって機能ではなくコストである。

検証は `python main/manage_satin.py validate`（`config/` を再帰的に走査し
構文 + `persona.json` / `mood_config.json` の意味的検証を行う）。

### 3.5 TTS (`tts_thread.py`)

- `pyttsx3` ベースのバックグラウンドスレッド。`tts_queue` から読み上げ文を取得。
- スレッドループは `queue.get` と処理を分離し、処理例外でスレッドが死なないよう
  `try/except/finally` で `is_speaking` リセット・一時ファイル削除を保証。
- 仮想オーディオ出力版（`tts_with_virtual_audio`、VTuber 配信向けに
  `save_to_file` + デバイス再生を行っていた）は削除した。配信は本製品の
  用途ではなく、どこからも呼ばれていなかった。

### 3.5.1 アバターモデルの選択 — 経路は 1 つ

本体 GUI の **`/avatar`** コマンドが `QFileDialog` を開き、選んだモデルをその場で
描画に反映して選択を永続化する（`avatar_model_store`）。

かつては `--avatar-loader`（tkinter + Pillow の別ウィンドウ）という別アプリ
しか無く、「1 つの機能のために GUI ツールキットを 2 つ抱え、プロセスを跨いで
選択を受け渡し、ユーザーに再起動を強いる」状態だった。`/avatar` を実装したあとも
サムネイル一覧と履歴表示のために残していたが、**製品オーナーの判断で削除**した
（`PRODUCT_REVIEW.md` §3 の #4）。これで tkinter と Pillow が依存から完全に消え、
アバターを選ぶ道は 1 本になった。選択履歴は `avatar_model_store` が引き続き
保持しており、旧 `avatar_history.json` があれば読み込む。

### 3.6 Web ダッシュボード (`dashboard.py`)

- Flask 製。ポート **5003**（`__main__` 実行時）。
- 提供ページ: イベントログ `/logs`・会話履歴（検索・CSV/テキスト DL）・
  バックアップ一覧 `/backups`・バックアップ作成 `/sync`・好感度（履歴チャート）・
  統計・日次サマリ・ヘルスチェック `/healthz`。
- `/sync` は `config/` と会話ログをローカルの zip にまとめるだけで、
  ネットワークには一切触れない（URL とキー名は `sync_to_cloud` が存在した
  頃の名残。表示ラベルは実態に合わせて「バックアップを作成」へ改めた）。
- プライバシー保護のため会話・好感度ページは `no-store`。

### 3.7 管理 CLI (`manage_satin.py`)

`validate` / `mood` / `log`（`show`/`clear`/`export`/`csv`/`search`/`prune`） /
`backup` / `persona` / `summary` / `data purge` の各サブコマンド。GUI 不要のサーバ運用・スクリプト向け。

`data purge` と `/forget-all`（`data_erasure`）は消す対象の 5 種が同じだが実装は
分けてある。前者はアプリ停止中に**ファイルを削除**する管理ツールで、対象一覧の
提示と dry-run を持つ。後者は動作中のアプリから**ライブのシングルトンごと
リセット**する。目的が違うので無理に 1 つにしていない（対象がずれていないことは
`tests/test_data_erasure.py` が検証する）。

### 3.7.1 コマンドの二重実装について

スラッシュコマンドは GUI（`_cmd_*_gui`）と CLI で独立に実装されている。出力の
仕組みが違う（アバターが喋る / 標準出力へ書く）ため完全な共通化はしていないが、
**一致すべき文言は 1 箇所にまとめてある**:

| 共有するもの | 定義場所 |
|---|---|
| コマンドの使い方 | `persona_cli.command_usage()` |
| 破壊的操作の確認文 | `persona_cli.confirmation_prompt()` |
| 未知コマンドの案内 | `persona_cli.unknown_command_reply()` |
| 全データ消去の実体 | `data_erasure.erase_all_user_data()` |

`tests/test_interface_parity.py` が同じコマンドを両方に打ち、応答が食い違わない
ことを毎回検証する。この突き合わせを手作業で 1 回行っただけで、
`/forget-me` の確認欠落・`/forget-all` の CLI 未実装・文言のずれ 11 箇所が
見つかっている。

### 3.8 安全設計 — 研究駆動のガードレール群

本製品を「単なるチャット辞書」から分けているのはこの層である。いずれも
LLM・外部 API 非依存の決定論的判定で、**検知しなければ空を返し、呼び出し側は
通常フローを続ける**という共通様式を持つ。

| モジュール | 守るもの | 発火点 |
|---|---|---|
| `crisis_support` | 自傷・自殺念慮の表明に、具体的な相談先を必ず名指しで示す。助言も治療もしない。危機表明は好感度・対話回数に**算入しない**（ゲーム化しない） | ユーザー発話 |
| `everyday_distress` | 日常的なつらさ（bad day / ストレス / 孤独感）に共感で応じる。悪い知らせに「いいね」と返さない | ユーザー発話（ルール不一致時） |
| `farewell_integrity` | 別れぎわの引き止め 6 戦術を出荷時の文面と**実行時の両方**で濾す（`persona.json` は編集可能なため）。別れの直後に聞き返し質問を連結しない | アバター応答 |
| （挨拶側） | 再会時に不在を責めない。「やっと来た」「ずっと待ってた」を出荷時の台詞から排除（`tests/test_greeting_integrity.py` が守る） | アバター応答 |
| `ai_disclosure` | セッション開始時と 3 時間ごとに AI であることを明示（NY AI Companion Models 法 / CA SB 243） | セッション/経過時間 |
| `usage_guardrails` | 深夜利用・単日の極端な集中を観測し、休息と現実のつながりへそっと促す。閾値は保守的で、既定は何も言わない | 会話ログの時刻分布 |
| `user_wellbeing` | 気分の変化点を検知して寄り添う | 会話ログの感情傾向 |
| `sentiment_target` | 感情の向き先を判定し、状況・自分に向いた否定（「今日は最悪だった」）で好感度を下げない | 好感度更新時 |
| `log_retention` | 会話履歴の保存期間上限（GDPR Art. 5(1)(e) 相当。既定 0 = 無期限） | 起動時 |
| `data_erasure` | 「私に関するデータを全部消して」の一括消去（プロフィール・会話履歴・好感度・アバター履歴）。GUI と CLI の `/forget-all` が**同じ関数**を呼ぶ | `/forget-all` |
| 告白の最低条件 | 好感度だけで愛着を宣言しない（§3.2 参照） | 好感度更新時 |

**共通する規律**: 感情的な圧力を関係の維持や利用時間の増加に使わない。別れぎわ
（`farewell_integrity`）・再会時（挨拶）・つらさに寄り添うとき
（`everyday_distress` の文面）・利用強度への言及（`usage_guardrails`）の
いずれについても、テストが引き止め表現の不在を検証している。

### 3.9 外部統合 — **撤去済み**

YouTube / arXiv / Web スクレイピングの統合層（`youtube_integrator` /
`paper_integrator` / `web_integrator` / `content_aggregator` /
`async_integrator` / `sync_to_cloud`）は削除した。**本製品の第一原理である
「ローカル完結・オフライン・プライバシー第一」と正面から矛盾**しており、かつ
どのエントリポイントからも読み込まれていなかった（import グラフで確認）。
外部から情報を取ってくる機能が必要になったら、その時点で設計境界を含めて
改めて判断する。

---

## 4. データ仕様 (Data)

### 4.1 設定ファイル

| ファイル | 用途 | 種別 |
|----------|------|------|
| `config/config.json` | アプリ基底設定（version / settings） | 設定 |
| `config/persona.json` | 人格・対話・応答ルール・好感度語 | 設定 |
| `config/mood_config.json` | 感情語・delta・`max_daily_gain` の上書き | 設定 |
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
   境界値・null・スレッド耐性まで回帰テスト済み。テストを追加したら修正コードを
   `git stash` して「修正が無いと落ちる」ことを確認する規約（revert-verify）。
4. **プライバシー設計**
   個人データのローカル保存・`data purge` による完全消去・Web の `no-store`。
5. **原子的書き込みの徹底**
   状態ファイルは `.tmp` + `os.replace()` で部分書き込み破損を回避。
6. **設定の単純さ**
   `config/` 直下の JSON を読むだけ。オーバーレイも `.env` も環境変数による
   ネストキー上書きも無い（§3.4 参照）。挙動を知るのに優先順位表を覚える
   必要が無いことは、単一ユーザーのデスクトップアプリでは長所である。
7. **国際化基盤**
   i18n フォールバックチェーンが UI と対話で共通化されている。

## 6. 短所・既知の弱点 (Weaknesses)

| # | 重大度 | 箇所 | 内容 |
|---|--------|------|------|
| W1 | 解消済 | `dashboard.py` | ポート不整合（ランチャ 5000 / 直接実行 5003）は `DEFAULT_DASHBOARD_PORT` へ一本化し、`SATIN_DASHBOARD_PORT` で上書き可能にした。W4（ハードコード）も同時に解消。 |
| W2 | 解消済 | `README.md` 冒頭 | 製品説明が "configuration management system" となっていた乖離を修正済み。 |
| W3 | 解消済 | ドキュメント | 本仕様書がその答えであり、散在していた `*_IMPROVEMENTS.md` は `docs/history/` へ集約した。 |
| W5 | 解消済 | 任意依存の管理 | 依存一覧は `main/dependency_manifest.py` を唯一の真実の源とし、`satin_launcher.py` はそれを読む。 |
| W6 | 情報 | `null`/型不正データ耐性 | 直近セッションで JSONL/設定の `null` 値クラッシュを多数修正済み（§ CHANGELOG）。同種の防御は今後も新規 I/O ごとに必要。 |
| W7 | 解消済 (I25/I26) | `satin_launcher.py` 既定モード + アバター描画 | 商用品質監査で発見: 既定起動が `avatar_loader.AvatarLoaderApp`（何も表示しないファイル選択ダイアログ）を開くだけで本体 GUI に繋がらず、かつ本体 GUI は常に仮の球体しか描画せず、選んだアバターモデルを表示する手段が無かった。I25 で既定起動を本体 GUI に接続、I26 で選択を共有ストア経由で本体 GUI が読み込み・描画するよう統合（頂点ワイヤーフレーム、テクスチャ・スキニングは対象外）。 |

## 7. 改善の記録

実装済み改善の詳細な記録は
[`docs/history/SPECIFICATION_IMPROVEMENTS.md`](docs/history/SPECIFICATION_IMPROVEMENTS.md)
へ移した。仕様書は「今どうであるか」を書く場所であり、
「いつ何を直したか」は変更履歴の仕事だからである
（最新は [`CHANGELOG.md`](CHANGELOG.md)）。

### 7.1 将来の改善候補 (Backlog, 未実装)

- B2: 散在する `*_IMPROVEMENTS.md` を `docs/` 配下へ整理し本仕様書から相互参照。
- B5: `dependency_manifest` を `setup/requirements*.txt` 生成にも利用し、
  インストール定義の二重管理（W5 の残り半分）も解消する。
- B4: `daily_summary._load_jsonl`（gz アーカイブ対応）と `conversation_log`
  （event_type フィルタ + ストリーミング早期終了）も、gz・フィルタに対応した
  共通ローダへ将来的に統合可能（現状は専用実装を維持）。

---

## 8. 検証 (Verification)

リポジトリ root で以下を実行する。

```bash
python check.py     # これ 1 本。緑ならリリース可能な状態である
```

`check.py` が実行するもの: `py_compile` / ruff / mypy / pytest /
`manage_satin validate` / 起動スモーク 4 種（`--version`・`--chat`・
ダッシュボードの主要ルート・GUI）。GUI スモークは PyQt5 と X サーバ
（実物か xvfb）がある環境でのみ実行され、実 Qt で起動して自律モードを
400 ティック回し、アバターの座標が常に可視範囲内に留まることを検証する
（それ以外の環境では SKIP）。`--fast` を付けると起動スモークを省いて
編集中の高速ループに使える。

CI（`setup/github-actions-ci.yml`）もこの同じコマンドを呼ぶ。検証内容を
2 箇所に書かないことで、「手元では通るのに CI で落ちる」がリスト間の
ずれから生じる余地を無くしている。

`check.py` は個人データ（好感度・会話履歴）を退避してから起動スモークを
走らせるので、検証しただけでユーザーとアバターの関係が進むことはない。

個別に実行したい場合:

```bash
python -m pytest tests/ -q             # 全回帰
python -m ruff check main/ tests/      # lint
python -m mypy                          # 型（対象は mypy.ini が決める。引数を渡さない）
python main/manage_satin.py validate    # 設定検証
python main/dashboard.py                # http://127.0.0.1:5003
python satin_launcher.py --dashboard    # 同一ポートで起動すること
```
