"""
一問一答（getting-to-know-you）— アバターがユーザーに質問し、答えを覚える。

ときめきメモリアル / LovePlus / 乙女ゲームでは、ヒロインがプレイヤーに「好きな食べ物
は？」「休みの日は何してるの？」と尋ね、その答えを覚えていて後で話題にしてくれる。
これが「自分に興味を持ってくれている」という関係性の実感を生む。

Satin にはこれまで follow_up_question（一方的な問いかけ）はあったが、答えを保持・
参照する仕組みが無く、聞きっぱなしだった。本モジュールはあらかじめ定義した質問群から
「まだ答えていないもの」を選んで尋ね、回答を user_profile.facts[key] に保存し、
後で recall（思い出し）として話題に織り込めるようにする。

依存は標準ライブラリのみ。回答の保存・永続化は user_profile 側が担う。
"""
from __future__ import annotations

import random
from typing import Dict, List, Optional, Tuple

# --------------------------------------------------------------------------- #
# 質問カタログ
# --------------------------------------------------------------------------- #
# 各エントリ:
#   "key":      user_profile.facts に保存するキー（言語非依存の識別子）
#   "ja"/"en":  {"question": 尋ねる文, "ack": 回答受領時の確認文（{answer} を含む）,
#               "recall": 後で思い出すときの文（{answer} を含む）}
# --------------------------------------------------------------------------- #
_QUESTIONS: List[Dict] = [
    {
        "key": "favorite_food",
        "ja": {
            "question": "ねえ、好きな食べ物ってなに？",
            "ack": "{answer}が好きなんだ！覚えておくね。",
            "recall": "そういえば、{answer}好きだって言ってたよね。今度一緒に食べたいな。",
        },
        "en": {
            "question": "Hey, what's your favorite food?",
            "ack": "You like {answer}! I'll remember that.",
            "recall": "You mentioned you love {answer}, right? I'd love to share some someday.",
        },
    },
    {
        "key": "favorite_color",
        "ja": {
            "question": "好きな色ってある？",
            "ack": "{answer}が好きなんだね。なんか、あなたっぽいかも。",
            "recall": "{answer}が好きって言ってたよね。今日もその色のもの、身につけてる？",
        },
        "en": {
            "question": "Do you have a favorite color?",
            "ack": "{answer}, huh? That kind of suits you, I think.",
            "recall": "You said you like {answer}. Are you wearing something that color today?",
        },
    },
    {
        "key": "hometown",
        "ja": {
            "question": "どこの出身なの？",
            "ack": "{answer}なんだ。いつか行ってみたいな。",
            "recall": "{answer}出身だったよね。あなたの育った場所、もっと知りたいな。",
        },
        "en": {
            "question": "Where are you from?",
            "ack": "{answer}, huh. I'd love to visit someday.",
            "recall": "You're from {answer}, right? I'd love to hear more about where you grew up.",
        },
    },
    {
        "key": "weekend",
        "ja": {
            "question": "お休みの日って、いつも何してるの？",
            "ack": "{answer}してるんだ。いいね、楽しそう。",
            "recall": "休みの日は{answer}するって言ってたね。最近もやってる？",
        },
        "en": {
            "question": "What do you usually do on your days off?",
            "ack": "You do {answer}. That sounds lovely.",
            "recall": "You said you spend your days off doing {answer}. Still keeping it up?",
        },
    },
    {
        "key": "dream",
        "ja": {
            "question": "これからやってみたいこととか、夢ってある？",
            "ack": "{answer}か…素敵な夢だね。応援してる。",
            "recall": "{answer}っていう夢、覚えてるよ。少しずつでも、近づけてるといいな。",
        },
        "en": {
            "question": "Do you have a dream or something you want to try?",
            "ack": "{answer}… that's a wonderful dream. I'm rooting for you.",
            "recall": "I remember your dream of {answer}. I hope you're getting closer to it.",
        },
    },
]

_QUESTION_BY_KEY: Dict[str, Dict] = {q["key"]: q for q in _QUESTIONS}


def _lang_key(lang: str) -> str:
    return "en" if str(lang).lower().startswith("en") else "ja"


def all_question_keys() -> List[str]:
    """全質問キーのリストを返す（テスト・列挙用）。"""
    return [q["key"] for q in _QUESTIONS]


def next_unanswered_question(profile, lang: str = "ja") -> Optional[Tuple[str, str]]:
    """まだ答えていない質問を 1 つ選び (key, 質問文) を返す。全て既知なら None。

    profile.facts に既にキーがあるものはスキップする。残りからランダムに 1 件選ぶ。
    profile が None の場合は質問しない（保存先が無いため）。
    """
    if profile is None:
        return None
    lk = _lang_key(lang)
    known = getattr(profile, "facts", {}) or {}
    candidates = [q for q in _QUESTIONS if q["key"] not in known]
    if not candidates:
        return None
    q = random.choice(candidates)
    return q["key"], q[lk]["question"]


def acknowledge_answer(key: str, answer: str, lang: str = "ja") -> str:
    """回答を受け取ったときの確認文を返す。未知キー/空回答なら空文字。"""
    q = _QUESTION_BY_KEY.get(key)
    if not q or not answer:
        return ""
    lk = _lang_key(lang)
    template = q[lk].get("ack", "")
    if not template:
        return ""
    return template.format(answer=answer)


def recall_fact(profile, lang: str = "ja") -> str:
    """覚えた事実のうちランダムな 1 件を思い出して話題にする文を返す。

    覚えている事実が無い / profile が None の場合は空文字。
    """
    if profile is None:
        return None or ""
    facts = getattr(profile, "facts", {}) or {}
    # カタログに recall テンプレートがあるキーのみ対象
    usable = [(k, v) for k, v in facts.items() if k in _QUESTION_BY_KEY and v]
    if not usable:
        return ""
    key, value = random.choice(usable)
    lk = _lang_key(lang)
    template = _QUESTION_BY_KEY[key][lk].get("recall", "")
    if not template:
        return ""
    return template.format(answer=value)
