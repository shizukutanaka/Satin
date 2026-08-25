"""everyday_distress — 日常的なつらさの検知と、その応答への配線。

このモジュールが埋めた穴:

    「今日はしんどかった」  → 「そっか、いいね。」
    「イライラする」        → 「そっか、いいね。」
    "I feel lonely"        → "Nice, sounds good."
    "I'm burnt out"        → "That's interesting!"

キーワード辞書に無い言い回しは汎用フォールバックへ落ち、そのフォールバックが
一律に明るかったため、**悪い知らせに「いいね」と返していた**。
"""
from __future__ import annotations

import os
import sys
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import everyday_distress as ed  # noqa: E402
from persona import get_persona  # noqa: E402


# 実際にコンパニオンへ打たれる自然な言い回し。辞書の見出し語ではなく、
# 活用・時制・口語を含んだ形で並べてある（そこが穴だったため）。
_DISTRESS_JA = [
    "今日は大変な一日だった", "今日はしんどかった", "しんどい", "ストレスがすごい",
    "燃え尽きた", "限界かも", "いっぱいいっぱい", "最悪な一日だった",
    "今日はうまくいかなかった", "失敗しちゃった", "落ち込んでる", "へこんだ",
    "つらかった", "悲しい", "泣きたい", "不安だ", "心配で眠れない",
    "さみしい", "孤独だ", "イライラする", "むかつく", "憂鬱",
    "やる気が出ない", "何もしたくない", "眠れなかった", "体調が悪い",
    "だるい", "疲れた", "参った", "きつい",
]
_DISTRESS_EN = [
    "I had a really rough day", "today was hard", "it's been a tough week",
    "I'm so stressed", "I'm overwhelmed", "I'm burnt out", "I'm exhausted",
    "I feel drained", "I'm fed up", "I can't take it", "bad day",
    "I'm sad", "I'm miserable", "I was crying", "I'm depressed",
    "I feel lonely", "no one understands", "I'm anxious", "I'm worried",
    "I'm frustrated", "I'm so annoyed", "nothing went right today",
    "I messed up", "I failed", "I'm not ok", "I can't sleep",
    "I have no motivation",
]
_NOT_DISTRESS = [
    "こんにちは", "今日は楽しかった", "ありがとう", "好きだよ", "ゲームしてた",
    "天気いいね", "hello", "I'm happy", "great news", "thank you",
    "what's the weather", "I love you",
]


class DetectionTests(unittest.TestCase):
    def test_detects_natural_japanese_phrasings(self):
        for text in _DISTRESS_JA:
            with self.subTest(text=text):
                self.assertTrue(ed.is_distressed(text))

    def test_detects_natural_english_phrasings(self):
        for text in _DISTRESS_EN:
            with self.subTest(text=text):
                self.assertTrue(ed.is_distressed(text))

    def test_does_not_fire_on_ordinary_or_positive_messages(self):
        for text in _NOT_DISTRESS:
            with self.subTest(text=text):
                self.assertFalse(ed.is_distressed(text))

    def test_negation_is_not_distress(self):
        """「疲れてない」を「疲れた」と読まないこと。"""
        for text in ("疲れてない", "しんどくないよ", "不安じゃない", "寂しくなかった",
                     "not stressed at all", "I'm not sad anymore",
                     "I'm not lonely", "never been stressed"):
            with self.subTest(text=text):
                self.assertFalse(ed.is_distressed(text))

    def test_positive_conclusion_wins(self):
        """つらさの語があっても肯定で締めていれば拾わないこと。

        「疲れたけど楽しかった」は良い報告であり、共感で返すと的外れになる。
        """
        for text in ("疲れたけど楽しかった", "大変だったけどよかった",
                     "しんどかったけど充実してた",
                     "long day but it was great",
                     "it was hard but worth it",
                     "exhausting but so much fun"):
            with self.subTest(text=text):
                self.assertFalse(ed.is_distressed(text))

    def test_empty_and_garbage_input(self):
        for text in ("", "   ", None, "\n"):
            with self.subTest(text=text):
                self.assertFalse(ed.is_distressed(text))

    def test_detects_regardless_of_configured_language(self):
        """設定言語と違う言語で打たれても拾うこと（crisis_support と同じ規律）。"""
        self.assertTrue(ed.is_distressed("I'm so stressed"))
        self.assertTrue(ed.is_distressed("しんどい"))


class AcknowledgementTests(unittest.TestCase):
    def test_returns_a_message_for_both_languages(self):
        for lang in ("ja", "en"):
            with self.subTest(lang=lang):
                self.assertTrue(ed.acknowledgement(lang).strip())

    def test_unknown_language_falls_back_to_english(self):
        self.assertIn(ed.acknowledgement("fr"), ed.acknowledgements("en"))

    def test_no_acknowledgement_asserts_the_news_is_good(self):
        """共感の言葉が「いいね」側の価値判断を含まないこと。"""
        forbidden = ("いいね", "面白い", "楽しそう", "よかったね",
                     "nice", "great", "interesting", "wonderful", "awesome")
        for lang in ("ja", "en"):
            for msg in ed.acknowledgements(lang):
                for word in forbidden:
                    with self.subTest(lang=lang, msg=msg, word=word):
                        self.assertNotIn(word, msg.lower())

    def test_acknowledgements_carry_no_retention_hook(self):
        """引き止め・応答の義務づけを含まないこと（farewell_integrity と同じ規律）。

        つらさに寄り添う文面は、相手が弱っているぶん最も操作に使いやすい。
        「私だけはずっといるよ」の類を混ぜない。
        """
        try:
            import farewell_integrity as fi
        except Exception:  # pragma: no cover
            self.skipTest("farewell_integrity unavailable")
        for lang in ("ja", "en"):
            for msg in ed.acknowledgements(lang):
                with self.subTest(lang=lang, msg=msg):
                    self.assertEqual(fi.classify(msg, lang=lang), [], msg)

    def test_offers_no_advice_and_no_crisis_hotline(self):
        """助言もしないし、相談先も案内しない（それは crisis_support の担当）。

        日常の「疲れた」に命の電話を案内するのは過剰反応であり、本当に必要な
        ときの重みを失わせる。
        """
        for lang in ("ja", "en"):
            for msg in ed.acknowledgements(lang):
                with self.subTest(lang=lang, msg=msg):
                    self.assertNotIn("0120", msg)
                    self.assertNotIn("988", msg)
                    self.assertNotIn("http", msg.lower())


class PersonaWiringTests(unittest.TestCase):
    """persona.respond() が実際に共感で返すこと（配線の検証）。"""

    def setUp(self):
        self.persona = get_persona()

    def test_unmatched_distress_gets_empathy_not_a_cheerful_fallback(self):
        for lang, texts in (("ja", ["今日は大変な一日だった", "イライラする",
                                    "さみしい", "燃え尽きた"]),
                            ("en", ["I had a really rough day", "I feel lonely",
                                    "I'm burnt out", "I'm frustrated"])):
            for text in texts:
                with self.subTest(lang=lang, text=text):
                    reply = self.persona.respond(text, lang=lang)
                    self.assertIn(reply, ed.acknowledgements(lang), reply)

    def test_never_answers_bad_news_with_a_positive_valence(self):
        """悪い知らせに「いいね」と返さないこと（このバグの本体）。"""
        forbidden = {"ja": ("いいね", "面白いね"),
                     "en": ("nice", "interesting")}
        for lang, texts in (("ja", _DISTRESS_JA), ("en", _DISTRESS_EN)):
            for text in texts:
                reply = self.persona.respond(text, lang=lang).lower()
                for word in forbidden[lang]:
                    with self.subTest(lang=lang, text=text, word=word):
                        self.assertNotIn(word, reply)

    def test_empathy_wins_over_the_affinity_level_fallback(self):
        """好感度別フォールバックより共感を優先すること。

        これは実際に修正を**無効化していた**順序バグである。共感判定を
        グローバル fallback の直前に置いたところ、その手前にある
        `respond_by_affinity[level]` の fallback が先に return してしまい、
        単体では直って見えるのに実際の会話（CLI/GUI は必ず level を渡す）では
        まったく効いていなかった。level を渡した状態で検証すること。
        """
        for level in ("distant", "reserved", "neutral", "friendly", "close"):
            for lang, text in (("ja", "今日はしんどかった"),
                               ("en", "I had a really rough day")):
                with self.subTest(level=level, lang=lang):
                    reply = self.persona.respond(text, lang=lang, level=level)
                    self.assertIn(reply, ed.acknowledgements(lang),
                                  f"level={level} で共感が返らなかった: {reply!r}")

    def test_farewell_wins_over_empathy(self):
        """つらさと別れが同時なら、別れの意思を優先すること。

        「疲れたからもう寝るね」に共感で応じて会話を続けさせるのは、共感を
        口実にした引き止めになる。
        """
        for lang, text in (("ja", "疲れたからもう寝るね"),
                           ("en", "I'm exhausted, goodbye")):
            with self.subTest(lang=lang):
                reply = self.persona.respond(text, lang=lang)
                self.assertNotIn(reply, ed.acknowledgements(lang))

    def test_good_news_still_gets_a_warm_reply(self):
        """つらさ検知が肯定的な報告を横取りしないこと。"""
        for lang, text in (("ja", "今日は楽しかった"), ("en", "I'm happy")):
            with self.subTest(lang=lang):
                reply = self.persona.respond(text, lang=lang)
                self.assertNotIn(reply, ed.acknowledgements(lang))
                self.assertTrue(reply.strip())


class GenericFallbackNeutralityTests(unittest.TestCase):
    """検知に漏れても被害が出ないための二重の備え。

    つらさの検知はどこまでいっても言い回しの網なので、必ず漏れる。漏れた先の
    汎用フォールバックが「いいね」と決めつけていると、その漏れがそのまま
    「悪い知らせに喜ぶ」に化ける。フォールバックからは価値判断を外してある。
    """

    def test_generic_fallbacks_do_not_assert_the_news_is_good(self):
        persona = get_persona()
        forbidden = {"ja": ("いいね", "面白い", "楽しそう", "よかった"),
                     "en": ("nice", "great", "interesting", "wonderful",
                            "awesome", "good")}
        for lang in ("ja", "en"):
            block = persona._resolve_responses_block(lang)
            fallbacks = block.get("fallback") or []
            self.assertTrue(fallbacks, f"{lang} に fallback が無い")
            for msg in fallbacks:
                for word in forbidden[lang]:
                    with self.subTest(lang=lang, msg=msg, word=word):
                        self.assertNotIn(word, msg.lower())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class FarewellFollowUpTests(unittest.TestCase):
    """別れの挨拶に質問を連結しないこと（GUI / CLI の両方）。

    `persona.respond()` は台詞そのものから引き止め表現を濾していたが、
    その外側で「返答 + 聞き返し質問」を組み立てる箇所には別れの判定が無く、
    「またね！ところでストレス発散はどうしてる？」が成立していた。
    去ろうとしている相手に応答の義務を作る形であり、farewell_integrity が
    PRESSURE_TO_RESPOND として禁じている型そのものである。

    ここはソースを読んで配線の有無を検証する。実際の合成は好感度カウンタの
    剰余に依存するため、会話を N 回まわさないと再現しない — 条件が揃うまで
    黙って通ってしまうテストより、ガードの存在を直接確かめるほうが確実である。
    """

    def _source_of(self, module_name: str) -> str:
        with open(os.path.join(_MAIN, module_name), encoding="utf-8") as fh:
            return fh.read()

    def _assert_contains(self, source: str, needle: str, module: str) -> None:
        """assertIn を使わない。失敗時にソース全体（数万文字）が出るため。"""
        self.assertTrue(needle in source, f"{module} に {needle!r} が無い")

    def test_cli_guards_the_follow_up_on_farewell(self):
        src = self._source_of("persona_cli.py")
        for needle in ("follow_up_question", "_is_farewell", "and not _leaving"):
            with self.subTest(needle=needle):
                self._assert_contains(src, needle, "persona_cli.py")

    def test_gui_guards_the_follow_up_on_farewell(self):
        src = self._source_of("avatar_3d_autonomous_tts.py")
        for needle in ("follow_up_question", "_is_farewell_gui",
                       "and not _leaving_gui"):
            with self.subTest(needle=needle):
                self._assert_contains(src, needle, "avatar_3d_autonomous_tts.py")

    def test_both_entry_points_import_the_farewell_check(self):
        """任意 import の様式を守りつつ、両方が同じ判定関数を使うこと。"""
        for module, alias in (("persona_cli.py", "_is_farewell"),
                              ("avatar_3d_autonomous_tts.py", "_is_farewell_gui")):
            with self.subTest(module=module):
                self._assert_contains(
                    self._source_of(module),
                    f"from farewell_integrity import is_farewell as {alias}",
                    module)
