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

進捗: ✅1 ✅2 ✅3 ✅4 ⬜5 ⬜6 ⬜7 ⬜8 ⬜9 ⬜10

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

## 3. 割り込み適時性/opportune-moment 検出

1. **Beyond Interruptibility: Predicting Opportune Moments to Engage Mobile Users** (UbiComp/IMWUT 2017) — https://minoskt.github.io/papers/UbiComp17_Engagement.pdf
   ML で opportune moment を予測すると非知能戦略比 **+66.6%**。
   → ★ `interruptibility.ts` を「busy 判定」から「engage 好機予測」へ。
2. **Intelligent Notification Systems: A Survey** — arxiv **1711.10171** — https://arxiv.org/pdf/1711.10171
   通知適時化の特徴量・手法サーベイ(breakpoint/context)。
   → 取り込むコンテキスト特徴(直前アプリ切替・時間帯)の整理。
3. **How Busy Are You?: Predicting the Interruptibility Intensity of Mobile Users** (CHI 2017) — https://www.researchgate.net/publication/316708988
   interruptibility を二値でなく **強度(intensity)** で予測。
   → `interruptibility.ts` の出力を連続スコア化(現状の coarse 判定を精緻化)。
4. **Continual Prediction of Notification Attendance with Classical and Deep Network Approaches** — arxiv **1712.07120** — https://arxiv.org/pdf/1712.07120
   通知応答の継続予測。軽量な古典手法でも実用精度。
   → DL 不要。`interruption_feedback.ts` の受容率推定を online 更新に。
5. **Predicting Interruptibility for Manual Data Collection** (MobileHCI 2017) — https://www.jorgegoncalves.com/docs/mobilehci17.pdf
   文脈特徴による interruptibility 予測の実証。
   → 採用特徴の取捨選択の参考。
6. **Rare Life Event Detection via Mobile Sensing Using Multi-Task Learning** — arxiv **2305.20056** — https://arxiv.org/abs/2305.20056
   モバイルセンシングで稀イベント検出(MTL)。
   → breakpoint/特異状況を「介入を控える」シグナルに。
7. **Examining the cognitive processes underlying resumption costs in task-interruption** (2023, PMC10896823) — https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10896823/
   タスク中断の **resumption cost**(再開コスト)の認知機構。
   → ★ `interruptionCost` を resumption-cost の概念で再定義(深い作業中ほど高コスト)。
8. **To Ask or Not To Ask (HITL contextual bandits)** — arxiv **2405.06908** — https://arxiv.org/html/2405.06908v1
   「問い合わせるべきか」の認知負荷を考慮した問い合わせ制御。
   → 問い合わせコストを `interruptionCost` と統合。
9. **GitHub: TimingPredict/Dataset** — https://github.com/TimingPredict/Dataset
   タイミング予測用データセット。
   → 適時化モデルの評価・回帰テスト用の参考データ。
10. **User Interruptibility and Notification Management in Mobile Devices**(研究トピック概観) — https://www.nature.com/research-intelligence/nri-topic-summaries-v9/user-interruptibility-and-notification-management-in-mobile-devices
    分野全体の動向(attention capacity + context-aware + ML)。
    → 設計の俯瞰・抜け漏れチェック。

**改善点まとめ(カテゴリ3)**: ①busy判定→好機予測へ(#1)、②出力を連続スコア化(#3)、
③`interruptionCost` を resumption-cost で再定義(#7)、④受容率の online 更新+問い合わせコスト統合(#4,#8)、
⑤app/task 切替を breakpoint シグナルに(#2)。

---

## 4. 文脈付きバンディット/オンライン学習

1. **GitHub: thoughtworks/simplebandit** — https://github.com/thoughtworks/simplebandit
   ★ **ゼロ依存の TS 文脈付きバンディット**(online logistic regression + softmax 探索, <700行)。
   → `bandit.ts` を非文脈→**文脈付き**へ拡張する際の直接の実装パターン(設計思想が satin と一致)。
2. **Optimal Baseline Corrections for Off-Policy Contextual Bandits** — arxiv **2405.05736** — https://arxiv.org/abs/2405.05736
   制御変量(baseline 補正/doubly-robust)で分散最適な不偏推定。
   → `debiasedUpdate` を baseline-corrected/doubly-robust へ。
3. **Anytime-valid off-policy inference for contextual bandits** — arxiv **2210.10768** — https://arxiv.org/abs/2210.10768
   逐次的に妥当な off-policy 推論。
   → `auditRewards` の信頼区間を anytime-valid に。
4. **To Ask or Not To Ask** — arxiv **2405.06908** — https://arxiv.org/html/2405.06908v1
   人間参加型の文脈バンディットで問い合わせ判断。
   → 介入の要否判断を bandit へ統合。
5. **Feel-Good Thompson Sampling for Contextual Bandits (MCMC)** — arxiv **2507.15290** — https://arxiv.org/html/2507.15290
   Feel-Good TS の探索性能を MCMC で検証。
   → 探索方針(softmax→TS)の比較検討。
6. **GitHub: stitchfix/mab** — https://github.com/stitchfix/mab
   Thompson/epsilon-greedy の決定的実装ライブラリ。
   → `selectArm` の探索戦略の実装参考。
7. **GitHub: ReactiveCJ/MultiArmedBandit** — https://github.com/ReactiveCJ/MultiArmedBandit
   MAB 戦略(TS 含む)の入門実装。
   → 既存 `bandit.ts` との戦略比較。
8. **GitHub Topic: contextual-bandits** — https://github.com/topics/contextual-bandits
   文脈バンディット OSS の一覧。
   → 軽量実装の横断比較。
9. **GitHub Topic: thompson-sampling** — https://github.com/topics/thompson-sampling
   TS 系実装のエコシステム。
   → 探索手法の実装ソース。
10. **Thompson Sampling for Contextual bandits**(解説, gdmarmerola) — https://gdmarmerola.github.io/ts-for-contextual-bandits/
    文脈バンディット+TS の実装解説。
    → 実装時のアルゴリズム理解。

**改善点まとめ(カテゴリ4)**: ①`bandit.ts` を文脈付き化(時刻/chronotype/活動/breakpoint をコンテキストに)。
simplebandit の online logistic + softmax が ゼロ依存方針に最適(#1)。②報酬補正を doubly-robust/baseline-corrected へ(#2)、
③off-policy 監査を anytime-valid に(#3)、④探索を softmax↔Thompson で比較(#5,#6)。

---

## 5〜10. (調査予定 — /loop で順次拡充)

- 5. 変化点検知 — 既存 §C(BOCPD)。
- 6. 長期記憶 — 同 §D(RMM/TiMem/Amory)+ ReMe / LD-Agent / Agent-Memory-Paper-List。
- 7. 概日/睡眠 — 同 §F。
- 8. 安全性/ウェルビーイング — 同 §A。
- 9. アバター身体性 — VRM/Live2D・spring 物理・ビート検出の arxiv/GitHub を新規調査。
- 10. オンデバイス/プライバシー — local LLM(llama.cpp 系)・on-device TTS・BYOK の新規調査。
