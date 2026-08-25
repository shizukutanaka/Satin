"""日常的なつらさ（bad day / ストレス / 孤独感）の検知。

`crisis_support` が扱うのは自傷・自殺念慮という**危機**であり、その閾値は
意図的に狭く保たれている（広げると誤検知で相談先案内が乱発され、本当に必要な
ときの重みが失われる）。一方 `mood.classify_sentiment` が見ているのは
「ユーザーがアバターをどう思っているか」（好き / 嫌い）で、好感度を動かすための
判定である。

その 2 つの間に、**コンパニオンが最も頻繁に受け取る開示**が丸ごと落ちていた。

    「今日はしんどかった」  → 「そっか、いいね。」
    「イライラする」        → 「そっか、いいね。」
    "I feel lonely"        → "Nice, sounds good."
    "I'm burnt out"        → "That's interesting!"

キーワード辞書に無い言い回しは汎用フォールバックへ落ち、そのフォールバックが
一律に明るいため、**悪い知らせに「いいね」と返していた**。単に的外れなのでは
なく、聞いていないこと（あるいは茶化していること）を能動的に示してしまう。
つらさを打ち明けられる相手であることが本製品の主要な価値なので、ここは
中核機能の欠落である。

設計方針:
- `crisis_support` と同じ規律: LLM・外部 API 非依存、キーワード + 否定/慣用句
  除外のみの決定論的判定。検知しなければ空を返し、呼び出し側は通常フローを続ける。
- **危機とは別物**。ここで検知しても相談先の案内はしない（それは過剰反応で、
  「疲れた」と言っただけで命の電話を案内される体験は不快である）。
  crisis_support が先に評価され、そちらが検知した場合はこのモジュールを通さない。
- **語幹で拾う**。日本語は活用するので「しんどい」だけを見ると「しんどかった」を
  取りこぼす。語幹（「しんど」）で持つ。
- 否定（「疲れてない」/ "not stressed"）と、肯定文脈での併記
  （「疲れたけど楽しかった」）は検知しない。

限界: これは感情分析ではなく、言い回しの網である。網に無い表現は拾えない。
拾えなかった場合も、フォールバックが「いいね」と決めつけないよう
`persona.json` 側の汎用フォールバックから価値判断を取り除いてある — 検知の
失敗が「悪い知らせに喜ぶ」に化けない二重の備え。

主な公開 API:
    is_distressed(text) -> bool
    acknowledgement(lang="ja") -> str
"""
from __future__ import annotations

import random
import re as _re
import unicodedata as _ud
from typing import List, Optional, Pattern

# --------------------------------------------------------------------------- #
# 語彙
# --------------------------------------------------------------------------- #

# 日本語は活用するため語幹で持つ（「しんど」→ しんどい/しんどかった/しんどくて）。
_JA_PATTERNS: List[str] = [
    r"しんど", r"疲れ|つかれ", r"だる(い|かった|くて)", r"へと へと|へとへと",
    r"燃え尽き|もえつき", r"限界", r"いっぱいいっぱい", r"いっぱい いっぱい",
    r"ストレス", r"参った|まいった", r"きつ(い|かった)", r"大変(だった|な一日)",
    r"最悪", r"うまくいかな", r"失敗", r"落ち込", r"へこ(む|んだ)",
    r"つら(い|かった)|辛(い|かった)", r"悲し|かなし", r"泣(いた|きたい)",
    r"不安", r"心配", r"こわい|怖い", r"緊張",
    r"さみし|寂し|さびし", r"孤独", r"ひとりぼっち|独りぼっち",
    r"イライラ|いらいら", r"むしゃくしゃ", r"腹が立", r"むかつ",
    r"憂鬱|ゆううつ", r"やる気が(出ない|でない)", r"何もしたくな|なにもしたくな",
    r"眠れ(ない|なかった)", r"体調(が)?悪|具合(が)?悪",
]

_EN_PATTERNS: List[str] = [
    r"\b(rough|hard|bad|terrible|awful|long|tough)\s+(day|week|night|time)\b",
    r"\b(today|tonight|this\s+week|it|that)\s+(was|has\s+been|'?s\s+been)\s+"
    r"(a\s+)?(really\s+|so\s+|pretty\s+|very\s+)?"
    r"(rough|hard|bad|terrible|awful|long|tough|brutal)\b",
    r"\b(stressed|stressful|stress)\b", r"\boverwhelm(ed|ing)\b",
    r"\bburn(t|ed)\s*out\b", r"\bexhaust(ed|ing)\b", r"\bdrained\b",
    r"\bworn\s+out\b", r"\bfed\s+up\b", r"\bat\s+my\s+limit\b",
    r"\bcan'?t\s+(take|handle|cope)\b", r"\btoo\s+much\s+(right\s+now|today)\b",
    r"\b(sad|unhappy|miserable|upset|down|blue)\b", r"\bcrying\b|\bcried\b",
    r"\bdepress(ed|ing)\b", r"\bmiss(ing)?\s+(him|her|them|home)\b",
    r"\b(lonely|alone|isolated)\b", r"\bno\s+one\s+(to\s+talk|understands)\b",
    r"\b(anxious|anxiety|worried|worry|scared|afraid|nervous)\b",
    r"\b(frustrat(ed|ing)|annoyed|irritated|angry|mad|pissed)\b",
    r"\bnothing\s+(went|goes)\s+right\b", r"\bmessed\s+up\b",
    r"\b(failed|failing|screwed\s+up)\b", r"\bnot\s+(ok|okay|great|good|well)\b",
    r"\bcan'?t\s+sleep\b", r"\b(unmotivated|no\s+motivation)\b",
]

# 否定スコープ。これらが検知語の近くにあれば「つらくない」の意なので拾わない。
_NEGATION_PATTERNS: List[str] = [
    # 日本語: 「疲れてない」「しんどくない」「不安じゃない」
    r"(疲れ|つかれ|しんど|つら|辛|悲し|不安|寂し|さみし|孤独)"
    r"[^。！？!?]{0,6}?(ない|ないよ|ないです|なかった|ません|ませんでした)",
    # 英語: not / no longer / never + 検知語
    r"\b(not|never|no\s+longer|nothing)\b[^.!?]{0,20}?"
    r"\b(stressed|sad|lonely|tired|anxious|upset|worried|angry|down)\b",
    r"\b(stressed|sad|lonely|tired|anxious|upset|worried|angry|down)\b"
    r"[^.!?]{0,10}?\b(anymore|no\s+more)\b",
]

# 肯定的な締めくくり。つらさの語があっても全体としては良い報告なので拾わない
# （「疲れたけど楽しかった」「long day but it was great」）。
_POSITIVE_OVERRIDE_PATTERNS: List[str] = [
    r"(けど|けれど|が|ものの)[^。！？!?]{0,20}"
    r"(楽し|たのし|よかった|良かった|嬉し|うれし|幸せ|満足|充実)",
    r"\bbut\b[^.!?]{0,30}\b(great|good|fun|worth\s+it|happy|glad|amazing|"
    r"wonderful|rewarding|satisfying)\b",
]


def _compile(patterns: List[str]) -> List[Pattern[str]]:
    return [_re.compile(p, _re.IGNORECASE) for p in patterns]


_JA_RE = _compile(_JA_PATTERNS)
_EN_RE = _compile(_EN_PATTERNS)
_NEGATION_RE = _compile(_NEGATION_PATTERNS)
_POSITIVE_OVERRIDE_RE = _compile(_POSITIVE_OVERRIDE_PATTERNS)


# --------------------------------------------------------------------------- #
# 応答
# --------------------------------------------------------------------------- #
# 共感の一言だけ。助言もしないし、相談先も案内しない（それは crisis_support の
# 仕事で、日常の「疲れた」に対しては過剰反応になる）。質問で終わるものを混ぜて
# いるのは、話したければ続けられる余地を残すため — ただし答えを強制しない
# 言い方に留める（farewell_integrity と同じ規律）。
_ACKNOWLEDGEMENTS = {
    "ja": [
        "そっか…、大変だったね。",
        "うん、聞いてるよ。無理しないでね。",
        "それはしんどかったね。",
        "話してくれてありがとう。",
        "そっか。ひとりで抱えなくていいからね。",
        "うんうん。そう感じて当然だと思う。",
    ],
    "en": [
        "That sounds rough. I'm sorry.",
        "I hear you. Go easy on yourself.",
        "That sounds like a lot to carry.",
        "Thanks for telling me.",
        "You don't have to hold that on your own.",
        "Mhm. That makes sense to feel.",
    ],
}


def _normalize(text: str) -> str:
    """比較用にテキストを正規化する（NFC + 小文字化 + 前後空白除去）。"""
    return _ud.normalize("NFC", str(text or "").strip().lower())


def _lang_key(lang: Optional[str]) -> str:
    """言語コードを 'ja' / 'en' のいずれかへ正規化する（未知は en）。"""
    return "ja" if str(lang or "").lower().startswith("ja") else "en"


def is_distressed(text: str) -> bool:
    """text が日常的なつらさの表明かどうか。

    日英両方のパターンで判定する（設定言語と異なる言語で打たれても拾う）。
    否定表現と、つらさを認めつつ肯定で締める文は False を返す。
    """
    norm = _normalize(text)
    if not norm:
        return False
    if any(p.search(norm) for p in _POSITIVE_OVERRIDE_RE):
        return False
    if any(p.search(norm) for p in _NEGATION_RE):
        return False
    return any(p.search(norm) for p in _JA_RE) or any(p.search(norm) for p in _EN_RE)


def acknowledgement(lang: str = "ja") -> str:
    """つらさに対する共感の一言を返す。"""
    return random.choice(_ACKNOWLEDGEMENTS[_lang_key(lang)])


def acknowledgements(lang: str = "ja") -> List[str]:
    """その言語の共感メッセージ一覧（テスト・カスタマイズ用）。"""
    return list(_ACKNOWLEDGEMENTS[_lang_key(lang)])
