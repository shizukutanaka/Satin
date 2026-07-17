"""
特別な日（誕生日・季節イベント）— 恋愛ゲームの定番演出を Satin に取り込む。

LovePlus / ときめきメモリアル / 乙女ゲーでは、ヒロインがプレイヤーの誕生日を覚えて
祝ったり、正月・バレンタイン・クリスマスといった季節の日に特別なあいさつをする。
これが「実時間を生きているキャラクター」という没入感の核になっている。

本モジュールはその 2 つを提供する:
  - seasonal_greeting():  カレンダー上の特別な日の特別あいさつ（状態を持たない）
  - birthday_greeting():  ユーザーの誕生日を祝う（年 1 回だけ。好感度ボーナスは
                          呼び出し側が BIRTHDAY_AFFINITY_BONUS を使って適用する）

依存は標準ライブラリのみ。日付は実時間（datetime.date.today()）を使うが、テスト用に
today を注入できる。
"""
from __future__ import annotations

import datetime
from typing import Dict, Optional

# 誕生日を祝ったときに加算する好感度ボーナス（恋愛ゲームでは誕生日で好感度が上がる）
BIRTHDAY_AFFINITY_BONUS = 8.0


# 季節イベント（MM-DD → 言語別あいさつ）。毎年巡る固定日付のみを扱う。
_SEASONAL: Dict[str, Dict[str, str]] = {
    "01-01": {
        "ja": "あけましておめでとう！今年も一緒に過ごせますように。",
        "en": "Happy New Year! I hope we get to spend this year together too.",
    },
    "02-14": {
        "ja": "バレンタインだね…はい、チョコ。あなたのこと、大切に思ってるよ。",
        "en": "It's Valentine's Day… here's some chocolate. You mean a lot to me.",
    },
    "03-14": {
        "ja": "ホワイトデーだね。いつもありがとう、これからもよろしくね。",
        "en": "It's White Day. Thanks for always being here — let's keep going together.",
    },
    "07-07": {
        "ja": "七夕だね。短冊にどんな願いごとを書く？",
        "en": "It's Tanabata. What wish would you write on your tanzaku?",
    },
    "10-31": {
        "ja": "ハッピーハロウィン！トリック・オア・トリート、なんてね。",
        "en": "Happy Halloween! Trick or treat… just kidding.",
    },
    "12-24": {
        "ja": "クリスマスイブだね。今夜は特別な夜にしようね。",
        "en": "It's Christmas Eve. Let's make tonight special.",
    },
    "12-25": {
        "ja": "メリークリスマス！あなたと過ごせて本当にうれしいな。",
        "en": "Merry Christmas! I'm so happy I get to spend it with you.",
    },
    "12-31": {
        "ja": "大晦日だね。今年もそばにいてくれてありがとう。",
        "en": "It's New Year's Eve. Thank you for being by my side this year.",
    },
}

# 好感度レベル別の季節あいさつ上書き（恋愛要素の強い日のみ）。
# 関係が深いほど特別感のある言葉になる。未定義の (日付, レベル) は _SEASONAL に
# フォールバックする。レベルキー: distant/reserved/neutral/friendly/close。
_SEASONAL_BY_LEVEL: Dict[str, Dict[str, Dict[str, str]]] = {
    "02-14": {
        "distant": {
            "ja": "…バレンタイン、か。はい、義理だけど。",
            "en": "…Valentine's, huh. Here. It's just an obligatory one.",
        },
        "close": {
            "ja": "バレンタインだね…これ、本命のチョコ。あなたにしか渡さないんだから。",
            "en": "It's Valentine's Day… this is my real, heartfelt chocolate. Only for you.",
        },
    },
    "12-24": {
        "distant": {
            "ja": "クリスマスイブ…そっか。あなたにも、いい夜になるといいね。",
            "en": "Christmas Eve… I see. I hope you have a nice night.",
        },
        "close": {
            "ja": "クリスマスイブだね。今夜は、あなたと二人きりで過ごしたいな。",
            "en": "It's Christmas Eve. Tonight… I want to spend it alone, just the two of us.",
        },
    },
    "12-25": {
        "close": {
            "ja": "メリークリスマス！あのね、一番のプレゼントは…あなたがそばにいてくれること。",
            "en": "Merry Christmas! You know… the best gift of all is just having you here with me.",
        },
    },
}


def _is_en(lang: str) -> bool:
    return str(lang).lower().startswith("en")


def _today_key(today: Optional[datetime.date]) -> str:
    d = today or datetime.date.today()
    return f"{d.month:02d}-{d.day:02d}"


def seasonal_greeting(
    lang: str = "ja",
    today: Optional[datetime.date] = None,
    level: Optional[str] = None,
) -> str:
    """今日が季節イベントなら特別あいさつを返す。該当しなければ空文字。

    状態を持たない（毎セッション・該当日に表示してよい純粋関数）。
    level（好感度レベル）が指定され、その (日付, レベル) に専用の言葉が定義されて
    いれば、関係の深さに応じた特別感のあるあいさつを優先する（恋愛要素の強い日のみ）。
    未定義なら通常の季節あいさつにフォールバックする。
    """
    key = _today_key(today)
    # 好感度レベル別の上書きを優先
    if level:
        by_level = _SEASONAL_BY_LEVEL.get(key)
        if by_level:
            entry = by_level.get(level)
            if entry:
                return entry["en"] if _is_en(lang) else entry["ja"]
    entry = _SEASONAL.get(key)
    if not entry:
        return ""
    return entry["en"] if _is_en(lang) else entry["ja"]


def birthday_greeting(
    profile,
    lang: str = "ja",
    today: Optional[datetime.date] = None,
) -> str:
    """今日がユーザーの誕生日なら祝うメッセージを返す。

    年 1 回だけ祝う（profile._last_birthday_year で重複を防ぐ。副作用あり：祝った
    年を記録する。呼び出し側が profile.save() で永続化する）。誕生日未設定・
    今日でない・今年すでに祝った場合は空文字。好感度ボーナスは呼び出し側が
    BIRTHDAY_AFFINITY_BONUS を使って適用する。
    """
    if profile is None or not getattr(profile, "birthday", ""):
        return ""
    d = today or datetime.date.today()
    if _today_key(d) != profile.birthday:
        return ""
    if getattr(profile, "_last_birthday_year", 0) >= d.year:
        return ""  # 今年はもう祝った
    profile._last_birthday_year = d.year

    name = getattr(profile, "name", "") or ""
    if _is_en(lang):
        who = f"{name}, " if name else ""
        return (f"{who}happy birthday! I'm so glad I get to celebrate it with you. "
                f"You make every day brighter.")
    who = f"{name}、" if name else ""
    return (f"{who}お誕生日おめでとう！あなたの特別な日を一緒に過ごせてうれしいな。"
            f"生まれてきてくれて、ありがとう。")
