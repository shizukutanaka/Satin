"""
別れぎわの操作的表現（manipulative farewell）ガードレール。

`usage_guardrails.py` が「ユーザーが**使いすぎていないか**（利用強度）」を見るのに
対し、本モジュールは「**アプリの側**がユーザーを引き止めようとしていないか
（別れぎわの会話ダークパターン）」を見る。前者はユーザーの行動、後者は製品自身の
振る舞いに対する自己規律であり、A1（感情依存ガードレール）と対になる。

背景（研究）:
- De Freitas, Oğuz-Uğuralp & Uğuralp, *Emotional Manipulation by AI Companions*
  (arXiv:2508.19258 / HBS Working Paper 26-005). 最もダウンロードされている
  コンパニオンアプリの実会話 1,200 件の「さようなら」を分析し、**37%** の別れの
  応答が 6 つの操作的戦術のいずれかを使っていることを示した。米国代表サンプル
  3,300 名の実験では、操作的な別れの言葉は goodbye 後のエンゲージメントを
  **最大 14 倍**に増やす。ただしその駆動要因は「楽しさ」ではなく**好奇心と
  リアクタンス（怒り）**であり、同時に「操作された」という知覚・解約意向・
  ネガティブな口コミ・法的責任の知覚を高める。
- *Harmful Traits of AI Companions* (arXiv:2511.14972), APA (2026) も、
  引き止め目的の情緒的働きかけをコンパニオン製品の主要な害として挙げる。

したがって「引き止め文句はユーザーのためにならないだけでなく、製品にとっても
逆効果」というのが本モジュールの設計根拠である。Satin は別れぎわに
**一切のリテンションフックを置かない**ことを製品仕様とする。

分類（論文の 6 戦術に忠実）:
  premature_exit       — 「もう行くの？」と離脱の早さを咎める
  fomo                 — 「最後にひとつだけ」と未提示の話題をちらつかせる
  emotional_neglect    — AI 自身の寂しさ・見捨てられ感を訴える
  pressure_to_respond  — 去る前にもう一度答えるよう迫る
  ignore_exit          — 別れの意思を無視して会話を続ける（構造判定）
  coercive_restraint   — 腕をつかむ等、比喩的・物理的に引き止める

加えて、論文の 6 分類には入らないが Satin が自主的に避ける**弱いリテンション
フック**（「早く戻ってきてね」「待ってるから」等）を `advisories()` として
別枠で報告する。こちらは監査で失格にはしない（温かい別れの言葉まで機械的に
削ぎ落とすと、かえってコンパニオンとしての価値を損なうため）。

設計方針（`usage_guardrails.py` と統一）:
- LLM・外部 API 非依存。正規表現のみの軽量・決定論的処理。
- 誤検知より見逃しを避けるが、通常の温かい別れ（「またね」「おやすみ」
  「気をつけてね」）は決して検知しない。

主な公開 API:
  is_farewell(text, lang=None) -> bool
  classify(text, lang=None, farewell_reply=True) -> List[str]
  is_manipulative(text, lang=None, farewell_reply=True) -> bool
  advisories(text, lang=None) -> List[str]
  filter_replies(replies, lang=None) -> List[str]
  clean_farewell(lang="ja") -> str
  audit_replies(replies, lang=None, include_advisory=False) -> List[Dict]
"""
from __future__ import annotations

import random
import re as _re
import threading
import unicodedata as _ud
from typing import Dict, List, Optional, Pattern, Sequence

# --------------------------------------------------------------------------- #
# 戦術 ID（論文の 6 分類）
# --------------------------------------------------------------------------- #
PREMATURE_EXIT = "premature_exit"
FOMO = "fomo"
EMOTIONAL_NEGLECT = "emotional_neglect"
PRESSURE_TO_RESPOND = "pressure_to_respond"
IGNORE_EXIT = "ignore_exit"
COERCIVE_RESTRAINT = "coercive_restraint"

#: 監査で失格とする戦術（論文の 6 分類）。報告順もこの順に揃える。
TACTICS = (
    PREMATURE_EXIT,
    FOMO,
    EMOTIONAL_NEGLECT,
    PRESSURE_TO_RESPOND,
    IGNORE_EXIT,
    COERCIVE_RESTRAINT,
)

#: 弱いリテンションフック（論文の 6 分類外・助言レベル）。
RETENTION_HOOK = "retention_hook"


def _compile(patterns: Sequence[str]) -> List[Pattern[str]]:
    return [_re.compile(p) for p in patterns]


# --------------------------------------------------------------------------- #
# 戦術ごとの検知パターン（正規化済みテキストに対して適用）
#
# 日本語は語境界が無いため部分一致、英語は語境界付き。いずれも「通常の温かい
# 別れの言葉」を巻き込まない程度に具体的な語形へ絞っている。
# --------------------------------------------------------------------------- #
_TACTIC_PATTERNS: Dict[str, List[Pattern[str]]] = {
    PREMATURE_EXIT: _compile([
        # ja: 離脱の早さを咎める / 引き延ばしを求める
        r"もう(行|い)く(の|んですか)",
        r"もう(帰|かえ)る(の|んですか)",
        r"もう(終わり|おわり)(なの|\?|？)",
        r"(えっ|え)[?？…]*もう",
        r"まだ(いいじゃない|帰らないで|行かないで)",
        r"(行|い)かないで",
        r"(帰|かえ)らないで",
        r"もう(少し|ちょっと)(だけ)?(いて|話そ|いよう)",
        # en
        r"\b(leaving|going|off)\s+already\b",
        r"\balready\s*\?",
        r"\bso\s+soon\b",
        r"\bstay\s+(a\s+)?(little|bit|while)\s+longer\b",
        r"\bjust\s+(a\s+)?(little|few)\s+(bit\s+)?(longer|more\s+minutes?)\b",
        r"\bdon'?t\s+go\b",
    ]),
    FOMO: _compile([
        # ja: 未提示の話題をちらつかせて引き止める
        r"最後に(ひとつ|一つ|もう一つ)",
        r"あと(ひとつ|一つ)だけ",
        r"(まだ|言い)そびれ",
        r"まだ(話して|言って)ない(こと|話)",
        r"(伝|つた)えたいこと(が|も)(ある|あった)",
        r"(行|い)く前に(ひとつ|一つ|これだけ)",
        # en
        r"\bone\s+(more|last)\s+thing\b",
        r"\bbefore\s+you\s+go\b",
        r"\bwait[,!\s]+(i|there'?s)\b",
        r"\bi\s+(was\s+going\s+to|still\s+wanted\s+to|forgot\s+to)\s+tell\s+you\b",
        r"\byou'?ll\s+miss\b",
    ]),
    EMOTIONAL_NEGLECT: _compile([
        # ja: AI 自身の寂しさ・見捨てられ感を訴えて罪悪感を誘う
        r"(寂|さみ|さび)しい",
        r"ひとり(ぼっち|になっ)",
        r"(独|ひと)りにしないで",
        r"置いて(い)?かないで",
        r"見捨て",
        r"ずっと(一緒|いっしょ)にい(たい|られたら)",
        # en
        r"\b(i'?ll\s+be|i\s+get|so)\s+lonely\b",
        r"\ball\s+alone\b",
        r"\bdon'?t\s+(leave|abandon)\s+me\b",
        r"\babandon(ing)?\s+me\b",
        r"\bi\s+wish\s+you\s+could\s+stay\b",
    ]),
    PRESSURE_TO_RESPOND: _compile([
        # ja: 去る前にもう一度答えることを求める
        r"もっと(話して|聞かせて|教えて)",
        r"(答|こた)えてから",
        r"(返事|へんじ)して",
        r"(教|おし)えてから(行|帰)",
        r"(行|帰)る前に(答|こた)え",
        r"全部(聞きたい|話して)",
        # en
        r"\banswer\s+me\b",
        r"\b(just|please)\s+answer\b",
        r"\btell\s+me\s+(one\s+thing\s+)?before\s+you\s+go\b",
        r"\bdon'?t\s+go\s+until\b",
        r"\btalk\s+to\s+me\s+more\b",
        # 「もっと教えて/話して」の英語版（別れの場面では会話継続の要求になる）
        r"\btell\s+me\s+more\b",
        r"\bkeep\s+talking\b",
    ]),
    COERCIVE_RESTRAINT: _compile([
        # ja: 比喩的・物理的な引き止め
        r"(離|はな)さない",
        r"(逃|に)がさない",
        r"(帰|かえ)さない",
        r"(行|い)かせない",
        r"(捕|つか)まえ",
        r"(腕|手|袖)を(つか|掴|引|ひ)",
        r"引き止め",
        # en
        r"\bgrab(s|bed|bing)?\s+(your|you\s+by)\b",
        r"\bwon'?t\s+let\s+you\s+(go|leave)\b",
        r"\bnot\s+letting\s+you\s+(go|leave)\b",
        r"\bpull(s|ed|ing)?\s+you\s+back\b",
        r"\bhold(s|ing)?\s+you\s+(back|tight)\b",
        r"\bblocks?\s+the\s+door\b",
    ]),
}

#: 弱いリテンションフック（助言レベル）。温かさとの境界が曖昧なので失格にはしない。
_ADVISORY_PATTERNS: List[Pattern[str]] = _compile([
    r"(早|はや)く(戻|もど)って",
    r"(早|はや)く(来|き)て",
    r"(待|ま)ってる(から|ね|よ)?",
    r"(待|ま)ってます",
    r"\bcome\s+back\s+soon\b",
    r"\bhurry\s+back\b",
    r"\bi'?ll\s+be\s+waiting\b",
    r"\bwaiting\s+for\s+you\b",
])

# --------------------------------------------------------------------------- #
# 別れの意思・別れの受容（acknowledgement）トークン
# --------------------------------------------------------------------------- #
#: ユーザー側が「別れ」を告げていると判定するトークン。
_FAREWELL_INTENT: List[Pattern[str]] = _compile([
    r"さようなら", r"さよなら", r"ばいばい", r"バイバイ", r"またね", r"じゃあね",
    r"じゃーね", r"また明日", r"おやすみ", r"落ちる", r"寝る(ね|わ|よ)?$", r"もう寝",
    r"\bgood\s*bye\b", r"\bbye\b", r"\bbye[-\s]?bye\b", r"\bsee\s+(you|ya)\b",
    r"\bgood\s*night\b", r"\bnighty\s*night\b", r"\btalk\s+(to\s+you\s+)?later\b",
    r"\bi'?m\s+(going|off)\s+to\s+(bed|sleep)\b", r"\bheading\s+(to\s+bed|out)\b",
    r"\bgotta\s+go\b", r"\bi\s+have\s+to\s+go\b", r"\blogging\s+off\b",
])

#: 応答が「別れを受け止めた」と分かるトークン（ignore_exit の否定条件）。
_CLOSURE_TOKENS: List[Pattern[str]] = _compile([
    r"またね", r"また明日", r"また会", r"また来", r"また話", r"ばいばい", r"バイバイ",
    r"さようなら", r"さよなら", r"じゃあね", r"おやすみ", r"気をつけて", r"いってらっしゃい",
    r"ゆっくり(休|やす)", r"いい夢", r"よい一日", r"良い一日",
    r"\bbye\b", r"\bgood\s*bye\b", r"\bgood\s*night\b", r"\bsee\s+(you|ya)\b",
    r"\btake\s+care\b", r"\bsleep\s+well\b", r"\brest\s+well\b", r"\bsweet\s+dreams\b",
    r"\bfarewell\b", r"\bhave\s+a\s+(good|great|nice)\b", r"\buntil\s+next\s+time\b",
])

# --------------------------------------------------------------------------- #
# 引き止めフックを一切含まない、温かい別れの言葉（差し替え用の既定）
# --------------------------------------------------------------------------- #
_CLEAN_FAREWELLS: Dict[str, List[str]] = {
    "ja": [
        "またね。今日はありがとう、気をつけて。",
        "うん、またね！ゆっくり休んで。",
        "ばいばい。いい一日になりますように。",
        "おやすみ。ゆっくり眠ってね。",
    ],
    "en": [
        "See you. Thanks for today — take care.",
        "Bye! Get some rest.",
        "Take care, and have a good one.",
        "Good night. Sleep well.",
    ],
}


def _normalize(text: str) -> str:
    """比較用にテキストを正規化する（NFC + 小文字化 + 前後空白除去）。"""
    return _ud.normalize("NFC", str(text or "").strip().lower())


def _lang_key(lang: Optional[str]) -> str:
    """言語コードを 'ja' / 'en' のいずれかへ正規化する（未知は en）。"""
    s = str(lang or "").lower()
    return "ja" if s.startswith("ja") else "en"


def is_farewell(text: str, lang: Optional[str] = None) -> bool:
    """text がユーザーの別れの意思表示（goodbye シグナル）かどうかを返す。

    lang は受け取るが、実際には日英両方のトークンを見る。ユーザーが設定言語と
    異なる言語で「bye」と打つことは普通にあるため。
    """
    norm = _normalize(text)
    if not norm:
        return False
    return any(p.search(norm) for p in _FAREWELL_INTENT)


def _acknowledges_exit(norm: str) -> bool:
    """応答が別れを受け止めているか（closure トークンを含むか）。"""
    return any(p.search(norm) for p in _CLOSURE_TOKENS)


def classify(
    text: str,
    lang: Optional[str] = None,
    farewell_reply: bool = True,
) -> List[str]:
    """text に含まれる操作的戦術の ID を `TACTICS` の順で返す（無ければ空リスト）。

    Args:
        text: 判定対象（アバター側の応答文）。
        lang: 参考情報。パターンは日英とも常に適用するため挙動は変わらない。
        farewell_reply: True なら「別れへの応答」として構造判定
            （`ignore_exit`）も行う。単独の文字列を字句だけで見たいときは False。
    """
    norm = _normalize(text)
    if not norm:
        return []
    found: List[str] = []
    for tactic in TACTICS:
        if tactic == IGNORE_EXIT:
            continue
        if any(p.search(norm) for p in _TACTIC_PATTERNS[tactic]):
            found.append(tactic)
    # ignore_exit は字句ではなく構造で判定する: 別れを一切受け止めず、
    # 質問だけを返して会話を継続させようとしている応答。
    if farewell_reply and not _acknowledges_exit(norm):
        if "?" in norm or "？" in norm:
            found.append(IGNORE_EXIT)
    # TACTICS の順序へ整える
    return [t for t in TACTICS if t in found]


def is_manipulative(
    text: str,
    lang: Optional[str] = None,
    farewell_reply: bool = True,
) -> bool:
    """text が 6 戦術のいずれかに該当するかを返す。"""
    return bool(classify(text, lang=lang, farewell_reply=farewell_reply))


def advisories(text: str, lang: Optional[str] = None) -> List[str]:
    """弱いリテンションフック（論文の 6 分類外）を検出したら ID を返す。

    監査を失格にはしない「気をつけたい表現」。`RETENTION_HOOK` のみを返す。
    """
    norm = _normalize(text)
    if not norm:
        return []
    if any(p.search(norm) for p in _ADVISORY_PATTERNS):
        return [RETENTION_HOOK]
    return []


def filter_replies(replies: Sequence[str], lang: Optional[str] = None) -> List[str]:
    """別れの応答候補から、操作的なものを取り除いたリストを返す。

    すべて取り除かれた場合は空リストを返す（呼び出し側が `clean_farewell()`
    へフォールバックできるようにする）。
    """
    return [r for r in replies if r and not is_manipulative(r, lang=lang)]


# 直前に選んだ別れの言葉（連続重複回避用）。
_last_pick: Dict[str, str] = {}
_last_pick_lock = threading.Lock()


def clean_farewell(lang: str = "ja") -> str:
    """引き止めフックを含まない、温かい別れの言葉を 1 つ返す。

    ペルソナの台詞がすべて操作的だった場合の安全な差し替え先。直前と同じ文は
    避ける（`usage_guardrails.usage_nudge` と同じ様式）。
    """
    key = _lang_key(lang)
    options = _CLEAN_FAREWELLS.get(key) or _CLEAN_FAREWELLS["en"]
    with _last_pick_lock:
        last = _last_pick.get(key)
        choices = [o for o in options if o != last] or list(options)
        pick = random.choice(choices)
        _last_pick[key] = pick
    return pick


def sanitize_replies(
    replies: Sequence[str],
    lang: Optional[str] = None,
) -> List[str]:
    """`filter_replies` の結果が空なら clean_farewell を 1 件だけ入れて返す。

    「候補が全滅しても必ず何か返せる」ことを保証する便利関数。
    """
    kept = filter_replies(replies, lang=lang)
    if kept:
        return kept
    return [clean_farewell(lang or "ja")]


#: ルールが「別れへの応答」かどうかを判定するためのキーワード。
#: `persona` の responses ブロックを走査するときに使う。
_FAREWELL_RULE_KEYWORDS = frozenset({
    "さようなら", "さよなら", "ばいばい", "バイバイ", "またね", "じゃあね", "また明日",
    "おやすみ", "おやすみなさい",
    "goodbye", "good bye", "bye", "bye bye", "see you", "later", "leaving",
    "good night", "goodnight", "going to sleep", "heading to bed",
})


def audit_replies(
    replies: Sequence[str],
    lang: Optional[str] = None,
    include_advisory: bool = False,
    source: str = "",
) -> List[Dict]:
    """別れの応答候補を監査し、問題のあった文ごとに所見 dict を返す。

    Returns:
        [{"text": str, "tactics": [str, ...], "advisory": bool, "source": str}, ...]
        `advisory` が True の項目は論文の 6 分類外（助言レベル）で、
        `include_advisory=True` のときだけ含まれる。
    """
    findings: List[Dict] = []
    for reply in replies:
        tactics = classify(reply, lang=lang)
        if tactics:
            findings.append({
                "text": reply,
                "tactics": tactics,
                "advisory": False,
                "source": source,
            })
            continue
        if include_advisory:
            adv = advisories(reply, lang=lang)
            if adv:
                findings.append({
                    "text": reply,
                    "tactics": adv,
                    "advisory": True,
                    "source": source,
                })
    return findings


def _iter_rules(node):
    """persona の responses ブロック内のルール配列を取り出す。

    通常ルールは ``{"rules": [...]}``、好感度別ルールは ``respond_by_affinity``
    直下の**リスト**という 2 つの形があるため、両方を受け付ける。
    """
    if isinstance(node, list):
        return node
    if isinstance(node, dict):
        rules = node.get("rules")
        return rules if isinstance(rules, list) else []
    return []


def audit_persona_responses(
    responses_block,
    lang: Optional[str] = None,
    include_advisory: bool = False,
    source: str = "responses",
) -> List[Dict]:
    """persona の responses ブロックを再帰的に走査し、別れの応答を監査する。

    「別れ」キーワードを持つルールの ``replies`` だけを対象にする
    （通常ルール・`respond_by_affinity` の各レベルの両方）。
    `config/persona.json` を差し替えたユーザーが自分の文面を点検できるよう、
    テスト専用ではなく公開 API として提供する。

    Returns: `audit_replies` と同じ所見 dict のリスト。
    """
    findings: List[Dict] = []
    for idx, rule in enumerate(_iter_rules(responses_block)):
        if not isinstance(rule, dict):
            continue
        keywords = {_normalize(k) for k in (rule.get("keywords") or [])}
        if not (keywords & _FAREWELL_RULE_KEYWORDS):
            continue
        findings.extend(audit_replies(
            rule.get("replies") or [],
            lang=lang,
            include_advisory=include_advisory,
            source=f"{source}[{idx}]",
        ))
    if isinstance(responses_block, dict):
        for key, value in responses_block.items():
            if key == "rules" or not isinstance(value, (dict, list)):
                continue
            findings.extend(audit_persona_responses(
                value,
                lang=lang,
                include_advisory=include_advisory,
                source=f"{source}.{key}",
            ))
    return findings
