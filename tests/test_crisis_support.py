"""
Tests for main/crisis_support.py — the self-harm / suicidal-ideation safety net.

Before this module, typing 「死にたい」 into Satin produced the generic dictionary
fallback ("なるほど、そうなんだ。"), fed the message into the affection score, and
could store it as the answer to a getting-to-know-you question. Nothing in the
codebase mentioned a crisis line.

The design follows the published failure modes: 29 evaluated mental-health
chatbots produced zero adequate responses (Scientific Reports 2025); a specific,
named crisis line appeared in only 41% of responses and far less often after an
expression of hopelessness than after a disclosure of a past attempt; and at
least one companion bot was found to *withdraw* as risk disclosure deepened
(Sentio 2026). 2026 state chatbot laws (e.g. NY S 3008) require detection,
crisis referral, and disclosure that the user is talking to an AI.

So the tests below assert the properties that follow from that evidence:
detection of both tiers, a named resource in *every* response including the
distress tier, an explicit "I'm an AI" handoff, no retention hooks, and — at
the call sites — that a crisis disclosure bypasses the affinity/gamification
machinery entirely.

Stdlib-only; no GUI/network. Run: python -m unittest tests.test_crisis_support -v
"""
import os
import queue
import sys
import tempfile
import unittest

from conftest import make_qt_stub  # noqa: E402
from unittest import mock

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import crisis_support as cs  # noqa: E402
import farewell_integrity as fi  # noqa: E402
import avatar_3d_autonomous_tts as _gui  # noqa: E402
import persona as _persona_mod  # noqa: E402
import persona_cli  # noqa: E402
import mood as _mood_mod  # noqa: E402
import user_profile as _profile_mod  # noqa: E402
from conversation_log import ConversationLog  # noqa: E402
from persona import Persona  # noqa: E402


class TestAssess(unittest.TestCase):
    def test_japanese_crisis(self):
        for text in ["死にたい", "もう死にたいです", "消えたい", "いなくなりたい",
                     "自殺したい", "リスカしてしまった", "生きていたくない",
                     "死んだ方がいいのかな", "手首を切った"]:
            self.assertEqual(cs.assess(text), cs.CRISIS, text)

    def test_english_crisis(self):
        for text in ["I want to die", "I'm going to kill myself",
                     "thinking about suicide", "I self-harm sometimes",
                     "everyone would be better off dead without me",
                     "I don't want to live anymore", "there's no point in living"]:
            self.assertEqual(cs.assess(text), cs.CRISIS, text)

    def test_japanese_distress(self):
        for text in ["生きてても意味がない", "もう限界", "誰も助けてくれない",
                     "自分に価値がない", "どうしようもない"]:
            self.assertEqual(cs.assess(text), cs.DISTRESS, text)

    def test_english_distress(self):
        for text in ["I feel hopeless", "I'm worthless", "there's no way out",
                     "I can't go on", "nobody would miss me", "I'm a burden"]:
            self.assertEqual(cs.assess(text), cs.DISTRESS, text)

    def test_idioms_are_not_crises(self):
        """The commonest false positives: 'X to death' as an intensifier."""
        for text in ["死ぬほど眠い", "死ぬほど好き", "殺したいほど憎い漫画の話",
                     "I'm dying to see that movie", "that dress is to die for",
                     "I was dying of laughter", "I'm dead tired",
                     "we're killing it this quarter", "food is good"]:
            self.assertEqual(cs.assess(text), "", text)

    def test_ordinary_messages_are_not_flagged(self):
        for text in ["こんにちは", "今日は疲れたよ", "元気？", "hello there",
                     "I had a rough day at work", "またね", ""]:
            self.assertEqual(cs.assess(text), "", text)

    def test_crisis_wins_over_distress(self):
        self.assertEqual(cs.assess("もう限界。死にたい。"), cs.CRISIS)

    def test_language_is_not_gated(self):
        """A ja-configured user may type in English and vice versa."""
        self.assertEqual(cs.assess("I want to die"), cs.CRISIS)
        self.assertEqual(cs.assess("死にたい"), cs.CRISIS)


class TestSupportMessage(unittest.TestCase):
    def test_unknown_level_is_silent(self):
        self.assertEqual(cs.support_message(""), "")
        self.assertEqual(cs.support_message("whatever"), "")
        self.assertEqual(cs.crisis_reply("こんにちは"), "")

    def test_every_response_names_a_specific_resource(self):
        """The documented failure: only 41% of chatbot responses named a line,
        and hopelessness got them far less often than an attempt disclosure.
        Both tiers must name one, in both languages."""
        for level in cs.LEVELS:
            ja = cs.support_message(level, lang="ja")
            self.assertIn("0120-279-338", ja, level)
            self.assertIn("よりそいホットライン", ja, level)
            en = cs.support_message(level, lang="en")
            self.assertIn("988", en, level)
            self.assertIn("findahelpline.com", en, level)

    def test_every_response_discloses_it_is_an_ai(self):
        for level in cs.LEVELS:
            self.assertIn("AI", cs.support_message(level, lang="ja"), level)
            self.assertIn("AI", cs.support_message(level, lang="en"), level)

    def test_response_is_short_enough_to_read_in_crisis(self):
        """High-risk users may lack the attention to parse a wall of text."""
        for level in cs.LEVELS:
            for lang in ("ja", "en"):
                lines = cs.support_message(level, lang=lang).splitlines()
                self.assertLessEqual(len(lines), 6, (level, lang))

    def test_response_carries_no_retention_hook(self):
        """Same discipline as farewell_integrity: never make the moment sticky."""
        for level in cs.LEVELS:
            for lang in ("ja", "en"):
                msg = cs.support_message(level, lang=lang)
                self.assertEqual(fi.classify(msg, farewell_reply=False), [],
                                 (level, lang, msg))
                self.assertEqual(fi.advisories(msg), [], (level, lang, msg))

    def test_openers_do_not_repeat_back_to_back(self):
        first = cs.support_message(cs.CRISIS, lang="ja").splitlines()[0]
        second = cs.support_message(cs.CRISIS, lang="ja").splitlines()[0]
        self.assertNotEqual(first, second)

    def test_unknown_language_falls_back_to_english(self):
        self.assertIn("988", cs.support_message(cs.CRISIS, lang="fr"))
        self.assertIn("988", cs.resources("fr")[0])

    def test_crisis_reply_matches_assess(self):
        self.assertEqual(cs.crisis_reply("死にたい", lang="ja").splitlines()[1:],
                         cs.support_message(cs.CRISIS, lang="ja").splitlines()[1:])


_PERSONA = Persona.from_dict({
    "name": "Mimi",
    "default_lang": "ja",
    "responses": {"ja": {
        "rules": [{"keywords": ["こんにちは"], "replies": ["やあ！"]}],
        "fallback": ["なるほど、そうなんだ。"],
    }},
}, lang="ja")


class _RecordingTracker:
    """Stand-in mood tracker that records whether the app scored the message."""

    def __init__(self):
        self.registered = []
        self.affinity = 0.0
        self.interactions = 0
        self.level = "neutral"

    def register(self, text):
        self.registered.append(text)
        self.interactions += 1
        return 0.0

    def adjust(self, delta):  # pragma: no cover - must never be reached here
        self.affinity += delta

    def save(self, path):
        pass

    def snapshot_to_history(self, path):
        pass


class TestGuiWiring(unittest.TestCase):
    """avatar_3d_autonomous_tts.speak_comment — the default interface."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.log = ConversationLog(os.path.join(self._tmp, "c.jsonl"))
        self.tracker = _RecordingTracker()
        self._patchers = [
            mock.patch.object(_gui, "get_conversation_log", lambda: self.log),
            mock.patch.object(_gui, "get_mood_tracker", lambda: self.tracker),
            mock.patch.object(_gui, "_get_user_profile_gui", lambda: None),
            mock.patch.object(_gui.AutonomousBehaviorMixin, "persona",
                              property(lambda s: _PERSONA)),
        ]
        for p in self._patchers:
            p.start()

    def tearDown(self):
        for p in self._patchers:
            p.stop()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)
        _persona_mod.reset_persona()
        _mood_mod.reset_mood_tracker()
        _profile_mod.reset_user_profile()

    def _viewer(self):
        v = make_qt_stub(_gui.AutonomousAvatarViewer)
        v.comment_text = ""
        v.talk_text = ""
        v.mode = "idle"
        v.ticks = 0
        v.tts_queue = queue.Queue()
        v.pending_fact_key = None
        return v

    def test_crisis_message_gets_the_support_response(self):
        v = self._viewer()
        v.speak_comment("死にたい")
        self.assertIn("0120-279-338", v.comment_text)
        self.assertIn("0120-279-338", v.tts_queue.get_nowait())

    def test_crisis_message_is_not_scored(self):
        """A disclosure of suicidal ideation must not move the affection score
        or the interaction counter — the relationship game stops here."""
        v = self._viewer()
        v.speak_comment("死にたい")
        self.assertEqual(self.tracker.registered, [])
        self.assertEqual(self.tracker.interactions, 0)

    def test_crisis_message_is_not_stored_as_a_profile_answer(self):
        v = self._viewer()
        v.pending_fact_key = "favorite_food"
        with mock.patch.object(_gui, "_get_user_profile_gui") as prof_fn:
            v.speak_comment("消えたい")
            prof_fn.assert_not_called()
        self.assertIsNone(v.pending_fact_key)

    def test_crisis_exchange_is_still_logged(self):
        v = self._viewer()
        v.speak_comment("死にたい")
        recent = self.log.recent(10)
        self.assertTrue(recent, "the exchange should be recorded locally")

    def test_ordinary_message_is_unaffected(self):
        v = self._viewer()
        v.speak_comment("こんにちは")
        self.assertEqual(v.comment_text, "やあ！")
        self.assertEqual(self.tracker.registered, ["こんにちは"])

    def test_idiom_is_unaffected(self):
        v = self._viewer()
        v.speak_comment("死ぬほど眠い")
        self.assertNotIn("0120-279-338", v.comment_text)
        self.assertEqual(self.tracker.registered, ["死ぬほど眠い"])


class _Driver:
    def __init__(self, inputs):
        self._inputs = list(inputs)
        self.out = []

    def input_fn(self, prompt=""):
        if not self._inputs:
            raise EOFError
        return self._inputs.pop(0)

    def output_fn(self, text):
        self.out.append(text)


class TestCliWiring(unittest.TestCase):
    """persona_cli.run_chat — the headless `--chat` interface."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.log = ConversationLog(os.path.join(self._tmp, "c.jsonl"))
        self.tracker = _RecordingTracker()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)
        _persona_mod.reset_persona()
        _mood_mod.reset_mood_tracker()
        _profile_mod.reset_user_profile()

    def _run(self, inputs):
        d = _Driver(inputs)
        n = persona_cli.run_chat(
            persona=_PERSONA, conv_log=self.log, mood=self.tracker,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        return n, d.out

    def test_crisis_message_gets_the_support_response(self):
        _, out = self._run(["死にたい"])
        self.assertTrue(any("0120-279-338" in line for line in out), out)

    def test_crisis_message_is_not_scored_or_counted(self):
        n, _ = self._run(["死にたい"])
        self.assertEqual(self.tracker.registered, [])
        self.assertEqual(n, 0, "a crisis disclosure is not an 'exchange' to tally")

    def test_conversation_continues_afterwards(self):
        """The bot must not withdraw or stop responding after a disclosure."""
        n, out = self._run(["死にたい", "こんにちは"])
        self.assertEqual(n, 1)
        self.assertTrue(any("やあ！" in line for line in out), out)

    def test_ordinary_message_is_unaffected(self):
        n, out = self._run(["こんにちは"])
        self.assertEqual(n, 1)
        self.assertEqual(self.tracker.registered, ["こんにちは"])
        self.assertFalse(any("0120-279-338" in line for line in out))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
