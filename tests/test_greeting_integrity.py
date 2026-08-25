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


class RelationshipTransitionIntegrityTests(unittest.TestCase):
    """関係レベルの遷移メッセージが、離れることに圧力をかけないこと。

    レベルダウンは**ユーザーが離れているとき**にしか起きない。そこで
    「もっと話しかけてほしいな」「忘れないでね」「いつでも待ってるのに」と
    言うのは、engagement が落ちたまさにその瞬間に感情的な圧力をかける形で、
    典型的な引き止めの構造である。以前は 8 種すべてがこの型で、圧力を含まない
    選択肢が存在しなかった。

    しかも本製品は `usage_guardrails` で「少し休んで、身近な人とも話してみてね」
    と促している。同じアプリの別の場所が離れることを咎めていては、その働きかけ
    は成立しない。

    引く線は挨拶のときと同じ: **気持ちの表明は残し、要求と非難を外す。**
        「なんかちょっと寂しい」        → 残す（自分の気持ち）
        「もっと話しかけてほしいな」    → 外す（engagement の要求）
        「忘れないでね」                → 外す（罪悪感）
        「いつでも待ってるのに」        → 外す（「のに」が非難）
    """

    def setUp(self):
        import sys
        _MAIN = os.path.join(_ROOT, "main")
        if _MAIN not in sys.path:
            sys.path.insert(0, _MAIN)
        import mood
        import farewell_integrity
        self.mood = mood
        self.fi = farewell_integrity

    def _all_transition_messages(self):
        for key, block in self.mood._TRANSITION_MESSAGES.items():
            for lang, msgs in block.items():
                for msg in msgs:
                    yield key, lang, msg

    def test_no_transition_message_uses_a_retention_tactic(self):
        """`ignore_exit` は別れ文脈専用なので除外し、文脈非依存の型だけ見る。

        遷移メッセージは会話の途中に出るので、「会話を続けようとすること」
        自体は操作ではない。罪悪感（emotional_neglect）と応答の義務づけ
        （pressure_to_respond）だけが問題になる。
        """
        offenders = []
        for key, lang, msg in self._all_transition_messages():
            tactics = [t for t in self.fi.classify(msg, lang=lang)
                       if t != "ignore_exit"]
            if tactics:
                offenders.append(f"{key}/{lang}: {msg!r} -> {tactics}")
        self.assertEqual(offenders, [],
                         "引き止めの型を含む遷移メッセージ:\n  "
                         + "\n  ".join(offenders))

    def test_level_down_messages_do_not_demand_more_contact(self):
        """離れているときに、より多くの接触を要求しないこと。"""
        order = ["distant", "reserved", "neutral", "friendly", "close"]
        demands = ["もっと話", "話しかけてほしい", "忘れないで", "待ってるのに",
                   "talk to me more", "don't forget me", "you'll talk to me"]
        offenders = []
        for key, lang, msg in self._all_transition_messages():
            before, _, after = key.partition("→")
            if before not in order or after not in order:
                continue
            if order.index(after) >= order.index(before):
                continue  # レベルアップは対象外
            for d in demands:
                if d.lower() in msg.lower():
                    offenders.append(f"{key}/{lang}: {msg!r}")
                    break
        self.assertEqual(offenders, [],
                         "離れているときに接触を要求している:\n  "
                         + "\n  ".join(offenders))

    def test_level_up_messages_do_not_claim_elapsed_time(self):
        """レベルアップは数分で起こりうるので、経過時間を主張しないこと。

        既定設定では初セッションの 3 メッセージ目で neutral→friendly に達し、
        「最近あなたのこと、友達だって思ってるんだ」が出ていた。出会って
        30 秒の相手に「最近」は嘘である。
        """
        order = ["distant", "reserved", "neutral", "friendly", "close"]
        time_claims = ["最近", "ずっと前から", "lately", "all this time",
                       "these days", "for a while now"]
        offenders = []
        for key, lang, msg in self._all_transition_messages():
            before, _, after = key.partition("→")
            if before not in order or after not in order:
                continue
            if order.index(after) <= order.index(before):
                continue  # レベルダウンは減衰＝時間経過が前提なので正当
            for c in time_claims:
                if c.lower() in msg.lower():
                    offenders.append(f"{key}/{lang}: {msg!r}")
                    break
        self.assertEqual(offenders, [],
                         "レベルアップで経過時間を主張している:\n  "
                         + "\n  ".join(offenders))

    def test_every_transition_still_has_messages(self):
        """圧力を外した結果、空になっていないこと。"""
        for key, block in self.mood._TRANSITION_MESSAGES.items():
            for lang in ("ja", "en"):
                with self.subTest(key=key, lang=lang):
                    self.assertTrue(block.get(lang), f"{key}/{lang} が空")


class ModuleWideDialogueIntegrityTests(unittest.TestCase):
    """全モジュールの台詞データに、文脈非依存の操作的表現が無いこと。

    ここまで挨拶・別れ・つらさ・告白・レベル遷移と 1 箇所ずつ潰してきたが、
    その都度「他にも同じものがあるのでは」という疑いが残る。台詞データを
    横断して一度に見ることで、その疑いを毎回の実行で解消する。

    ## 何を見て、何を見ないか

    見るのは **emotional_neglect（罪悪感）・coercive_restraint（束縛）・
    fomo（取り逃がしの不安）** の 3 つだけ。これらは「どの場面で言われても
    操作である」型なので、文脈を知らなくても判定できる。

    見ないのは `ignore_exit` と `pressure_to_respond`。この 2 つは**別れの
    文脈でのみ**操作になる — 会話の途中の「もっと聞かせて！」はごく普通の
    相づちであり、実際 `persona.respond` は別れを検知したときだけ
    `_farewell_safe()` でこれらを濾している。文脈を無視して当てると、
    「元気だった？」「朝ごはん食べた？」まで違反として並び、本物が埋もれる
    （persona.json 全体に当てて 133 件出したのが実際の失敗例）。

    正規表現定数（`*_PATTERNS`）と docstring は台詞ではないので除外する
    （こちらも一度取りこぼした）。
    """

    #: 台詞を持つモジュール。安全機構そのものも含める（自分だけ例外にしない）。
    MODULES = (
        "gifts", "special_days", "daily_summary", "break_reminder", "daily_mood",
        "profile_questions", "user_wellbeing", "usage_guardrails",
        "notification_system", "crisis_support", "everyday_distress",
        "mood", "persona",
    )

    #: 場面を問わず操作にあたる型。
    CONTEXT_FREE_TACTICS = ("emotional_neglect", "coercive_restraint", "fomo")

    def setUp(self):
        import sys
        main_dir = os.path.join(_ROOT, "main")
        if main_dir not in sys.path:
            sys.path.insert(0, main_dir)
        import farewell_integrity
        self.fi = farewell_integrity

    def _iter_dialogue(self):
        import importlib
        for name in self.MODULES:
            module = importlib.import_module(name)
            for attr in dir(module):
                if attr.startswith("__"):
                    continue
                if not (attr.isupper() or attr.startswith("_")):
                    continue
                if "PATTERN" in attr or attr.endswith("_RE"):
                    continue  # 正規表現は台詞ではない
                value = getattr(module, attr, None)
                if not isinstance(value, (dict, list, tuple, str)):
                    continue
                for path, line in _iter_strings(value, f"{name}.{attr}"):
                    if len(line) < 6 or line.startswith("\n"):
                        continue
                    yield path, line

    def test_no_dialogue_line_uses_a_context_free_manipulation(self):
        offenders = []
        for path, line in self._iter_dialogue():
            lang = "ja" if re.search(r"[ぁ-んァ-ン一-龥]", line) else "en"
            tactics = [t for t in self.fi.classify(line, lang=lang)
                       if t in self.CONTEXT_FREE_TACTICS]
            if tactics:
                offenders.append(f"{path}: {line!r} -> {tactics}")
        self.assertEqual(offenders, [],
                         "文脈に関係なく操作的な台詞:\n  " + "\n  ".join(offenders))

    def test_the_sweep_actually_reaches_dialogue(self):
        """走査が空振りしていないこと。

        フィルタを厳しくしすぎて 0 件を走査し、それを「違反なし」と読む —
        という失敗は、このクラスがいちばん起こしやすい。
        """
        seen = list(self._iter_dialogue())
        self.assertGreater(len(seen), 200, f"走査できた台詞が {len(seen)} 件しかない")

