# Satin — カテゴリー別 改善リサーチ (10カテゴリ × 各10ソース)

> 目的: `satin-companion-core`(プライバシーファースト/ゼロ依存/純粋関数のオンデバイス行動知能ライブラリ)
> を、製品カテゴリーごとに arxiv.org / GitHub の関連情報を集めて改善点を洗い出す。
> 各ソースは web 検索で実在 URL を確認したもののみ掲載(架空の arxiv ID/URL は不可)。
> 進捗はループ(/loop)で順次拡充。

調査開始: 2026-06-05

## 10 カテゴリー一覧(対象モジュール)
1. 行動的感情/affect 推定(keystroke/mouse dynamics) — `empathy.ts`, `keyboard_activity.ts`
2. 人間–AI ボンディング/愛着モデル — `bond.ts`, `reunion.ts`, `streak.ts`
3. 割り込み適時性/opportune-moment 検出 — `interruptibility.ts`, `interruption_feedback.ts`, `awareness.ts`
4. 文脈付きバンディット/オンライン学習 — `bandit.ts`
5. 変化点検知/非定常適応 — `change_point.ts`
6. 長期記憶: 統合・検索・忘却 — `memory_journal.ts`, `semantic_memory.ts`, `self_narrative.ts`
7. 概日リズム/クロノタイプ/睡眠推定 — `chronotype.ts`, `sleep_window.ts`
8. AIコンパニオン安全性/ウェルビーイング/反シンコファンシー — `empathy.ts`, `ai_chat.ts`, `coherence.ts`
9. アバター身体性(VRM/Live2D idle・spring 物理・audio-reactive) — `idle_motion.ts`, `spring.ts`, `audio_reactivity.ts`, `particles.ts`
10. プライバシー保護/オンデバイス知能(local LLM/TTS, BYOK, zero-dep) — `ai_chat.ts`, `schema.ts`

進捗: ✅1 ✅2 ⬜3 ⬜4 ⬜5 ⬜6 ⬜7 ⬜8 ⬜9 ⬜10

---

## 1. 行動的感情/affect 推定 (keystroke/mouse dynamics)

1. **A Review of Emotion Recognition Methods From Keystroke, Mouse, and Touchscreen Dynamics** (Kołakowska ほか, IEEE Access 2021) — https://ieeexplore.ieee.org/document/9632591/
   キーストローク/マウス/タッチ動態からの感情推定手法の包括レビュー。非侵襲・追加センサ不要が利点。
   → satin: `empathy.ts` の特徴量設計の網羅性確認に。固定閾値でなくレビュー準拠の特徴(dwell/flight time, 速度分散)を整理。
2. **Identifying emotional states using keystroke dynamics** (Epp, Lippold, Mandryk, CHI 2011) — https://dl.acm.org/doi/10.1145/1978942.1979046
   タイピングのリズム特徴で 15 感情を分類した seminal 研究。
   → `keyboard_activity.ts` に dwell/flight 比など古典特徴を追加し `inferEmotion` の入力を拡充。
3. **MouStress: Detecting Stress from Mouse Motion** (Sun ほか, CHI 2014) — https://people.eecs.berkeley.edu/~jfc/papers/14/CHI_MS14.pdf
   マウス運動の mass-spring-damper モデルで筋硬直を近似しストレス推定。
   → `empathy.ts` のカーソル特徴を「速度/加速度のジャーク」へ拡張(spring.ts の二次系と整合)。
4. **Linear Predictive Coding for Acute Stress Prediction from Computer Mouse Movements** — arxiv **2010.13836** — https://arxiv.org/abs/2010.13836
   LPC フィルタで筋スティフネス/ダンピングを近似、10 サンプルで ~70% 精度。
   → 軽量・オンデバイス向き。`empathy.ts` に LPC 風の低次特徴を純関数で実装可能。
5. **Machine and Deep Learning Applications to Mouse Dynamics** (survey) — arxiv **2205.13646** — https://arxiv.org/pdf/2205.13646
   マウス動態の ML/DL 応用サーベイ(認証・感情・ストレス)。
   → どの特徴が汎化するかの参照。重い DL は避け、サーベイ中の軽量特徴を採用。
6. **One does not fit all: Detecting work-related stress from mouse, keyboard, and cardiac data in the field** (medRxiv 2025) — https://www.medrxiv.org/content/10.1101/2025.08.02.25332538v1.full.pdf
   フィールドでは one-fits-all より **個人化(personalized)** モデルが有効。
   → ★ `empathy.ts` に **個人ベースライン正規化** を導入(固定閾値→相対化)。
7. **Tracking stress via the computer mouse? Promises and challenges** (Freihaut ほか, PMC8613085) — https://pmc.ncbi.nlm.nih.gov/articles/PMC8613085/
   N=994 のフィールド研究では明確な関係が出ず、汎用ストレス指標化は困難という警鐘。
   → ★ 推定に **信頼度/不確実性** を必ず付与し、低信頼時はミラーリングを抑制(過信防止)。
7b. **The influence of emotion on keyboard typing: an experimental study** (PMC4091769) — https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4091769/
   感情刺激でタイピング速度/エラー率が変化することを実証。
   → 速度・誤打鍵(backspace 率)を `keyboard_activity.ts` のシグナルに追加。
8. **EmoSurv**(感情ラベル付きタイピングバイオメトリクス データセット, IEEE DataPort) — 参照: https://github.com/alodieboissonnet/EmotionRecognitionKeystrokeDynamics
   感情ラベル付きの公開データで手法検証が可能。
   → `empathy.ts` の係数を **実データで較正/回帰テスト** する基盤に。
9. **GitHub: alodieboissonnet/EmotionRecognitionKeystrokeDynamics** — https://github.com/alodieboissonnet/EmotionRecognitionKeystrokeDynamics
   キーストローク特徴抽出+分類の実装例(EmoSurv 使用)。
   → 抽出する特徴セットの実装参考(TS へ純関数で移植)。
10. **GitHub Topic: keystroke-dynamics** — https://github.com/topics/keystroke-dynamics
    キーストローク動態の OSS エコシステム(認証/感情)。
    → 既存実装の特徴量・前処理の比較対象。

**改善点まとめ(カテゴリ1)**: ①個人ベースライン正規化(#6)、②不確実性付き出力で過信防止(#7)、
③古典特徴の追加(dwell/flight, backspace 率, ジャーク)(#2,#3,#7b)、④公開データでの較正・回帰テスト(#8)。
すべて純関数・ゼロ依存で実装可能。

---

## 2. 人間–AI ボンディング/愛着モデル

1. **Illusions of Intimacy: How Emotional Dynamics Shape Human-AI Relationships** — arxiv **2505.11649** — https://arxiv.org/abs/2505.11649
   30K 会話分析。感情ミラーリング/同期が人間的な絆形成に酷似、ただし正感情の過増幅リスク。
   → ★ `bond.ts`/`empathy.ts`: ミラーリング駆動の絆進行に **上限と減衰** を入れる(過依存抑制)。
2. **The Rise of AI Companions: How Human-Chatbot Relationships Influence Well-Being** — arxiv **2506.12605** — https://arxiv.org/html/2506.12605v1
   重い利用と孤独感の相関。healthy boundaries/disengagement の設計推奨。
   → `bond.ts` に過依存検知 nudge と「意図的に離れる」API。
3. **Mental Health Impacts of AI Companions** — arxiv **2509.22505** — https://arxiv.org/abs/2509.22505
   コンパニオン利用のメンタルヘルス影響(依存・気分)を整理。
   → 進行が速すぎる絆を抑制、ステージ可視化でユーザの自己認識を支援。
4. **How AI and Human Behaviors Shape Psychosocial Effects of Extended Chatbot Use: A Longitudinal RCT** — arxiv **2503.17473** — https://arxiv.org/html/2503.17473v2
   長期 RCT。利用様態(音声/テキスト・話題)で心理社会的影響が変化。
   → `coherence.ts` のモード選択に「ウェルビーイング配慮」分岐を追加。
5. **Can LLMs and humans be friends? Factors affecting human-AI intimacy formation** — arxiv **2505.24658** — https://arxiv.org/html/2505.24658v1
   親密形成の要因(応答性・自己開示・一貫性)を分析。
   → ★ `applyReward`/`recordSession` を **自己開示量・reciprocity・継続性** で重み付け。
6. **Scaffolded Vulnerability: Chatbot-Mediated Reciprocal Self-Disclosure** — arxiv **2602.07508** — https://arxiv.org/pdf/2602.07508
   相互自己開示の足場かけが関係深化に寄与。
   → bond 進行の駆動因に「相互開示の往復」を組み込む。
7. **The Impact of a Chatbot's Ephemerality-Framing on Self-Disclosure** — arxiv **2505.20464** — https://arxiv.org/html/2505.20464v1
   「消える/残る」のフレーミングが自己開示量を左右。
   → メモリ可視化(memory_journal の inspect/redact)とプライバシー表現に反映。
8. **Dialoging Resonance: How Users Reciprocate Chatbot's Self-Disclosure** — arxiv **2106.01666** — https://arxiv.org/pdf/2106.01666
   チャットボットの自己開示にユーザが reciprocate する条件。
   → コンパニオン側の self-disclosure(`self_narrative.ts`)を reciprocity 設計に活用。
9. **AI Chaperones to Prevent Parasocial Relationships with Chatbots** — arxiv **2508.15748** — https://arxiv.org/html/2508.15748v5
   過度なパラソーシャル関係を抑える「シャペロン」機構の提案。
   → 依存検知時の介入(休憩提案・現実関係への橋渡し)の設計参考。
10. **Operationalizing Social Bonding in Human-Robot Dyads** — arxiv **2310.11386** — https://arxiv.org/pdf/2310.11386
    社会的絆の操作化(自己開示・知覚エージェンシー・反復相互作用)。
    → `bond.ts` の進行式の理論的裏付け・パラメータ設計。
+ GitHub: **leolee99/LD-Agent**(NAACL2025 長期対話 personalized agent) — https://github.com/leolee99/LD-Agent
    persona 抽出+event perception の実装。`semantic_memory`/`self_narrative` 連携の参考。
+ 参考(縦断研究): **Longitudinal Study of Self-Disclosure in Human–Chatbot Relationships**(Oxford IWC 2023) — https://academic.oup.com/iwc/article/35/1/24/7069316
    自己開示は時間とともに変化(往々に減衰)。継続性設計の根拠。

**改善点まとめ(カテゴリ2)**: ①絆進行を「自己開示量×reciprocity×継続性」で重み付け(#5,#6,#10)、
②ミラーリング絆に上限/減衰を入れ過依存を防ぐ(#1,#2,#3)、③ステージ可視化+disengagement/シャペロン(#2,#9)、
④メモリ可視化と整合した自己開示設計(#7,#8)。

---

## 3〜10. (調査予定 — /loop で順次拡充)

- 3. 割り込み適時性 — 既存 `RESEARCH_DRIVEN_IMPROVEMENTS.md` §B の出典を核に GitHub OSS を追加予定。
- 4. 文脈付きバンディット — 同 §B-2。
- 5. 変化点検知 — 同 §C(BOCPD)。
- 6. 長期記憶 — 同 §D(RMM/TiMem/Amory)+ ReMe / LD-Agent / Agent-Memory-Paper-List。
- 7. 概日/睡眠 — 同 §F。
- 8. 安全性/ウェルビーイング — 同 §A。
- 9. アバター身体性 — VRM/Live2D・spring 物理・ビート検出の arxiv/GitHub を新規調査。
- 10. オンデバイス/プライバシー — local LLM(llama.cpp 系)・on-device TTS・BYOK の新規調査。
