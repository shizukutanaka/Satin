"""
Tests for main/sentiment_target.py — which target a negative message is about.

Affinity answers "how did the user treat me"; wellbeing answers "how is the
user feeling". Both were reading the same document-level polarity, so Satin
scored self-criticism and venting as if they were aimed at the avatar:

    「自分が嫌い」          -> -1 -> affinity DOWN
    "I hate myself"        -> -1 -> affinity DOWN
    「今日は最悪な一日だった」 -> -1 -> affinity DOWN

and since low affinity moves replies toward the distant/reserved registers
(「…そう。」「…うん。」), the avatar got colder exactly when the user was
struggling. Document-level polarity is not a stand-in for target-level
polarity: the entity-level sentiment survey (arXiv:2304.14241) reports that
an entity's polarity matches the surrounding document's only 47.7% of the
time, which is why ABSA exists as a separate task at all.

The fix is deliberately one-sided: it can only cancel a *penalty*, only when
the target is explicitly readable as the user or their circumstances, and it
never touches `classify_sentiment` — user_wellbeing still needs to see the
negative polarity to notice that the user is down (research item A5).

Stdlib-only; no GUI/network. Run: python -m unittest tests.test_sentiment_target -v
"""
import os
import sys
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import sentiment_target as stgt  # noqa: E402
import mood as mood_mod  # noqa: E402


class TestDirectedAtCompanion(unittest.TestCase):
    def test_japanese_second_person(self):
        for text in ["あなたなんて嫌い", "あんた最悪", "君のこと嫌いだ",
                     "お前は最低だ", "きみはつまらない"]:
            self.assertTrue(stgt.is_directed_at_companion(text), text)

    def test_english_second_person(self):
        for text in ["you're the worst", "I hate you", "your replies are boring",
                     "you are so annoying"]:
            self.assertTrue(stgt.is_directed_at_companion(text), text)

    def test_unaddressed_rejections_still_count(self):
        """No pronoun, but unmistakably aimed at the avatar."""
        for text in ["うるさい", "黙れ", "消えろ", "もう来ないで",
                     "shut up", "go away", "leave me alone"]:
            self.assertTrue(stgt.is_directed_at_companion(text), text)

    def test_self_talk_is_not_directed_at_companion(self):
        for text in ["自分が嫌い", "I hate myself", "今日は最悪だった", ""]:
            self.assertFalse(stgt.is_directed_at_companion(text), text)


class TestSelfOrSituational(unittest.TestCase):
    def test_japanese_self_markers(self):
        for text in ["自分が嫌い", "私なんてダメだ", "僕なんて必要ない",
                     "俺は情けない"]:
            self.assertTrue(stgt.is_self_or_situational(text), text)

    def test_english_self_markers(self):
        for text in ["I hate myself", "I'm worthless", "I am so stupid",
                     "I feel awful", "it's my fault"]:
            self.assertTrue(stgt.is_self_or_situational(text), text)

    def test_situational_markers(self):
        for text in ["今日は最悪な一日だった", "仕事でミスをした",
                     "上司に怒られた", "満員電車がつらい",
                     "I had the worst day at work", "my boss was awful today"]:
            self.assertTrue(stgt.is_self_or_situational(text), text)

    def test_bare_negatives_are_not_classified(self):
        """Ambiguous input keeps the original behaviour — no target is readable."""
        for text in ["つまらない", "最悪", "boring", "awful", ""]:
            self.assertFalse(stgt.is_self_or_situational(text), text)


class TestSuppression(unittest.TestCase):
    def test_self_criticism_suppresses(self):
        for text in ["自分が嫌い", "私なんてダメだ", "I hate myself",
                     "I'm worthless and stupid"]:
            self.assertTrue(stgt.suppresses_affinity_penalty(text), text)

    def test_venting_suppresses(self):
        for text in ["今日は最悪な一日だった", "仕事で最悪なミスをした",
                     "I had the worst day at work"]:
            self.assertTrue(stgt.suppresses_affinity_penalty(text), text)

    def test_insults_do_not_suppress(self):
        for text in ["あなたなんて嫌い", "お前は最悪だ", "you're the worst",
                     "うるさい", "shut up"]:
            self.assertFalse(stgt.suppresses_affinity_penalty(text), text)

    def test_companion_marker_wins_over_self_marker(self):
        """'I'm upset because you ignored me' is still about the avatar."""
        self.assertFalse(
            stgt.suppresses_affinity_penalty("I'm sad because you ignored me"))
        self.assertFalse(
            stgt.suppresses_affinity_penalty("自分も悪いけど、あなたが嫌い"))

    def test_ambiguous_input_keeps_old_behaviour(self):
        for text in ["つまらない", "最悪", "boring", "", None]:
            self.assertFalse(stgt.suppresses_affinity_penalty(text), text)


class TestMoodIntegration(unittest.TestCase):
    """The point of the module: what MoodTracker.register actually does."""

    def _tracker(self):
        return mood_mod.MoodTracker(affinity=50.0)

    def test_self_criticism_no_longer_costs_affinity(self):
        t = self._tracker()
        before = t.affinity
        delta = t.register("自分が嫌い")
        self.assertEqual(delta, 0.0)
        self.assertEqual(t.affinity, before)

    def test_english_self_criticism_no_longer_costs_affinity(self):
        t = self._tracker()
        self.assertEqual(t.register("I hate myself"), 0.0)

    def test_venting_about_the_day_no_longer_costs_affinity(self):
        t = self._tracker()
        self.assertEqual(t.register("今日は最悪な一日だった"), 0.0)

    def test_insults_still_cost_affinity(self):
        t = self._tracker()
        self.assertLess(t.register("あなたなんて嫌い"), 0.0)

    def test_english_insults_still_cost_affinity(self):
        t = self._tracker()
        self.assertLess(t.register("you're the worst"), 0.0)

    def test_bare_negative_still_costs_affinity(self):
        """Unchanged behaviour for input with no readable target."""
        t = self._tracker()
        self.assertLess(t.register("つまらない"), 0.0)

    def test_positive_messages_are_untouched(self):
        t = self._tracker()
        self.assertGreater(t.register("大好き"), 0.0)

    def test_positive_self_talk_still_gains(self):
        """Suppression is penalty-only — it must never cancel a gain."""
        t = self._tracker()
        self.assertGreater(t.register("自分は今日すごく嬉しい"), 0.0)

    def test_interaction_still_counted(self):
        """Suppressing the penalty is not the same as ignoring the message."""
        t = self._tracker()
        t.register("自分が嫌い")
        self.assertEqual(t.interactions, 1)

    def test_hurt_event_does_not_fire_on_self_criticism(self):
        """Otherwise the avatar acts wounded at someone insulting themselves."""
        t = self._tracker()
        delta = t.register("自分なんて最悪でひどい、大嫌いだ")
        self.assertFalse(mood_mod.check_hurt_event(delta, lang="ja"))

    def test_hurt_event_still_fires_on_a_real_insult(self):
        t = self._tracker()
        delta = t.register("あなたなんて最悪でひどい、大嫌いだ")
        self.assertTrue(mood_mod.check_hurt_event(delta, lang="ja"))

    def test_classify_sentiment_is_unchanged(self):
        """user_wellbeing (A5 change-point detection) still needs to see that
        the user is feeling bad — only the affinity penalty was suppressed."""
        self.assertEqual(mood_mod.classify_sentiment("自分が嫌い"), -1)
        self.assertEqual(mood_mod.classify_sentiment("I hate myself"), -1)
        self.assertEqual(mood_mod.classify_sentiment("今日は最悪な一日だった"), -1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
