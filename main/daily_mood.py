"""
日替わりキャラクタームード（デイリームード）。

日付（+ オプションのソルト）から決定論的にアバターのその日の気質を導く。
同じ日に何度呼んでも同じ結果を返す（テスト・再現性に優しい）。
外部ライブラリ不要。
"""
from __future__ import annotations

import hashlib
from datetime import date as _date
from typing import Optional

# ── ムード定義 ────────────────────────────────────────────────────────────── #
# 順序がそのまま選択重みに相当（均等分布 → 各1/6）。
_MOODS = [
    {
        "key": "energetic",
        "ja": {"label": "活発", "desc": "今日はなんかはりきってる感じ！何でも聞いて！"},
        "en": {"label": "Energetic", "desc": "Feeling super energetic today! Ask me anything!"},
        "emoji": "⚡",
    },
    {
        "key": "cheerful",
        "ja": {"label": "陽気", "desc": "今日はなんか楽しい気分！いいことありそう！"},
        "en": {"label": "Cheerful", "desc": "Feeling bright and happy today! Something good might happen!"},
        "emoji": "☀️",
    },
    {
        "key": "calm",
        "ja": {"label": "穏やか", "desc": "今日は穏やかな気分かな。ゆったり話そう。"},
        "en": {"label": "Calm", "desc": "Feeling peaceful today. Let's take it easy."},
        "emoji": "🌙",
    },
    {
        "key": "thoughtful",
        "ja": {"label": "思慮深い", "desc": "今日はちょっと考えごとが多い日。深い話がしたい気分。"},
        "en": {"label": "Thoughtful", "desc": "A bit reflective today. I'm in the mood for deeper conversations."},
        "emoji": "💭",
    },
    {
        "key": "melancholy",
        "ja": {"label": "センチメンタル", "desc": "なんかしんみりした気分…。そっとしておいてくれると嬉しいかも。"},
        "en": {"label": "Melancholy", "desc": "Feeling a little wistful today… gentle company would be nice."},
        "emoji": "🌧️",
    },
    {
        "key": "mischievous",
        "ja": {"label": "いたずら", "desc": "今日はちょっとやんちゃな気分かも？ふふ。"},
        "en": {"label": "Mischievous", "desc": "Feeling a little mischievous today~ hehe."},
        "emoji": "😼",
    },
]

_KEY_INDEX = {m["key"]: i for i, m in enumerate(_MOODS)}

# デイリームードが好感度 delta に与える乗数。
# 明るい日は受け取り上手（1.2）、センチメンタルな日はちょっと反応しにくい（0.8）。
# neutral / default は 1.0。
_AFFINITY_MULTIPLIER: dict = {
    "energetic":   1.2,
    "cheerful":    1.2,
    "calm":        1.0,
    "thoughtful":  0.9,
    "melancholy":  0.8,
    "mischievous": 1.1,
}


def get_daily_mood(today: Optional[_date] = None, salt: str = "") -> str:
    """今日のムードキーを返す（同一日 + salt では常に同じ値）。

    Args:
        today: 基準日（None のとき date.today()）。
        salt:  ユーザー名など追加のシード（省略可）。

    Returns:
        ムードキー文字列 ("energetic" | "cheerful" | "calm" |
                         "thoughtful" | "melancholy" | "mischievous")。
    """
    if today is None:
        today = _date.today()
    seed = f"{today.isoformat()}:{salt or ''}".encode()
    digest = hashlib.sha256(seed).digest()
    return _MOODS[digest[0] % len(_MOODS)]["key"]


def mood_label(key: str, lang: str = "ja") -> str:
    """ムードキーの表示ラベルを返す（例: "活発"）。"""
    idx = _KEY_INDEX.get(key)
    if idx is None:
        return key
    lang_key = "en" if str(lang).lower().startswith("en") else "ja"
    return _MOODS[idx][lang_key]["label"]


def mood_description(key: str, lang: str = "ja") -> str:
    """ムードキーの一行説明文を返す（アバターが喋る形式）。"""
    idx = _KEY_INDEX.get(key)
    if idx is None:
        return ""
    lang_key = "en" if str(lang).lower().startswith("en") else "ja"
    return _MOODS[idx][lang_key]["desc"]


def mood_emoji(key: str) -> str:
    """ムードキーに対応する絵文字を返す。"""
    idx = _KEY_INDEX.get(key)
    if idx is None:
        return ""
    return _MOODS[idx]["emoji"]


def mood_affinity_multiplier(key: str) -> float:
    """ムードキーに対応する好感度 delta 乗数を返す（デフォルト 1.0）。

    MoodTracker.register() の結果にこの値を掛けることで、
    明るい日は好感度が上がりやすく、センチメンタルな日は反応が鈍くなる。
    """
    return _AFFINITY_MULTIPLIER.get(key, 1.0)


def all_mood_keys() -> list:
    """全ムードキーのリストを返す（テスト・列挙用）。"""
    return [m["key"] for m in _MOODS]
