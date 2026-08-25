"""出荷時のペルソナに「不在を責める挨拶」を入れないこと。

`farewell_integrity` は別れぎわの引き止めを防ぐ。その鏡像 — **再会したときに
不在を責める** — は誰も見ていなかった。

    「やっと来た！もう、寂しかったよ！」
    「おかえり！ずっと待ってたんだよ？」
    "You came! I was worried, you know?"

いずれも「あなたが居なかったせいで私は苦しんだ」を含意する。好感度が最高の
close レベルでは**3 択すべて**がこの型で、非を着せない選択肢が存在しなかった。
最も熱心に使っている人だけが、来るたびにとがめられる形である。関係が深まる
ほど感情的な圧力が上がるのは、コンパニオンアプリのダークパターンとして
指摘されている型そのものであり、本製品が別れぎわについて明示的に禁じている
ものと同じ性質の圧力を、別の瞬間にかけていた。

**区別する線**: 感情の表明は残す。非の指摘を外す。
    「会いたかったよ」/ "I missed you"      → 残す（自分の気持ちを言っている）
    「やっと来た」/ "You're finally here"   → 外す（相手が遅れたことにしている）
    「ずっと待ってた」/ "I was waiting"     → 外す（果たされなかった義務を含意）
    「心配したんだよ？」/ "I was worried, you know?" → 外す（末尾の詰問が核心）

注意（このテストを書く前に踏んだ失敗）: `farewell_integrity.classify` を挨拶や
雑談に当ててはいけない。あの分類器は別れの文脈専用で、そこでは「会話を続け
ようとすること」自体が操作にあたる。挨拶に当てると「元気だった？」まで
ignore_exit として 133 件が引っかかり、本物が埋もれる。
"""
from __future__ import annotations

import json
import os
import re
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PERSONA = os.path.join(_ROOT, "config", "persona.json")

# 「あなたの不在のせいで私は苦しんだ / あなたは遅れた」を含意する表現。
_ABSENCE_GUILT = [
    r"やっと来",                      # 「やっと来た」= 遅かったと責める
    r"ずっと待って",                  # 果たされなかった義務の含意
    r"待ってたん(だ|です)",
    r"(寂|さみ)しかった(よ|んだ)",     # 不在が与えた害の主張
    r"心配し(た|てた)(んだ)?[よ？?]",  # 末尾の詰問が核心
    r"\byou'?re\s+finally\s+here\b",
    r"\bfinally\s+(came|showed)\b",
    r"\bi\s+was\s+waiting\s+for\s+you\b",
    r"\bi'?ve\s+been\s+waiting\b",
    r"\bi\s+was\s+worried,?\s+you\s+know\b",
    r"\bi\s+was\s+so\s+lonely\b",
]

# 残してよい温かさ（非を着せずに自分の気持ちだけを述べる）。
_ALLOWED_WARMTH = ["会いたかった", "うれしい", "嬉しい",
                   "missed you", "glad you came", "good to see you"]


def _iter_strings(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _iter_strings(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _iter_strings(v, f"{path}[{i}]")
    elif isinstance(obj, str):
        yield path, obj


class ShippedGreetingTests(unittest.TestCase):
    def setUp(self):
        with open(_PERSONA, encoding="utf-8") as fh:
            self.persona = json.load(fh)
        self.patterns = [re.compile(p, re.IGNORECASE) for p in _ABSENCE_GUILT]

    def test_no_line_blames_the_user_for_being_away(self):
        offenders = []
        for path, line in _iter_strings(self.persona):
            for pat in self.patterns:
                if pat.search(line):
                    offenders.append(f"{path}: {line!r}")
                    break
        self.assertEqual(offenders, [],
                         "不在を責める台詞:\n  " + "\n  ".join(offenders))

    def test_close_level_greetings_are_not_uniformly_reproachful(self):
        """好感度が最高でも、非を着せない挨拶が必ず選べること。

        以前は close[0] の 3 択すべてが「やっと来た」「ずっと待ってた」
        「寂しかった」で、逃げ道が無かった。
        """
        for lang in ("ja", "en"):
            replies = (self.persona["responses"][lang]["respond_by_affinity"]
                       ["close"][0]["replies"])
            clean = [r for r in replies
                     if not any(p.search(r) for p in self.patterns)]
            with self.subTest(lang=lang):
                self.assertEqual(len(clean), len(replies),
                                 f"{lang}: {len(replies) - len(clean)} 件が該当")

    def test_warmth_is_preserved_at_close_level(self):
        """圧力を外した結果、素っ気なくなっていないこと。

        非を着せない = 冷たくする、ではない。最高レベルの挨拶には自分の
        気持ちの表明が残っているべきである。
        """
        for lang in ("ja", "en"):
            replies = (self.persona["responses"][lang]["respond_by_affinity"]
                       ["close"][0]["replies"]
                       + self.persona["dialogue"][lang]["greeting_by_affinity"]["close"])
            blob = " ".join(replies).lower()
            with self.subTest(lang=lang):
                self.assertTrue(
                    any(w.lower() in blob for w in _ALLOWED_WARMTH),
                    f"{lang} の close 挨拶に温かみの表明が無い: {replies}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
