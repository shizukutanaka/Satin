# Satin 改善点リスト — 最新研究駆動（Python 実装接地版, 2025–2026）

> **位置づけ**: 既存の `CATEGORY_RESEARCH.md` / `RESEARCH_DRIVEN_IMPROVEMENTS.md` は
> TypeScript ライブラリ `satin-companion-core`（`empathy.ts`/`bond.ts`/`bandit.ts`）
> を対象とした**構想**で、このリポジトリには存在しない。本ドキュメントは、実際に
> 出荷されている **Python `main/`（対話・感情・記憶がすべて辞書/ルール/キーワード
> ベース、LLM・外部API非依存）** に改善点を接地させ、その意図的な no-LLM/オフライン/
> プライバシー設計を尊重して分類したもの。

## 設計境界（Tier）

- **Tier A** — 現行 no-LLM/オフライン設計の内側（決定論的・軽量・新規重依存なし）
- **Tier B** — ローカル ML オプション（クラウド不使用・未導入時は A へ自動フォールバック）
- **Tier C** — ローカル LLM オプション（"no-LLM" 明言と衝突・採用は要方針判断）

---

## Tier A（推奨）

| # | 状態 | 改善点 | 対象モジュール | 主な出典 |
|---|------|--------|----------------|----------|
| A1 | ✅ 実装済 | **感情依存/パラソーシャル安全ガードレール** — 深夜利用の常態化・極端な単日集中を検知し、そっと休息/現実のつながりへ促す（1日1回・非強制） | `usage_guardrails.py`（新規）, `autonomous_behavior.py` | [APA 2026](https://www.apa.org/monitor/2026/01-02/trends-digital-ai-relationships-emotional-connection), [Princeton CITP 2025](https://blog.citp.princeton.edu/2025/08/20/emotional-reliance-on-ai-design-dependency-and-the-future-of-human-connection/), [arXiv:2506.12605](https://arxiv.org/html/2506.12605v1), [Affective AI Safety](https://arxiv.org/pdf/2606.23380) |
| A2 | ✅ 実装済 | **否定・絵文字対応のハイブリッド感情判定** — 「好きじゃない」「I don't like you」を否定と正しく判定、絵文字/顔文字を反映 | `mood.classify_sentiment` / `MoodTracker.register` | [WRIME NAACL 2021](https://aclanthology.org/2021.naacl-main.169/), [arXiv:2208.14244](https://arxiv.org/pdf/2208.14244) |
| A3 | ✅ 実装済 | **感情強度連動辞書** — 全て±1でなく弱/中/強の重み（`_INTENSITY` 静的表 + `_polarity_weights`）。極性の符号は整数カウントのまま、増減幅のみ強度加重（「大好き」>「好き」、「最悪」>「つまらない」）。未指定/カスタム語は 1.0 で従来挙動を保持 | `mood.py` (`_intensity_of`/`_polarity_weights`) | [WRIME Ver.2/HF](https://huggingface.co/datasets/shunk031/wrime) |
| A4 | ✅ 実装済 | **記憶想起の品質向上** — substring 検索に加え Okapi BM25 の関連度検索 `search_relevant()` を追加（純 Python・埋め込み/外部依存なし、CJK は文字バイグラム）。GUI `/search` は完全一致 0 件時に「近い会話」を関連度順で提示 | `conversation_log.py` (`search_relevant`), `avatar_3d_autonomous_tts.py` | [Re:Member arXiv:2510.19030](https://arxiv.org/pdf/2510.19030) |
| A5 | ✅ 実装済 | **変化点検知** — ユーザー自身の基準からの気分変化を根拠付きで発火 | `user_wellbeing.py` (`wellbeing_shift`) | [BOCPD arXiv:0710.3742](https://arxiv.org/abs/0710.3742) |
| A6 | ✅ 実装済 | **概日トーン拡充** — 深夜帯 `late_night`(0–5時) を `night` から分離し睡眠配慮トーンを追加、時刻区分を単一化 | `persona.py` (`_time_of_day`/`talk_by_time`), `config/persona.json` | `CATEGORY_RESEARCH.md` カテゴリ7 |
| A7 | ✅ 実装済 | **別れぎわの操作的表現ガードレール** — 「もう行くの？」「待ってるから」等、goodbye 時にユーザーを引き止める会話ダークパターン（6 戦術）を決定論的に検知し、`Persona.respond()` が別れの文脈で除外。出荷する台詞も監査テストで hook ゼロを保証（A1 がユーザーの利用強度を見るのに対し、A7 は**製品自身の振る舞い**を律する） | `farewell_integrity.py`（新規）, `persona.respond`, `config/persona.json` | [De Freitas, Oğuz-Uğuralp & Uğuralp, *Emotional Manipulation by AI Companions*, arXiv:2508.19258 / HBS WP 26-005](https://arxiv.org/abs/2508.19258), [Harmful Traits of AI Companions arXiv:2511.14972](https://arxiv.org/abs/2511.14972), [APA 2026](https://www.apa.org/monitor/2026/01-02/trends-digital-ai-relationships-emotional-connection) |
| A8 | ✅ 実装済 | **危機表明（自傷・自殺念慮）への応答** — 従来は「死にたい」も汎用フォールバックで受け流し、しかも好感度に算入していた。共感 → AI である旨 → **具体名の相談先**の 3 要素だけを短く返し、好感度・会話回数・プロフィール記憶・聞き返し質問を全てバイパスする（危機をゲーム化しない） | `crisis_support.py`（新規）, `avatar_3d_autonomous_tts.speak_comment`, `persona_cli.run_chat` | [メンタルヘルスbot 29種の評価, Sci Rep 2025](https://www.nature.com/articles/s41598-025-17242-4)（適切な応答 0 件・具体名の提示は 41%）, [Sentio 2026/IASEAI](https://sentio.org/ai-research/llm-responses-to-suicide-risk-iaseai-study)（リスク開示が深まるほどボットが引く）, [2026 State Chatbot Laws (NY S 3008 等)](https://www.orrick.com/en/Insights/2026/04/2026-State-Chatbot-Laws-Key-Provisions-and-Regulatory-Trends) |

## Tier B（ローカル ML オプション・要オプトイン）

| # | 改善点 | 対象 | 出典 |
|---|--------|------|------|
| B1 | 小型ローカル埋め込みで意味記憶（A4 の上位版、未導入時 A4 にフォールバック） | `conversation_log.py` | `CATEGORY_RESEARCH.md` カテゴリ6/10 |
| B2 | WRIME 学習の小型日本語感情分類（A2 の上位版） | `mood.classify_sentiment` | [RoBERTa/DeBERTa, arXiv:2505.00013](https://arxiv.org/html/2505.00013v1) |
| B3 | 表現力ローカル TTS（気分/好感度に応じた感情スタイル発話） | `tts_thread.py`, `tts_with_virtual_audio.py` | [Style-Bert-VITS2](https://github.com/litagin02/Style-Bert-VITS2), [ベンチ arXiv:2505.17320](https://arxiv.org/html/2505.17320v1) |

## Tier C（ローカル LLM オプション・要方針判断）

| # | 改善点 | 対象 | 出典 |
|---|--------|------|------|
| C1 | 小型ローカル LLM による対話生成（未導入時は現行テンプレへフォールバック）。**A1 の安全ガードレール前提** | `persona.respond` | on-device SLM; Affective AI Safety [arXiv](https://arxiv.org/pdf/2606.23380), `CATEGORY_RESEARCH.md` カテゴリ8 |

---

## 推奨実行順

A1（安全）→ A2（感情精度）→ A5（変化点）→ A6（概日）→ A4（BM25 記憶）→ A3（感情強度辞書）
→ A7（別れぎわの操作的表現）→ A8（危機表明への応答）→ B/C は方針確定後。
（**Tier A（A1–A8）はすべて実装済み**。以降は Tier B（ローカル ML）/ Tier C（ローカル LLM）で、
no-LLM 設計境界に関わるためユーザーの方針判断が必要。
各項目は 1機能=1コミット、実装→回帰テスト（fix を revert すると落ちる確認）→push で実施した。）
