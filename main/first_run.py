"""
初回起動オンボーディング — 「この子は何ができるのか」を最初に伝える。

第一原理から見た問題: 本製品の価値は「覚えていてくれる / 関係が育つコンパニオン」
だが、初回起動時にユーザーが目にするのは (a) 静止したアバター、(b)「自律モードON」
という内部用語のボタン、(c)「コメントを入力してEnterで読み上げ」というプレース
ホルダだけだった。この文言は**読み上げツール**を示唆しており、記憶・好感度・
スラッシュコマンドという製品の中核価値が初回接触時に一切見えない。結果として
「TTS のおもちゃ」と誤解されたまま離脱しうる。

そこで初回起動（＝まだ一度も交流していない）と判定できたときだけ、アバター自身の
台詞として「できること」を短く伝える。2 回目以降は一切出さない（既存ユーザーの
体験を邪魔しない）。LLM 非依存の定型文・決定論的。
"""
from __future__ import annotations

from typing import Optional


def _lang_key(lang: Optional[str]) -> str:
    """'en' で始まれば英語、それ以外は日本語。"""
    return "en" if str(lang or "ja").lower().startswith("en") else "ja"


_WELCOME = {
    "ja": (
        "はじめまして！わたしは あなたのことを少しずつ覚えていくコンパニオンだよ。\n"
        "・話しかけてくれたら返事するね（下の入力欄に書いて Enter）\n"
        "・「/callme さくら」で呼び名、「/like 音楽」で好きなものを覚えるよ\n"
        "・使えることの一覧は「/help」でどうぞ\n"
        "・「自律モードON」を押すと、わたしから話しかけたり動いたりするよ"
    ),
    "en": (
        "Nice to meet you! I'm a companion who gradually learns about you.\n"
        "- Say something and I'll reply (type below and press Enter)\n"
        "- \"/callme Sakura\" teaches me your name, \"/like music\" your interests\n"
        "- Type \"/help\" to see everything I can do\n"
        "- Press \"Autonomous ON\" and I'll move and talk on my own"
    ),
}


def is_first_run(interactions: Optional[int], has_profile_name: bool,
                 has_history: bool) -> bool:
    """初回起動（まだ一度も交流していない）かを判定する。

    3 つの独立した痕跡すべてが「無い」ときのみ True。どれか 1 つでも過去の利用を
    示していれば False（既存ユーザーに歓迎メッセージを再表示しない）。
    interactions が None（好感度が読めない）でも他の痕跡で判断できるよう
    0 と同様に扱う。
    """
    if has_profile_name or has_history:
        return False
    return not int(interactions or 0) > 0


def welcome_message(lang: str = "ja") -> str:
    """初回起動時に表示する歓迎＋できることの案内を返す。"""
    return _WELCOME[_lang_key(lang)]
