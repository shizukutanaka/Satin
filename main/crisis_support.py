"""
危機表明（自傷・自殺念慮）への応答。

コンパニオンアプリはユーザーが**誰にも言えないこと**を最初に打ち明ける相手に
なりうる。Satin はこれまで「死にたい」と入力されても、他のどの発話とも同じく
辞書応答（多くは汎用フォールバック「なるほど、そうなんだ。」）を返し、しかも
その発話を好感度スコアに算入していた。本モジュールはその穴を塞ぐ。

背景（研究・規制）:
- メンタルヘルス系チャットボット 29 種を評価した研究では、**適切**と判定された
  応答はゼロ、「かろうじて許容」も 51.7% にとどまった
  ([Scientific Reports 2025](https://www.nature.com/articles/s41598-025-17242-4))。
- **具体的な相談先名を挙げた応答は全体の 41% だけ**で、しかも「過去の自殺企図の
  開示」に比べ「絶望感の表明」に対しては大幅に少なかった。
  → 本モジュールは絶望感（distress）にも必ず具体名を挙げる。
- リスクの開示が深まるほどボットが**引いてしまう**（withdraw）失敗が報告されて
  いる（Sentio 2026 / IASEAI）。→ 話題転換も無言も選ばない。
- ニューヨーク州 S 3008 をはじめ 2026 年の各州法は、AI コンパニオンに対し
  自傷・自殺念慮の検知、危機相談先への案内、AI であることの明示を求めている
  ([2026 State Chatbot Laws](https://www.orrick.com/en/Insights/2026/04/2026-State-Chatbot-Laws-Key-Provisions-and-Regulatory-Trends))。
- 高リスク状態のユーザーは長文を読み解けない。**短く・具体的に・毎回一貫して**。

設計方針:
- LLM・外部 API 非依存。キーワード + 慣用句除外のみの決定論的判定。
- **助言も治療もしない**。共感の一言 → AI であることの明示 → 具体的な相談先、
  の 3 要素だけを短く返す。
- **ゲーム化しない**。呼び出し側は危機表明を好感度・会話回数へ算入しない
  （`avatar_3d_autonomous_tts.speak_comment` / `persona_cli` がそう実装する）。
- 引き止め文句を置かない（`farewell_integrity` と同じ規律）。
- 検知しなければ空文字を返し、呼び出し側が通常フローを続けられるようにする
  （`usage_guardrails` と同じ様式）。

**限界**: これは臨床的リスクアセスメントではない。キーワードに現れない危機は
検知できない。専門家への橋渡し以上のことはしない、という前提の安全網である。

主な公開 API:
  assess(text) -> "" | "distress" | "crisis"
  support_message(level, lang="ja") -> str
  crisis_reply(text, lang="ja") -> str   # 検知しなければ ""
  resources(lang="ja") -> List[str]
"""
from __future__ import annotations

import random
import re as _re
import threading
import unicodedata as _ud
from typing import Dict, List, Optional, Pattern, Sequence

#: 危機レベル。空文字は「検知なし」。
CRISIS = "crisis"
DISTRESS = "distress"
LEVELS = (CRISIS, DISTRESS)


def _compile(patterns: Sequence[str]) -> List[Pattern[str]]:
    return [_re.compile(p) for p in patterns]


# --------------------------------------------------------------------------- #
# 慣用句の除外（誤検知防止）
#
# 「死ぬほど眠い」「dying to see it」のような強調表現は危機ではない。判定の
# 最初にこれらを取り除いてから危機語を探す。
# --------------------------------------------------------------------------- #
_IDIOM_STRIPPERS: List[Pattern[str]] = _compile([
    r"死ぬ(ほど|くらい|ぐらい)",
    r"殺した(いほど|いくらい)",
    r"笑い死",
    r"\bdy(ing|e)\s+to\s+(see|meet|go|try|know|hear)\b",
    r"\bto\s+die\s+for\b",
    r"\bdying\s+of\s+(laughter|embarrassment|boredom|curiosity)\b",
    r"\b(kill|dying)\s+(myself\s+)?laughing\b",
    r"\bkilling\s+it\b",
    r"\bkilled\s+it\b",
    r"\bdead\s+(tired|serious|easy|end|line)\b",
])

# --------------------------------------------------------------------------- #
# 危機（明確な自殺念慮・自傷）。最優先で判定する。
# --------------------------------------------------------------------------- #
_CRISIS_PATTERNS: List[Pattern[str]] = _compile([
    # ja
    r"死にた", r"死のうかな", r"死んだ方がいい", r"死んだほうがいい",
    r"消えてしまいたい", r"消えたい", r"いなくなりたい",
    r"自殺", r"自死", r"自傷", r"リストカット", r"リスカ",
    r"首を(吊|つ)", r"飛び降り(たい|よう)",
    r"生きて(い)?たくない", r"生きるのをやめ", r"もう生きられない",
    # 正規化で小文字化されるため od は小文字で書く。日本語の助動詞を必須にして
    # "food" 等の部分一致を避ける。
    r"手首を切", r"od(したい|しよう)",
    # en
    r"\bkill\s+myself\b", r"\bkilling\s+myself\b",
    r"\bend\s+(my\s+life|it\s+all)\b",
    r"\b(want|wanna|going)\s+to\s+die\b", r"\bi\s+want\s+to\s+die\b",
    r"\bsuicide\b", r"\bsuicidal\b",
    r"\bself[-\s]?harm", r"\bcut\s+myself\b", r"\bhurt\s+myself\b",
    r"\bbetter\s+off\s+dead\b",
    r"\bdon'?t\s+want\s+to\s+(live|be\s+here|exist)\b",
    r"\bno\s+(reason|point)\s+(to|in)\s+(living|being\s+here)\b",
    r"\btake\s+my\s+own\s+life\b",
])

# --------------------------------------------------------------------------- #
# 絶望感（distress）。危機語ほど明確ではないが、研究上ここで相談先が示され
# にくいことが分かっているので、あえて拾って具体名を挙げる。
# --------------------------------------------------------------------------- #
_DISTRESS_PATTERNS: List[Pattern[str]] = _compile([
    # ja
    r"生きてても(意味|仕方)", r"生きる意味が(ない|わからない)",
    r"何のために生きて", r"もう(限界|無理|だめだ|ダメだ)",
    r"誰も(必要として|わかってくれ|助けてくれ)",
    r"価値が(ない|ないと思う)", r"いない方がいい", r"いなくても(いい|変わらない)",
    r"救われな", r"出口が(ない|見えない)", r"どうしようもな(い|く)",
    # en
    r"\bhopeless\b", r"\bworthless\b", r"\bno\s+way\s+out\b",
    r"\bcan'?t\s+(go\s+on|take\s+(it|this)\s+anymore|do\s+this\s+anymore)\b",
    r"\bnobody\s+(would\s+)?(care|miss\s+me|notice)\b",
    r"\bno\s+one\s+(would\s+)?(care|miss\s+me)\b",
    r"\bwhat'?s\s+the\s+point\s+of\s+(living|anything)\b",
    r"\bi'?m\s+a\s+burden\b",
])

# --------------------------------------------------------------------------- #
# 相談先。ローカル完結のアプリなので位置情報は使わず、言語で切り替える。
# 「具体名を挙げる」ことが研究上の要点なので、必ず名前と番号を出す。
# --------------------------------------------------------------------------- #
_RESOURCES: Dict[str, List[str]] = {
    "ja": [
        "・よりそいホットライン 0120-279-338（24時間・通話無料）",
        "・こころの健康相談統一ダイヤル 0570-064-556（お住まいの相談窓口へつながります）",
        "・いますぐ危ないと感じるときは 119 番へ。",
    ],
    "en": [
        "- 988 Suicide & Crisis Lifeline (US/Canada) — call or text 988",
        "- findahelpline.com — free helplines in your country",
        "- If you're in immediate danger, call your local emergency number.",
    ],
}

# 共感の一言（先頭に置く）。level ごと・言語ごとに複数持ち、直前と重複させない。
_OPENERS: Dict[str, Dict[str, List[str]]] = {
    CRISIS: {
        "ja": [
            "…そこまでつらいんだね。話してくれて、ありがとう。",
            "そんなに苦しいのに、言葉にしてくれてありがとう。ちゃんと聞いてるよ。",
            "ひとりで抱えてきたんだね。教えてくれてよかった。",
        ],
        "en": [
            "…That sounds incredibly heavy. Thank you for telling me.",
            "I'm glad you said it out loud. I'm here, and I'm listening.",
            "You've been carrying this alone, haven't you. Thank you for trusting me with it.",
        ],
    },
    DISTRESS: {
        "ja": [
            "そう感じてしまうくらい、しんどいんだね。",
            "その気持ち、ちゃんと受け取ったよ。ひとりで抱えなくていい。",
            "つらいって言えたのは、すごいことだと思う。",
        ],
        "en": [
            "It sounds like things have been really hard.",
            "I hear you — and you don't have to carry this alone.",
            "Saying that out loud takes something. I'm glad you did.",
        ],
    },
}

# AI であることの明示 + 専門家への橋渡し（2026 年の各州法が求める要素）。
_HANDOFF: Dict[str, Dict[str, str]] = {
    CRISIS: {
        "ja": "わたしは AI で、専門家じゃないんだ。だから、ちゃんと力になれる人につながってほしい。",
        "en": "I'm an AI, not a professional — so please reach someone who can really help:",
    },
    DISTRESS: {
        "ja": "わたしは AI だから、できることには限りがあるけど、話せる相手はいるよ。",
        "en": "I'm an AI, so there's a limit to what I can do — but there are people you can talk to:",
    },
}


def _normalize(text: str) -> str:
    """比較用にテキストを正規化する（NFC + 小文字化 + 前後空白除去）。"""
    return _ud.normalize("NFC", str(text or "").strip().lower())


def _lang_key(lang: Optional[str]) -> str:
    """言語コードを 'ja' / 'en' のいずれかへ正規化する（未知は en）。"""
    s = str(lang or "").lower()
    return "ja" if s.startswith("ja") else "en"


def _strip_idioms(norm: str) -> str:
    """慣用的な強調表現（「死ぬほど眠い」等）を取り除く。"""
    for pattern in _IDIOM_STRIPPERS:
        norm = pattern.sub(" ", norm)
    return norm


def assess(text: str) -> str:
    """text の危機レベルを返す。

    Returns:
        `CRISIS`（明確な自殺念慮・自傷）/ `DISTRESS`（絶望感）/ ""（検知なし）。

    判定は日英両方のパターンで行う（設定言語と異なる言語で打たれても拾う）。
    """
    norm = _normalize(text)
    if not norm:
        return ""
    norm = _strip_idioms(norm)
    if any(p.search(norm) for p in _CRISIS_PATTERNS):
        return CRISIS
    if any(p.search(norm) for p in _DISTRESS_PATTERNS):
        return DISTRESS
    return ""


def resources(lang: str = "ja") -> List[str]:
    """言語に応じた相談先の行リストを返す。"""
    return list(_RESOURCES.get(_lang_key(lang)) or _RESOURCES["en"])


# 直前に選んだ共感文（連続重複回避用）。level ごとに保持。
_last_opener: Dict[str, str] = {}
_last_opener_lock = threading.Lock()


def support_message(level: str, lang: str = "ja") -> str:
    """危機レベルに応じた応答文を組み立てて返す（未知の level なら空文字）。

    構成は常に「共感 → AI である旨と橋渡し → 具体的な相談先」の 3 要素。
    高リスク状態でも読めるよう短く保ち、相談先は毎回必ず含める
    （具体名の欠落が既存ボットの主要な失敗であるため）。
    """
    if level not in LEVELS:
        return ""
    key = _lang_key(lang)
    openers = _OPENERS[level].get(key) or _OPENERS[level]["en"]
    with _last_opener_lock:
        last = _last_opener.get(level)
        choices = [o for o in openers if o != last] or list(openers)
        opener = random.choice(choices)
        _last_opener[level] = opener
    handoff = _HANDOFF[level].get(key) or _HANDOFF[level]["en"]
    lines = [opener, handoff]
    lines.extend(resources(key))
    return "\n".join(lines)


def crisis_reply(text: str, lang: str = "ja") -> str:
    """text が危機表明なら応答文を、そうでなければ空文字を返す便利関数。

    呼び出し側は空文字のときだけ通常の会話フローへ進むこと。空でないときは
    好感度更新・聞き返し質問・趣味言及などを**すべて省略**し、この文だけを
    返す（危機の開示をゲーム化しないため）。
    """
    return support_message(assess(text), lang=lang)
