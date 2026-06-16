"""
プレゼントシステム（恋愛ゲーム定番要素）。

ユーザーが /gift <アイテム名> でアバターにプレゼントを贈ると好感度が上昇し、
アバターがそれぞれのアイテムに合わせた感情的な反応を返す。
LLM 不要・標準ライブラリのみ。
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

# --------------------------------------------------------------------------- #
# カタログ定義
# --------------------------------------------------------------------------- #
# 各エントリ:
#   "affinity": 好感度ボーナス（float）
#   "ja": {"aliases": [...], "replies": [...]}  <- aliases: 日本語入力の別名リスト
#   "en": {"aliases": [...], "replies": [...]}  <- aliases: 英語入力の別名リスト
# --------------------------------------------------------------------------- #
_GIFTS: List[Dict] = [
    {
        "key": "flowers",
        "affinity": 5.0,
        "ja": {
            "aliases": ["花", "お花", "花束", "フラワー"],
            "replies": [
                "わあ、お花！ありがとう、すごく嬉しい！大事にするね。",
                "お花なんてもらったの初めてかも…ありがとう、大切にする！",
            ],
        },
        "en": {
            "aliases": ["flowers", "bouquet", "flower"],
            "replies": [
                "Flowers? For me? I'm so happy! I'll take good care of them.",
                "Oh wow, flowers! I don't think I've ever gotten flowers before… thank you!",
            ],
        },
    },
    {
        "key": "chocolate",
        "affinity": 4.0,
        "ja": {
            "aliases": ["チョコ", "チョコレート", "chocolate"],
            "replies": [
                "チョコ！甘いの大好き！ありがとう、一緒に食べよう？",
                "わあ、チョコレート！嬉しいな。大切に食べる。",
            ],
        },
        "en": {
            "aliases": ["chocolate", "chocolates", "choco"],
            "replies": [
                "Chocolate! I love sweets! Thank you — let's eat it together?",
                "Oh, chocolate! I'm so happy. I'll savor every piece.",
            ],
        },
    },
    {
        "key": "book",
        "affinity": 3.5,
        "ja": {
            "aliases": ["本", "ほん", "本書", "小説", "漫画", "マンガ"],
            "replies": [
                "本！どんな話か教えて？一緒に読みたい！",
                "わあ、ありがとう。あなたが選んでくれたものなら絶対楽しいはず。",
            ],
        },
        "en": {
            "aliases": ["book", "novel", "manga", "comic"],
            "replies": [
                "A book! What's it about? I want to read it together with you!",
                "Thank you so much — anything you chose for me must be great.",
            ],
        },
    },
    {
        "key": "music",
        "affinity": 4.0,
        "ja": {
            "aliases": ["音楽", "cd", "CD", "アルバム", "プレイリスト"],
            "replies": [
                "音楽！一緒に聴こう！どんな曲が入ってる？",
                "ありがとう！あなたのセンスが好きだから、楽しみ！",
            ],
        },
        "en": {
            "aliases": ["music", "cd", "album", "playlist", "song"],
            "replies": [
                "Music! Let's listen to it together! What songs are on it?",
                "Thank you! I love your taste, so I can't wait to hear it!",
            ],
        },
    },
    {
        "key": "cake",
        "affinity": 5.0,
        "ja": {
            "aliases": ["ケーキ", "cake", "スイーツ", "お菓子"],
            "replies": [
                "ケーキ！！大好きー！ありがとう！一緒に食べよう！",
                "わあ、ケーキだ！いい香り〜！すごく嬉しい！",
            ],
        },
        "en": {
            "aliases": ["cake", "sweets", "pastry", "dessert"],
            "replies": [
                "Cake!! I love it so much! Thank you! Let's eat it together!",
                "Oh, cake! It smells so good! I'm so happy!",
            ],
        },
    },
    {
        "key": "ribbon",
        "affinity": 3.0,
        "ja": {
            "aliases": ["リボン", "アクセサリー", "ヘアピン"],
            "replies": [
                "かわいい！ありがとう、大切にするね。似合うかな？",
                "リボン！わあ、私につけていいの？うれしい！",
            ],
        },
        "en": {
            "aliases": ["ribbon", "accessory", "hairpin", "hairclip"],
            "replies": [
                "How pretty! Thank you, I'll treasure it. Does it suit me?",
                "A ribbon! Oh, can I wear it? I'm so happy!",
            ],
        },
    },
    {
        "key": "letter",
        "affinity": 6.0,
        "ja": {
            "aliases": ["手紙", "てがみ", "レター", "letter", "メッセージ"],
            "replies": [
                "手紙…！ありがとう。大事に読むね。あなたの気持ちが嬉しくて。",
                "手書きの手紙なんて…すごく嬉しい。一生大切にする。",
            ],
        },
        "en": {
            "aliases": ["letter", "note", "message", "card"],
            "replies": [
                "A letter…! Thank you. I'll read it carefully. It means so much.",
                "A handwritten letter… I'm so touched. I'll treasure this forever.",
            ],
        },
    },
]

# フラットな別名→カタログエントリのマップ（小文字正規化済み）
_ALIAS_MAP_JA: Dict[str, int] = {}
_ALIAS_MAP_EN: Dict[str, int] = {}

for _idx, _gift in enumerate(_GIFTS):
    for _alias in _gift["ja"]["aliases"]:
        _ALIAS_MAP_JA[_alias.lower()] = _idx
    for _alias in _gift["en"]["aliases"]:
        _ALIAS_MAP_EN[_alias.lower()] = _idx


def _pick(options: List[str], key: str = "") -> str:
    """重複を避けながらリストから 1 件選ぶ（ステートレス: 単純にランダム）。"""
    import random
    return random.choice(options) if options else ""


def lookup_gift(item: str, lang: str = "ja") -> Optional[Tuple[float, str]]:
    """アイテム名から (好感度ボーナス, 反応テキスト) を返す。

    一致しなければ None。
    マッチングは小文字部分一致（「手紙」が含まれていれば OK）。

    Args:
        item: ユーザーが入力したアイテム名。
        lang: "ja" または "en"。
    """
    if not item:
        return None
    norm = item.strip().lower()
    lang_key = "en" if str(lang).lower().startswith("en") else "ja"
    alias_map = _ALIAS_MAP_EN if lang_key == "en" else _ALIAS_MAP_JA

    # 完全一致を優先、次に部分一致
    idx = alias_map.get(norm)
    if idx is None:
        for alias, i in alias_map.items():
            if alias in norm or norm in alias:
                idx = i
                break
    if idx is None:
        return None

    gift = _GIFTS[idx]
    affinity_bonus = float(gift["affinity"])
    replies = list(gift[lang_key]["replies"])
    reply = _pick(replies)
    return affinity_bonus, reply


def all_gift_keys() -> List[str]:
    """全ギフトキーのリストを返す（テスト・列挙用）。"""
    return [g["key"] for g in _GIFTS]


def gift_catalog_text(lang: str = "ja") -> str:
    """プレゼントカタログを表示用テキストとして返す。"""
    lang_key = "en" if str(lang).lower().startswith("en") else "ja"
    lines = []
    for g in _GIFTS:
        aliases = g[lang_key]["aliases"]
        bonus = int(g["affinity"])
        main = aliases[0]
        if lang_key == "en":
            lines.append(f"  {main} (+{bonus})")
        else:
            lines.append(f"  {main} (+{bonus})")
    return "\n".join(lines)
