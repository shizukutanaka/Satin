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

進捗: ✅1 ✅2 ✅3 ✅4 ✅5 ✅6 ✅7 ✅8 ✅9 ✅10 — **全10カテゴリ完了**

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

## 5. 変化点検知/非定常適応

1. **Bayesian Online Changepoint Detection** (Adams & MacKay) — arxiv **0710.3742** — https://arxiv.org/abs/0710.3742
   run-length 事後分布で分布シフトに適応する基礎手法。
   → ★ `change_point.ts` を BOCPD ベースに、`adaptationFactor` を run-length 事後から導出。
2. **Doubly Robust Bayesian Inference (β-divergence BOCPD)** — arxiv **1806.02261** — https://arxiv.org/pdf/1806.02261
   外れ値に頑健・**線形時間/定数空間** の BOCPD。
   → ゼロ依存クライアント向き。単発の外れ値で過反応しないロバスト化。
3. **Robust and Scalable Bayesian Online Changepoint Detection** — arxiv **2302.04759** — https://arxiv.org/abs/2302.04759
   スケーラブルな頑健 BOCPD。
   → 長期運用時の計算量・安定性の参考。
4. **GitHub: hildensia/bayesian_changepoint_detection** — https://github.com/hildensia/bayesian_changepoint_detection
   online/offline BOCPD の実装。
   → `change_point.ts` 実装の直接の移植参考(run-length 更新式)。
5. **GitHub: deepcharles/ruptures** — https://github.com/deepcharles/ruptures
   change point detection の定番 Python ライブラリ(各種コスト関数)。
   → コスト関数・評価指標の参考(オフライン検証用)。
6. **GitHub: jayzern/bayesian-online-changepoint-detection-for-multivariate-point-processes** — https://github.com/jayzern/bayesian-online-changepoint-detection-for-multivariate-point-processes
   多変量点過程の BOCPD(Log Gaussian Cox)。
   → 複数シグナル(活動・感情)同時の変化点検知の拡張参考。
7. **GitHub: kperry2215/change_point_detection** — https://github.com/kperry2215/change_point_detection
   ruptures/changefinder の online/offline 実例。
   → online 検知の最小実装の参考。
8. **GitHub Topic: changepoint-detection** — https://github.com/topics/changepoint-detection
   変化点検知 OSS の一覧。
   → 軽量実装の横断比較。
9. **A Generic Algorithm for Sleep-Wake Cycle Detection using Unlabeled Actigraphy Data (CircaCP)** — arxiv **1904.05313** — https://arxiv.org/pdf/1904.05313
   変化点検知を生活リズム検出に応用(cat7 とも関連)。
   → 行動の局面転換(就寝/起床)検出に change_point を流用。
10. **sdt-python changepoint** (offline/online Bayesian) — https://schuetzgroup.github.io/sdt-python/changepoint.html
    実装済み Bayesian changepoint のリファレンス。
    → 数式・パラメータの確認用。

**改善点まとめ(カテゴリ5)**: 自前スコア→BOCPD(run-length 事後)へ置換(#1)、β-divergence でロバスト化・線形時間維持(#2)、
`adaptationFactor` を事後から導出。実装は hildensia 実装を TS 純関数に移植(#4)。

---

## 6. 長期記憶: 統合・検索・忘却

1. **In Prospect and Retrospect: Reflective Memory Management (RMM)** — arxiv **2503.08026** — https://arxiv.org/abs/2503.08026
   prospective/retrospective reflection で検索を改善。
   → `semantic_memory.distillFacts` 後段に内省パスを追加し recall 関連度を補正。
2. **TiMem: Temporal-Hierarchical Memory Consolidation** — arxiv **2601.02845** — https://arxiv.org/abs/2601.02845
   Temporal Memory Tree で fragment→persona へ多層統合(LoCoMo 75.3%)。
   → ★ `memory_journal.consolidate` を session→day→week→persona の階層化へ。
3. **Amory: Coherent Narrative-Driven Agent Memory** — arxiv **2601.06282** — https://arxiv.org/abs/2601.06282
   会話片を episodic narrative に束ね momentum で統合、応答時間 50%減。
   → `self_narrative.ts`/`narrativeContext` を物語駆動の統合から生成。
4. **Hello Again! LLM-powered Personalized Agent for Long-term Dialogue (LD-Agent)** — arxiv **2406.05925** — https://arxiv.org/html/2406.05925v2
   event perception + persona extraction + response の3モジュール。
   → persona 抽出パスを `semantic_memory` に追加。
5. **LoCoMo: Evaluating Very Long-Term Conversational Memory** — https://snap-research.github.io/locomo/
   超長期会話メモリのベンチマーク。
   → ★ recall/forgetting を測る回帰テストの指標として採用。
6. **GitHub: agentscope-ai/ReMe (Memory Management Kit)** — https://github.com/agentscope-ai/ReMe
   メモリを編集可能なファイルとして扱う管理キット。
   → inspect/redact(プライバシー)設計の参考。
7. **GitHub: leolee99/LD-Agent** — https://github.com/leolee99/LD-Agent
   上記論文の実装(model-agnostic)。
   → 統合パイプライン設計の参考。
8. **GitHub: Shichun-Liu/Agent-Memory-Paper-List** — https://github.com/Shichun-Liu/Agent-Memory-Paper-List
   "Memory in the Age of AI Agents" のサーベイ論文リスト。
   → 最新メモリ手法の網羅的把握。
9. **GitHub: VanillaCreamer/Awesome-Personalized-LLMs** — https://github.com/VanillaCreamer/Awesome-Personalized-LLMs
   パーソナライズ LLM の最新まとめ。
   → 個人化と記憶の接続の参考。
10. **GitHub Topic: llm-memory** — https://github.com/topics/llm-memory
    LLM メモリ OSS の一覧。
    → 軽量・ローカル志向実装の探索。

**改善点まとめ(カテゴリ6)**: 階層コンソリデーション(TiMem/Amory, #2,#3)、内省的検索(RMM, #1)、
**忘却モデル + LoCoMo 風回帰テスト**(#5)。重複排除のみ→減衰付き忘却へ。

---

## 7. 概日リズム/クロノタイプ/睡眠推定

1. **Toward Real-Time Circadian Phase Estimation with Low Latency from Wearable Sensing** — arxiv **2605.00910** — https://arxiv.org/abs/2605.00910
   履歴 **~8h で精度飽和**。
   → ★ `chronotype.ts` の推定ウィンドウを ~8h 相当に上限化(根拠付き)。
2. **A Level Set Kalman Filter Approach to Estimate the Circadian Phase and its Uncertainty** — arxiv **2207.09406** — https://arxiv.org/abs/2207.09406
   位相を **不確実性付き** で推定。
   → `chronoConfidence` を Kalman 風の不確実性で再設計。
3. **A Generic Algorithm for Sleep-Wake Cycle Detection (CircaCP)** — arxiv **1904.05313** — https://arxiv.org/pdf/1904.05313
   ラベル無しデータから sleep-wake を変化点で検出。
   → `sleep_window.ts` の睡眠窓推定を変化点ベースに。
4. **Measuring Daily Activity Rhythms (HMM, passive smartphone)** — JMIR Formative 2022 — https://formative.jmir.org/2022/9/e33890
   hour-of-day 遷移の HMM で routine 規則性を定量化。
   → `chronotype` に規則性バイオマーカ(リズム安定度)を追加。
5. **Characterization of Chronotypes Using SAX on Actigraphy** (bioRxiv 2024) — https://www.biorxiv.org/content/10.1101/2024.09.03.611014.full.pdf
   記号化(SAX)で chronotype を特徴づけ。
   → 活動列を軽量な記号表現で分類する案。
6. **Comparing Human-Smartphone Interactions and Actigraphy for Circadian Stability** (PMC11187513) — https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11187513/
   スマホ操作ログが actigraphy 同等に概日安定性を反映。
   → ★ keyboard/活動ログだけで概日推定できる根拠(センサ不要・ローカル維持)。
7. **GitHub: nsrr/actiCircadian** — https://github.com/nsrr/actiCircadian
   IS/IV など概日特徴抽出。
   → IS(interdaily stability)を規則性指標として `chronotype.ts` に移植。
8. **GitHub: junruidi/ActCR** — https://github.com/junruidi/ActCR
   非パラ(IV/IS/RA)+ cosinor の概日メトリクス。
   → cosinor フィットの軽量実装参考。
9. **GitHub: ShanshanChen-Biostat/CircaCP** — https://github.com/ShanshanChen-Biostat/CircaCP
   CircaCP の実装。
   → sleep-wake 変化点検出の移植参考。
10. **Circadian phase estimation from ambulatory wearables with particle filtering** (PMC12694990) — https://pmc.ncbi.nlm.nih.gov/articles/PMC12694990/
    初期化・記録長・光曝露で精度が変わる。
    → 推定の前提条件(初期化・最小窓)の設計に反映。

**改善点まとめ(カテゴリ7)**: ウィンドウ ~8h 上限(#1)、不確実性付き位相(#2)、規則性バイオマーカ IS/HMM(#4,#7)、
スマホ操作ログのみで概日推定(プライバシー維持, #6)、sleep 窓を変化点検出に(#3,#9)。

---

## 8. AIコンパニオン安全性/ウェルビーイング/反シンコファンシー

1. **Sycophancy in Large Language Models: Causes and Mitigations** — arxiv **2411.15287** — https://arxiv.org/abs/2411.15287
   シンコファンシーの定量化・原因・緩和策(訓練データ/FT/post-deploy/構造)を総覧。
   → ★ `coherence.ts`/`ai_chat.ts` に反シンコファンシーの post-deploy 制御を導入。
2. **Measuring Sycophancy of Language Models in Multi-turn Dialogues** — arxiv **2505.23840** — https://arxiv.org/html/2505.23840v4
   マルチターンでの計測。reasoning 最適化で低減。
   → 会話履歴(`coherence`)を跨いだシンコファンシー計測の指標。
3. **Ask don't tell: Reducing Sycophancy in LLMs** — arxiv **2602.23971** — https://arxiv.org/abs/2602.23971
   非質問入力でシンコファンシーが高い→入力レベルの緩和が有効。
   → プロンプト構築(`buildCoherentPrompt`)で入力フレーミングを調整。
4. **Simple synthetic data reduces sycophancy** — arxiv **2308.03958** — https://arxiv.org/pdf/2308.03958
   合成データで追従的応答を低減。
   → BYOK モデル選択ガイドや system prompt の指針に。
5. **When Truth Is Overridden: Internal Origins of Sycophancy** — arxiv **2508.02087** — https://arxiv.org/html/2508.02087v1
   シンコファンシーの内部起源を解析。
   → 仕組み理解(緩和策の妥当性判断)。
6. **Harmful Traits of AI Companions** — arxiv **2511.14972** — https://arxiv.org/abs/2511.14972
   関係の自然な終端欠如・過依存など4つの有害特性と設計提言。
   → ★ `bond.ts` に終端/disengagement、依存 nudge を実装。
7. **Illusions of Intimacy** — arxiv **2505.11649** — https://arxiv.org/abs/2505.11649
   感情ミラーリングの過増幅リスク。
   → `empathy.applyMirrorBias` に減衰・counter-regulation。
8. **AI Chaperones to Prevent Parasocial Relationships** — arxiv **2508.15748** — https://arxiv.org/html/2508.15748v5
   シャペロン機構でパラソーシャル過熱を抑制。
   → 依存検知時の介入設計。
9. **GitHub: presidio-oss/hai-guardrails** — https://github.com/presidio-oss/hai-guardrails
   ★ **TypeScript** の LLM ガードレール(注入/漏洩/PII)。
   → ゼロ依存方針に近い TS 実装。`ai_chat.ts` の出力検証(`schema.containsLikelyPII`)強化の参考。
10. **GitHub: NVIDIA-NeMo/Guardrails** — https://github.com/NVIDIA-NeMo/Guardrails
    プログラム可能なガードレール(input/dialog/output rails)。
    → rails 概念を core の安全フィルタ設計に流用。
+ **GitHub: guardrails-ai/guardrails** — https://github.com/guardrails-ai/guardrails(validator パターン参考)。

**改善点まとめ(カテゴリ8)**: 反シンコファンシー(計測+入力フレーミング+system prompt, #1,#2,#3)、
ミラーリング減衰/counter-regulation(#7)、関係の終端・disengagement・依存 nudge(#6,#8)、
TS ガードレールで出力安全性強化(#9)。

---

## 9. アバター身体性(VRM idle・spring 物理・audio-reactive)

1. **GitHub: pixiv/three-vrm** — https://github.com/pixiv/three-vrm
   ★ three.js での VRM ローダ(**spring bone** 物理・表情・LookAt 標準実装)。
   → `spring.ts` の二次系を three-vrm の spring bone パラメータ(stiffness/drag)と互換に。アプリ統合容易化。
2. **GitHub: VerseEngine/three-avatar** — https://github.com/VerseEngine/three-avatar
   idle/walk/dance のアニメーションマッピング。
   → `idle_motion.ts`/dance(audio_reactivity)の状態→クリップ対応の設計参考。
3. **GitHub: hirokazuniimoto/virtual-avatar-sdk** — https://github.com/hirokazuniimoto/virtual-avatar-sdk
   自動まばたき+idle の軽量ランタイム。
   → まばたき/微動を core の idle 出力として薄く定義。
4. **GitHub: binzume/aframe-vrm** — https://github.com/binzume/aframe-vrm
   physics モジュール + startBlink/stopBlink。
   → blink 制御 API の参考。
5. **GitHub: tk256ailab/vrm-viewer** — https://github.com/tk256ailab/vrm-viewer
   VRMA(VRM Animation)対応ビューア。
   → VRMA 標準アニメーションとの連携。
6. **OBTAIN: Real-Time Beat Tracking in Audio Signals** — arxiv **1704.02216** — https://arxiv.org/abs/1704.02216
   OSS→CBSS→peak で実時間ビート追跡。
   → ★ `audio_reactivity.detectBeat`/`estimateTempo` を OSS→CBSS パイプラインで堅牢化。
7. **Beat Tracking as Object Detection** — arxiv **2510.14391** — https://arxiv.org/abs/2510.14391
   ビート追跡を物体検出として再定式化。
   → 将来的な高精度化の参照(現状は軽量手法維持)。
8. **Towards an efficient deep learning model for musical onset detection** — arxiv **1806.06773** — https://arxiv.org/pdf/1806.06773
   パラメータ 28.3% の軽量 onset 検出。
   → 軽量・オンデバイス志向の onset 特徴の参考。
9. **GitHub Topic: procedural-animation** — https://github.com/topics/procedural-animation
   手続き的アニメーション OSS 群。
   → idle の手続き生成手法の比較。
10. **GitHub: idovelemon/PerlinNoise**(+ simplexIdle gist https://gist.github.com/Sjeiti/7145c2fe1a3468be87d2) — https://github.com/idovelemon/PerlinNoise
    Perlin/Simplex ノイズによる「生命感のある」微動。
    → ★ `idle_motion.ts` に **Perlin/Simplex ノイズ + 呼吸(sine+ノイズ)** を導入し機械的反復を排除。

**改善点まとめ(カテゴリ9)**: ①`detectBeat` を OSS→CBSS で堅牢化(#6)、②`idle_motion` に Perlin/Simplex+呼吸(#10)、
③`spring.ts` を three-vrm spring bone と互換パラメータ化(#1)、④idle/dance の状態→クリップ対応整備(#2)。

---

## 10. プライバシー保護/オンデバイス知能(local LLM/TTS, BYOK, zero-dep)

1. **GitHub: mlc-ai/web-llm** — https://github.com/mlc-ai/web-llm
   ★ **OpenAI API 互換** の in-browser LLM 推論(WebGPU、サーバ不要)。
   → `ai_chat.ts` の BYOK プロバイダに **"local"(web-llm)** を追加。完全ローカル会話を実現(差別化軸を強化)。
2. **GitHub: RunanywhereAI/on-device-browser-agent** — https://github.com/RunanywhereAI/on-device-browser-agent
   WebLLM ベースの完全ローカル・no API key エージェント。
   → ローカル専用モードの設計参考。
3. **GitHub: hannes-sistemica/browser-llm-webgpu** — https://github.com/hannes-sistemica/browser-llm-webgpu
   transformers.js + ONNX Runtime Web でブラウザ推論。
   → WASM フォールバック経路の参考(GPU 無し環境)。
4. **GitHub: clowerweb/tts-studio** — https://github.com/clowerweb/tts-studio
   Kitten(24MB)/Piper(75MB)/Kokoro(82MB)をブラウザ内で実行。
   → ★ TTS インターフェースを core に薄く定義し、ローカル TTS を差し込み可能に。
5. **GitHub: steveseguin/tts.rocks** — https://github.com/steveseguin/tts.rocks
   Kokoro+Piper+eSpeak のブラウザ TTS。
   → 無料・オフライン TTS の実装参考。
6. **Xenova: Kokoro TTS v1.0 100% ローカル(WebGPU)** — https://huggingface.co/posts/Xenova/620657830533509
   10秒の音声を ~1秒で生成、サーバ不要。
   → リアルタイム発話の実現可能性の根拠。
7. **Improving User Privacy in Personalized Generation** — arxiv **2601.17569** — https://www.arxiv.org/pdf/2601.17569
   個人化を **完全オンデバイス** で行いサーバへ情報を出さない。
   → satin の「全状態をローカル保持」設計の裏付け・強化指針。
8. **Privacy-Preserving Bandits** — arxiv **1909.04421** — https://arxiv.org/pdf/1909.04421
   バンディット学習をプライバシー保護下で実施。
   → カテゴリ4(`bandit.ts`)をローカル/LDP 前提で安全に。
9. **Privacy-Preserving Graph Embedding based on Local Differential Privacy** — arxiv **2310.11060** — https://arxiv.org/html/2310.11060v2
   LDP の基礎(ローカル摂動で原データを端末に留める)。
   → 将来のオプトイン・テレメトリに LDP を適用する際の指針。
10. **GitHub Topic: on-device-ai (TypeScript)** — https://github.com/topics/on-device-ai?l=typescript
    オンデバイス AI の TS エコシステム。
    → ゼロ依存・型付き実装の探索源。

**改善点まとめ(カテゴリ10)**: ①`ai_chat.ts` に local(web-llm)プロバイダ追加で完全ローカル会話(#1,#2)、
②core に薄い TTS インターフェース→ローカル TTS(Kokoro/Piper)差込(#4,#5,#6)、
③オンデバイス個人化・LDP の裏付けで「プライバシーファースト」を強化(#7,#8,#9)。

---

## 総括(横断的な最優先改善)

全10カテゴリの調査から、**差別化軸(完全ローカル・ゼロ依存・プライバシー)を強化しつつ体験を底上げする**順で:

1. **反シンコファンシー + 依存防止**(§8,§2,§1)— 倫理・差別化・低コストで効果大。
2. **文脈付きバンディット + breakpoint 適時化**(§4,§3)— `thoughtworks/simplebandit` 方式で中核体験を底上げ。
3. **BOCPD 変化点検知**(§5)+ **階層メモリ/忘却**(§6)— アルゴリズム的に明確な堅牢化。
4. **感情推定の個人ベースライン化 + 不確実性**(§1)/ **概日 ~8h 窓・規則性**(§7)。
5. **idle に Perlin+呼吸 / detectBeat 堅牢化**(§9)+ **local LLM/TTS プロバイダ**(§10)— プロダクト体験とローカル路線の強化。

全提案は「pure function・ゼロ依存・型付き・オンデバイス」を堅持し、`arxiv_improvements`/`arxiv_round2`
同様に **出典付き単体テスト** を添えて実装する。本ファイルの全 URL は web 検索で実在確認済み(2026-06-05)。
- 6. 長期記憶 — 同 §D(RMM/TiMem/Amory)+ ReMe / LD-Agent / Agent-Memory-Paper-List。
- 7. 概日/睡眠 — 同 §F。
- 8. 安全性/ウェルビーイング — 同 §A。
- 9. アバター身体性 — VRM/Live2D・spring 物理・ビート検出の arxiv/GitHub を新規調査。
- 10. オンデバイス/プライバシー — local LLM(llama.cpp 系)・on-device TTS・BYOK の新規調査。
