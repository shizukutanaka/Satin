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
| A3 | 未着手 | **感情強度連動辞書** — 全て±1でなく弱/中/強の重み | `mood.py`, `config/persona.json` | [WRIME Ver.2/HF](https://huggingface.co/datasets/shunk031/wrime) |
| A4 | 未着手 | **記憶想起の品質向上** — substring 検索を BM25/TF-IDF（scikit-learn は既存依存、埋め込み不要）へ | `conversation_log.py` | [Re:Member arXiv:2510.19030](https://arxiv.org/pdf/2510.19030) |
| A5 | ✅ 実装済 | **変化点検知** — ユーザー自身の基準からの気分変化を根拠付きで発火 | `user_wellbeing.py` (`wellbeing_shift`) | [BOCPD arXiv:0710.3742](https://arxiv.org/abs/0710.3742) |
| A6 | ✅ 実装済 | **概日トーン拡充** — 深夜帯 `late_night`(0–5時) を `night` から分離し睡眠配慮トーンを追加、時刻区分を単一化 | `persona.py` (`_time_of_day`/`talk_by_time`), `config/persona.json` | `CATEGORY_RESEARCH.md` カテゴリ7 |

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

A1（安全）→ A2（感情精度）→ A5（変化点）→ A6（概日）→ **A4（BM25 記憶）** → A3 → B/C は方針確定後。
（A1・A2・A5・A6 は実装済み。残るは A4（記憶想起の BM25/TF-IDF 化）と A3（感情強度辞書）。
以降も 1機能=1コミット、実装→回帰テスト→push で継続。）
