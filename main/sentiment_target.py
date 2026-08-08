"""
感情の**向き先**（誰について言っているか）の判定。

`mood.classify_sentiment` は文書レベルの極性しか返さない。それは
`user_wellbeing`（「ユーザー自身が今どう感じているか」）には正しい指標だが、
好感度（「ユーザーがわたしをどう扱ったか」）に流用すると向き先を取り違える。
実際、修正前の Satin では次のようになっていた:

    「自分が嫌い」        -> -1 -> 好感度が下がる
    "I hate myself"      -> -1 -> 好感度が下がる
    「今日は最悪な一日だった」-> -1 -> 好感度が下がる

つまり**弱音を吐いたユーザーほどアバターに嫌われる**。しかも好感度が下がると
応答は distant/reserved（「…そう。」「…うん。」）へ寄るので、つらいときほど
冷たくなるという最悪の向きに増幅する。

背景（技術）:
- 文書レベル極性は対象レベル極性の代用にならない。Entity-Level Sentiment
  Analysis のサーベイでは、**エンティティ単位の極性が文書全体の極性と一致する
  のは 47.7% にとどまる**と報告されている
  ([arXiv:2304.14241](https://arxiv.org/abs/2304.14241))。
  aspect/target-based sentiment analysis (ABSA) がそもそも独立した課題として
  存在するのはこのためで、極性だけを見て「誰に向けられたか」を推定することは
  できない ([ABSA サーベイ](https://link.springer.com/article/10.1007/s10462-024-10906-z))。
- A2 で引用した WRIME は**書き手/読み手自身の感情**のコーパスであり、
  「宛先への態度」のコーパスではない。好感度の入力として使うのは範疇の取り違え。
- コンパニオンがリスク開示や苦痛の表明に対して引いてしまう失敗は既知
  （Sentio 2026 / IASEAI、`crisis_support.py` 参照）。自己批判で好感度が下がる
  のはその静かな一形態。

設計方針:
- **加点側には一切触れない**。抑制するのは好感度の**減点**だけで、しかも
  「自分・自分の状況について言っている」と明示的に判定できたときに限る。
  曖昧なもの（「つまらない」だけ等）は従来どおりの挙動を保つ。
- `classify_sentiment` 自体は変更しない。`user_wellbeing` はユーザーの気分を
  知るために負の極性をそのまま必要とするため（ここを弄ると A5 変化点検知が壊れる）。
- LLM・外部 API 非依存。マーカー語の有無だけを見る決定論的処理。

主な公開 API:
  is_directed_at_companion(text) -> bool
  is_self_or_situational(text) -> bool
  suppresses_affinity_penalty(text) -> bool
"""
from __future__ import annotations

import re as _re
import unicodedata as _ud
from typing import List, Pattern, Sequence


def _compile(patterns: Sequence[str]) -> List[Pattern[str]]:
    return [_re.compile(p) for p in patterns]


# --------------------------------------------------------------------------- #
# アバター（＝わたし）に向けられていることを示すマーカー。
# これがあれば向き先は明確なので、減点は従来どおり適用する。
# --------------------------------------------------------------------------- #
_COMPANION_MARKERS: List[Pattern[str]] = _compile([
    # ja: 二人称
    r"あなた", r"あんた", r"きみ", r"君(は|が|を|も|の|に|って|、)", r"お前", r"おまえ",
    r"てめ[えぇ]", r"貴様",
    # ja: 宛先が明らかな命令・拒絶（二人称が無くてもアバターに向いている）
    r"うるさい", r"うざい", r"黙れ", r"だまれ", r"消えろ", r"しつこい",
    r"話しかけないで", r"もう来ないで",
    # en: 二人称
    r"\byou\b", r"\byou'?re\b", r"\byour\b", r"\byours\b", r"\bu r\b",
    # en: 宛先が明らかな命令・拒絶
    r"\bshut\s+up\b", r"\bgo\s+away\b", r"\bleave\s+me\s+alone\b",
    r"\bstop\s+talking\b", r"\bannoying\b",
])

# --------------------------------------------------------------------------- #
# 自分自身について言っていることを示すマーカー。
# --------------------------------------------------------------------------- #
_SELF_MARKERS: List[Pattern[str]] = _compile([
    # ja
    r"自分", r"(私|わたし|僕|ぼく|俺|おれ|自分)(なんて|なんか|は|が|も|って)",
    r"じぶん",
    # en
    r"\bmyself\b", r"\bi\s*'?\s*m\b", r"\bi\s+am\b", r"\bi\s+feel\b",
    r"\bi\s+hate\s+me\b", r"\bmy\s+(life|fault|own)\b", r"\bi\s+(was|got|did|made)\b",
    r"\bi\s+can'?t\b", r"\bi'?ve\b",
])

# --------------------------------------------------------------------------- #
# 状況・出来事について言っていることを示すマーカー（愚痴）。
# --------------------------------------------------------------------------- #
_SITUATIONAL_MARKERS: List[Pattern[str]] = _compile([
    # ja
    r"今日", r"昨日", r"きょう", r"きのう", r"最近",
    r"仕事", r"会社", r"職場", r"上司", r"学校", r"授業", r"バイト", r"アルバイト",
    r"テスト", r"試験", r"就活", r"電車", r"満員", r"天気", r"家族", r"friends?",
    r"(だった|でした|しました|してしまった|しちゃった)$",
    # en
    r"\btoday\b", r"\byesterday\b", r"\blately\b", r"\bthis\s+week\b",
    r"\b(at|from)\s+work\b", r"\bmy\s+(job|boss|class|exam|team|day)\b",
    r"\bschool\b", r"\bthe\s+weather\b", r"\bcommute\b",
])


def _normalize(text: str) -> str:
    """比較用にテキストを正規化する（NFC + 小文字化 + 前後空白除去）。"""
    return _ud.normalize("NFC", str(text or "").strip().lower())


def is_directed_at_companion(text: str) -> bool:
    """発話がアバター自身に向けられていると読めるかを返す。

    二人称、または宛先が明らかな命令・拒絶（「黙れ」「shut up」）があれば True。
    """
    norm = _normalize(text)
    if not norm:
        return False
    return any(p.search(norm) for p in _COMPANION_MARKERS)


def is_self_or_situational(text: str) -> bool:
    """発話がユーザー自身、または自分の状況・出来事についてかを返す。"""
    norm = _normalize(text)
    if not norm:
        return False
    if any(p.search(norm) for p in _SELF_MARKERS):
        return True
    return any(p.search(norm) for p in _SITUATIONAL_MARKERS)


def suppresses_affinity_penalty(text: str) -> bool:
    """好感度の**減点**を抑制すべき発話かを返す。

    「自分・自分の状況について言っている」ことが明示的に読み取れ、かつ
    アバターに向けたマーカーが無いときだけ True。判断がつかない発話
    （「つまらない」だけ等）は False を返し、従来の挙動を保つ。

    加点側には一切関与しない（呼び出し側が delta < 0 のときだけ参照する）。
    """
    if not text or not str(text).strip():
        return False
    if is_directed_at_companion(text):
        return False
    return is_self_or_situational(text)
