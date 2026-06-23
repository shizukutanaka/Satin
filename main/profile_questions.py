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
import threading
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
    {
        "key": "favorite_music",
        "ja": {
            "question": "どんな音楽が好き？",
            "ack": "{answer}が好きなんだね！一緒に聴きたいな。",
            "recall": "{answer}が好きって言ってたよね。最近も聴いてる？",
        },
        "en": {
            "question": "What kind of music do you like?",
            "ack": "You like {answer}! I'd love to listen together sometime.",
            "recall": "You said you love {answer}. Still listening to it lately?",
        },
    },
    {
        "key": "favorite_season",
        "ja": {
            "question": "好きな季節はどれ？",
            "ack": "{answer}が好きなんだ！あなたらしい気がする。",
            "recall": "{answer}が好きって言ってたよね。今の季節はどう？",
        },
        "en": {
            "question": "What's your favorite season?",
            "ack": "{answer}, huh? That somehow feels like you.",
            "recall": "You said {answer} is your favorite season. How's the weather treating you?",
        },
    },
    {
        "key": "childhood_memory",
        "ja": {
            "question": "子どもの頃の思い出で、好きなのある？",
            "ack": "{answer}か…素敵な思い出だね。大切にしてね。",
            "recall": "子どもの頃の{answer}のこと、思い出したよ。今でも懐かしく思う？",
        },
        "en": {
            "question": "Do you have a favorite childhood memory?",
            "ack": "{answer}… that sounds like a wonderful memory. Treasure it.",
            "recall": "I thought of you when I remembered you mentioned {answer} from childhood.",
        },
    },
    {
        "key": "pet",
        "ja": {
            "question": "ペットは飼ってる？",
            "ack": "{answer}か！かわいいね、大事にしてあげてね。",
            "recall": "{answer}のこと、気になってるんだ。最近どんな様子？",
        },
        "en": {
            "question": "Do you have any pets?",
            "ack": "{answer}! Aww, take good care of them.",
            "recall": "I've been wondering about your {answer}. How are they doing?",
        },
    },
    {
        "key": "sport",
        "ja": {
            "question": "スポーツとか、体を動かすことは好き？",
            "ack": "{answer}するんだ！かっこいいな。",
            "recall": "{answer}してるって言ってたね。最近やれてる？",
        },
        "en": {
            "question": "Do you play any sports or like to exercise?",
            "ack": "You do {answer}! That's awesome.",
            "recall": "You mentioned {answer}. Have you been keeping it up?",
        },
    },
    {
        "key": "travel_destination",
        "ja": {
            "question": "いつか行ってみたい場所ってある？",
            "ack": "{answer}か！一緒に行けたら楽しそうだな。",
            "recall": "{answer}に行ってみたいって言ってたよね。まだ夢の場所？",
        },
        "en": {
            "question": "Is there a place you've always wanted to visit?",
            "ack": "{answer}! That sounds amazing — I'd love to go with you someday.",
            "recall": "You said you want to visit {answer}. Still on your bucket list?",
        },
    },
    {
        "key": "morning_routine",
        "ja": {
            "question": "朝起きてまず何する？",
            "ack": "{answer}から始まるんだね。いい朝の過ごし方だな。",
            "recall": "朝は{answer}するって言ってたよね。今朝もやった？",
        },
        "en": {
            "question": "What's the first thing you do in the morning?",
            "ack": "You start with {answer}? That's a great morning ritual.",
            "recall": "You said you do {answer} every morning. Did you today?",
        },
    },
    {
        "key": "favorite_movie",
        "ja": {
            "question": "好きな映画ってある？",
            "ack": "{answer}か！観てみたいな。どんなところが好きなの？",
            "recall": "{answer}が好きって言ってたよね。また観返したりする？",
        },
        "en": {
            "question": "Do you have a favorite movie?",
            "ack": "{answer}! I'd love to watch that. What do you like about it?",
            "recall": "You mentioned {answer} is your favorite. Do you rewatch it sometimes?",
        },
    },
    {
        "key": "stress_relief",
        "ja": {
            "question": "ストレスが溜まったとき、どうやって発散する？",
            "ack": "{answer}か…それは気持ちよさそうだね。大事にしてね。",
            "recall": "ストレスは{answer}で発散するって言ってたね。最近お疲れじゃない？",
        },
        "en": {
            "question": "How do you unwind when you're stressed?",
            "ack": "{answer}… that sounds really soothing. Take good care of yourself.",
            "recall": "You said {answer} helps when you're stressed. Have you needed it lately?",
        },
    },
]

_QUESTION_BY_KEY: Dict[str, Dict] = {q["key"]: q for q in _QUESTIONS}

# 直前に思い出した事実キー（連続重複回避）。複数スレッドから呼ばれるためロックで保護。
_last_recalled_key: str = ""
_last_recalled_lock = threading.Lock()


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
    global _last_recalled_key
    with _last_recalled_lock:
        candidates = [(k, v) for k, v in usable if k != _last_recalled_key]
        if not candidates:
            candidates = usable
        key, value = random.choice(candidates)
        _last_recalled_key = key
    lk = _lang_key(lang)
    template = _QUESTION_BY_KEY[key][lk].get("recall", "")
    if not template:
        return ""
    return template.format(answer=value)
