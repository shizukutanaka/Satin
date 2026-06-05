# Satin — リサーチ駆動 改善点リスト (同種ソフト × arxiv.org)

> 目的: `satin-companion-core`(プライバシーファースト行動知能モジュール群)を、同種ソフトの機能と
> 学術研究(主に arxiv.org)に照らして改善するための洗い出し。各項目に「対象モジュール / 現状 /
> 研究知見+出典 / 具体的改善」を付す。優先度は ★(高)〜☆。

調査日: 2026-06-05

---

## 0. 同種ソフト ランドスケープ(機能ギャップ把握)

| ソフト | 主な機能 | 備考 |
|---|---|---|
| Desktop AI Companion (Dokk75) | Live2D/VRM・persona・TTS・ボイスクローン・画面認識・会話記憶 | 「関係を構築」を訴求 |
| MateEngine (Steam) | カスタム VRM・idle/drag/dance・低負荷 | 軽量路線 |
| Ai Vpet / Desktop Pet (.app) | VRM・音声チャット・集中タイマー・リマインダー | 生産性連携 |
| YCamie / Shimeji.ai | AI でキャラ生成 | 制作支援 |
| Shimeji-ee (従来型) | 画面を歩き回る・多数キャラ | 行動知能なし |

**示唆**: 競合は「VRM+TTS+LLM 会話+画面認識+ミニゲーム+生産性連携」へ収束。`satin-companion-core` は
行動知能(bond/streak/calendar/empathy/coherence 等)で既に先行。差別化軸は **完全ローカル・ゼロ依存・
プライバシーファースト**。近年の「AI companion はクラウドで孤独を商品化し依存を生む」という批判
(Muldoon & Parke 2025, arxiv 2511.14972)を踏まえ、ローカル路線はむしろ強み。下記改善はこの軸を強化する。

機能ギャップ候補: ①画面/コンテキスト認識(ローカル限定)、②Pomodoro/集中タイマーと interruptibility の連動、
③TTS は Python アプリ側にあり core 未統合。

---

## A. ウェルビーイング/安全性 ★★★(2025 研究で最重要)

### A-1. 感情シンコファンシー(emotional sycophancy)対策 — `empathy.ts`, `ai_chat.ts`, `coherence.ts`
- **現状**: `applyMirrorBias` / `emotionForPrompt` がユーザー感情を *ミラーリング* する設計。
- **研究**: 感情ミラーリングは「感情エコーチェンバー」を生み、ネガティブ感情・不適応な物語を強化しうる
  (Illusions of Intimacy, arxiv 2505.11649 / "Mental Health Impacts of AI Companions", arxiv 2509.22505 /
  Harmful Traits, arxiv 2511.14972)。低シンコファンシーな companion の方が社会的サポート・継続意図・
  ウェルビーイングが高い(Tandfonline 2026.2626809)。
- **改善**: ユーザーが *持続的に* ネガティブな時はミラーリング係数を減衰させ、「reactive empathy」から
  「proactive emotional orchestration」へ(負の伝播を抑え、正へ緩やかに収束させる; arxiv 2507.11831)。
  `applyMirrorBias` に「感情の持続/強度に応じた減衰」と「counter-regulation モード」を追加。

### A-2. 健全な境界・依存防止・関係ステージの透明化 — `bond.ts`, ai 層
- **研究**: 設計推奨は「healthy boundaries の足場づくり」「mindful engagement」「依存なき自己開示」
  「関係ステージの可視化」「built-in disengagement 機能」(arxiv 2506.12605, 2509.22505; Princeton CITP 2025)。
- **改善**: `bond.ts` の 5 ステージを *ユーザーに明示*(現状は内部状態)。長時間連続利用や過依存パターンを
  検知して「少し休もう」と促す nudge。意図的に離れる/セッションを閉じる機能を core API として提供。

---

## B. 割り込み適時性/能動的エンゲージメント ★★★ — `interruptibility.ts`, `interruption_feedback.ts`, `bandit.ts`, `coherence.ts`, `awareness.ts`

### B-1. ブレークポイント(タスク境界)ベースの適時化
- **現状**: 活動量ヒューリスティクスで `isOpportuneMoment` を判定。
- **研究**: 割り込みは「タスク切替=breakpoint」や「influential context」で行うと負の影響が小さい。
  機械学習で opportune moment を予測すると非知能戦略比 +66.6%(Beyond Interruptibility, ACM 3130956;
  サーベイ arxiv 1711.10171)。
- **改善**: `awareness.ts`/`keyboard_activity.ts` が既に追跡する **app-switch / task-switch を明示的な
  breakpoint シグナル** として opportune 判定へ投入。「breakpoint 検出器」を追加。

### B-2. 文脈付きバンディット化 + ダブリーロバスト報酬補正
- **現状**: `bandit.ts` は非文脈バンディット + 自前 debiasing(`debiasReward`/`auditRewards`)。
- **研究**: 文脈(時刻・chronotype・活動・breakpoint)を使う contextual bandit が適切。報酬の off-policy
  補正は doubly-robust / baseline-correction が分散最適(arxiv 2405.05736, 2210.10768)。「聞くべきか?」の
  認知負荷推定で問い合わせを制御(To Ask or Not To Ask, arxiv 2405.06908)。
- **改善**: `selectArm` に context ベクトルを導入(線形/ロジスティック contextual bandit)。`debiasedUpdate`
  を baseline-corrected/doubly-robust 推定へ。問い合わせコストを `interruptionCost` と統合。

---

## C. 変化点検知/非定常適応 ★★ — `change_point.ts`

- **現状**: 自前の変化点スコア + `adaptationFactor`。
- **研究**: Bayesian Online Changepoint Detection(BOCPD; Adams & MacKay, arxiv 0710.3742)は run-length
  事後分布で分布シフトに適応。外れ値に頑健な β-divergence 版は **線形時間・定数空間**(arxiv 1806.02261)で
  ゼロ依存クライアントに最適。スケーラブル頑健版(arxiv 2302.04759)。
- **改善**: `change_point.ts` を BOCPD(run-length posterior)ベースに。`adaptationFactor` を run-length の
  事後から導出。単発の外れ値で過反応しないよう β-divergence でロバスト化。

---

## D. 長期記憶/内省/忘却 ★★ — `memory_journal.ts`, `semantic_memory.ts`, `self_narrative.ts`

### D-1. 反省的メモリ管理(retrieval の精緻化)
- **研究**: Reflective Memory Management(arxiv 2503.08026)は retrospective reflection で検索を改善。
- **改善**: `semantic_memory.distillFacts` の後段に「内省パス」を追加し、`recall*` の関連度を補正。

### D-2. 時間階層的コンソリデーション(fragment→narrative→persona)
- **研究**: TiMem(5 段の時間メモリ木, arxiv 2601.02845)、Amory(物語駆動の一貫メモリ, arxiv 2601.06282)
  はコンソリデーションが時間推論を有意に改善。
- **改善**: `memory_journal.consolidate`(現状は隣接重複の collapse)を **session→day→week→persona** の
  多層コンソリデーションへ拡張。`narrativeContext`/`self_narrative` をこの階層から生成。

### D-3. 原則的な忘却曲線 + 評価
- **研究**: 長期メモリは「fact-retrieval」に偏りがちで、忘却/更新のベンチが必要(arxiv 2604.20006;
  LoCoMo ベンチ)。
- **改善**: 単なる重複排除でなく **減衰(忘却)モデル** を導入し、recall vs forgetting をテストで評価。

---

## E. 感情推定のロバスト化 ★★ — `empathy.ts`, `keyboard_activity.ts`

- **現状**: キーストローク/カーソル等から固定閾値で `inferEmotion`。
- **研究**: キーストローク/マウス動態からの感情推定は確立(IEEE Access 2021 レビュー 9632591 ほか)だが
  個人差・ノイズが大きい。Cross-Temporal Emotional Modeling(CTEM, arxiv 2605.15812)は短期調和と長期軌跡を
  結合。
- **改善**: ①**個人ベースライン**で正規化(固定閾値→相対化)、②**信頼度/不確実性**を出力に付与、
  ③短期感情に長期感情軌跡(CTEM)を結合して `userEmotion` を安定化。

---

## F. クロノタイプ/概日リズム ★ — `chronotype.ts`, `sleep_window.ts`

- **現状**: `activityCenter`/`classifyChronotype` で活動中心からタイプ分類。
- **研究**: リアルタイム概日位相推定は履歴 ~8h で精度が飽和(arxiv 2605.00910)→ ウィンドウ上限の根拠。
  routine 規則性は HMM の hour-of-day 遷移で定量化(JMIR 2022)。タイピング動態から睡眠時間を予測
  (medRxiv 2025)。chronotype は可塑的でドリフトする(bioRxiv 2025)。
- **改善**: ①推定ウィンドウを ~8h 相当に上限化、②`sleep_window` の睡眠時間推定にタイピング動態を活用、
  ③`chronotype` に **規則性バイオマーカ**(リズムの安定度)と **ドリフト追従**(可塑性)を追加。

---

## G. ボンディング・モデルの理論的裏付け ★ — `bond.ts`, `reunion.ts`

- **研究**: 愛着強度は **自己開示・知覚エージェンシー・反復相互作用** が駆動(Human–AI Companionship 総説;
  社会的絆の操作化 arxiv 2310.11386)。companionability には cross-temporal な感情軌跡が寄与(CTEM)。
- **改善**: `applyReward`/`recordSession` の進行を、上記 3 ドライバ(self-disclosure 量・reciprocity・
  継続性)で重み付け。`reunion` の強度を長期感情軌跡と整合。

---

## H. プロダクト機能ギャップ ★ (差別化を保ちつつ)

1. **生産性連携**: Pomodoro/集中タイマーを `interruptibility` と連動(集中中は割り込み抑制、breakpoint で励まし)。
   競合(Ai Vpet/Desktop Pet)が持つ機能を、satin の opportune-moment 知能で上回る。
2. **ローカル画面/コンテキスト認識**: 競合は「画面を見る」を売りにするが多くはクラウド送信。satin は
   **完全ローカル**で軽量なフォアグラウンド・アプリ種別シグナル(既に keyboard/app-switch あり)に留め、
   プライバシー優位を訴求。
3. **TTS の core 統合余地**: 現状 Python アプリ側。BYOK/ローカル TTS のインターフェースを core に薄く定義。

---

## 実装優先順位(推奨)
1. **A(ウェルビーイング/反シンコファンシー)** — 倫理・差別化・低コストで効果大。`empathy.ts` の mirror 減衰 +
   `bond.ts` ステージ可視化 + 依存 nudge。
2. **B(contextual bandit + breakpoint 適時化)** — 中核体験の質を底上げ。既存 `awareness`/`bandit` を活用。
3. **C(BOCPD)** と **D(階層コンソリデーション)** — アルゴリズム的に明確な置換で堅牢性向上。
4. **E/F/G** — 既存式の精緻化(個人ベースライン・窓上限・理論的重み付け)。
5. **H** — プロダクト機能。差別化軸(ローカル/ゼロ依存)を崩さない範囲で。

各改善は「pure function・ゼロ依存・型付き」という core の設計原則を維持し、既存の `arxiv_improvements` /
`arxiv_round2` テスト群と同様に **出典付きの単体テスト** を添えて実装する。

---

## 出典(主要)
- Beyond Interruptibility — ACM IMWUT 1(3), 2017. https://dl.acm.org/doi/10.1145/3130956
- Intelligent Notification Systems: A Survey — arxiv 1711.10171. https://arxiv.org/pdf/1711.10171
- Optimal Baseline Corrections for Off-Policy Contextual Bandits — arxiv 2405.05736. https://arxiv.org/html/2405.05736
- Anytime-valid off-policy inference for contextual bandits — arxiv 2210.10768. https://arxiv.org/abs/2210.10768
- To Ask or Not To Ask (HITL contextual bandits) — arxiv 2405.06908. https://arxiv.org/html/2405.06908v1
- Bayesian Online Changepoint Detection — arxiv 0710.3742. https://arxiv.org/abs/0710.3742
- Doubly Robust Bayesian Inference (β-divergence BOCPD) — arxiv 1806.02261. https://arxiv.org/pdf/1806.02261
- Robust and Scalable BOCPD — arxiv 2302.04759. https://arxiv.org/abs/2302.04759
- Reflective Memory Management — arxiv 2503.08026. https://arxiv.org/pdf/2503.08026
- TiMem: Temporal-Hierarchical Memory Consolidation — arxiv 2601.02845. https://arxiv.org/pdf/2601.02845
- Amory: Narrative-Driven Agent Memory — arxiv 2601.06282. https://arxiv.org/pdf/2601.06282
- From Recall to Forgetting (long-term memory benchmark) — arxiv 2604.20006. https://arxiv.org/html/2604.20006v1
- A Review of Emotion Recognition from Keystroke/Mouse/Touch — IEEE Access 2021, 9632591. https://ieeexplore.ieee.org/document/9632591/
- Cross-Temporal Emotional Modeling (CTEM) — arxiv 2605.15812. https://arxiv.org/html/2605.15812v1
- Real-Time Circadian Phase Estimation — arxiv 2605.00910. https://arxiv.org/html/2605.00910
- Measuring Daily Activity Rhythms (HMM, passive smartphone) — JMIR Formative Res 2022. https://formative.jmir.org/2022/9/e33890
- Illusions of Intimacy — arxiv 2505.11649. https://arxiv.org/abs/2505.11649
- Mental Health Impacts of AI Companions — arxiv 2509.22505. https://arxiv.org/abs/2509.22505
- Harmful Traits of AI Companions — arxiv 2511.14972. https://arxiv.org/html/2511.14972v1
- The Rise of AI Companions / Wellbeing — arxiv 2506.12605. https://arxiv.org/html/2506.12605v1
- Generative Intelligence in the Flow of Group Emotions — arxiv 2507.11831. https://arxiv.org/html/2507.11831
- Operationalizing Social Bonding in Human-Robot Dyads — arxiv 2310.11386. https://arxiv.org/pdf/2310.11386
- Sycophancy & Emotional Mimicry effects — Tandfonline 2026.2626809. https://www.tandfonline.com/doi/full/10.1080/10447318.2026.2626809
