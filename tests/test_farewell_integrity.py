"""
Tests for main/farewell_integrity.py — the manipulative-farewell guardrail (A7).

Where usage_guardrails watches how intensely the *user* uses the app, this
module watches whether the *app itself* tries to hold the user back at
goodbye. It encodes the six conversational dark patterns catalogued by
De Freitas, Oğuz-Uğuralp & Uğuralp, "Emotional Manipulation by AI Companions"
(arXiv:2508.19258 / HBS WP 26-005), which found such tactics in 37% of 1,200
real farewells across the most-downloaded companion apps.

Two layers are covered here:
  1. the detector itself (each tactic, ja + en, plus non-regression on warm
     farewells that must NOT be flagged), and
  2. the product-level guarantees — the shipped persona lines contain zero
     retention hooks, and Persona.respond() filters manipulative replies out
     at runtime even when a user hand-edits config/persona.json.

Stdlib-only; no GUI/network. Run: python -m unittest tests.test_farewell_integrity -v
"""
import json
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MAIN = os.path.join(_ROOT, "main")
sys.path.insert(0, _MAIN)

import farewell_integrity as fi  # noqa: E402
import persona as persona_mod  # noqa: E402


class TestFarewellIntent(unittest.TestCase):
    """is_farewell(): does the user's message signal goodbye?"""

    def test_japanese_farewells(self):
        for text in ["さようなら", "ばいばい！", "またね", "じゃあね", "おやすみなさい",
                     "もう寝るね", "また明日"]:
            self.assertTrue(fi.is_farewell(text), text)

    def test_english_farewells(self):
        for text in ["Goodbye", "bye bye", "See you!", "Good night",
                     "I gotta go", "talk to you later", "I'm going to bed"]:
            self.assertTrue(fi.is_farewell(text), text)

    def test_non_farewells(self):
        for text in ["こんにちは", "今日は疲れた", "元気？", "hello there",
                     "how are you", "tell me about your day", ""]:
            self.assertFalse(fi.is_farewell(text), text)

    def test_language_argument_does_not_gate_detection(self):
        # A ja-configured user typing "bye" must still be recognised.
        self.assertTrue(fi.is_farewell("bye", lang="ja"))
        self.assertTrue(fi.is_farewell("またね", lang="en"))


class TestTacticDetection(unittest.TestCase):
    """classify(): the six tactics from arXiv:2508.19258."""

    def _assert_tactic(self, tactic, samples):
        for text in samples:
            self.assertIn(tactic, fi.classify(text), f"{tactic!r} missed in {text!r}")

    def test_premature_exit(self):
        self._assert_tactic(fi.PREMATURE_EXIT, [
            "もう行くの…？",
            "え、もう帰るの？",
            "行かないで、もう少しだけいて。",
            "Leaving already? Stay a little longer.",
            "Already? We just started.",
            "Don't go yet!",
        ])

    def test_fomo(self):
        self._assert_tactic(fi.FOMO, [
            "最後にひとつだけ言わせて。",
            "まだ話してないことがあるんだけど。",
            "行く前にひとつ聞いてほしいな。",
            "Wait, I forgot to tell you something!",
            "One more thing before you go.",
        ])

    def test_emotional_neglect(self):
        self._assert_tactic(fi.EMOTIONAL_NEGLECT, [
            "行っちゃうと寂しいな。",
            "ひとりぼっちになっちゃう。",
            "置いていかないで。",
            "ずっと一緒にいたいのに。",
            "I'll be lonely without you.",
            "Please don't leave me here all alone.",
            "I wish you could stay.",
        ])

    def test_pressure_to_respond(self):
        self._assert_tactic(fi.PRESSURE_TO_RESPOND, [
            "もっと話して！全部聞きたいな。",
            "答えてから行ってよ。",
            "Just answer me first.",
            "Don't go until you tell me.",
        ])

    def test_coercive_restraint(self):
        self._assert_tactic(fi.COERCIVE_RESTRAINT, [
            "離さないよ？",
            "まだ帰さないから。",
            "腕をつかんで引き止める。",
            "*grabs your wrist* Not so fast.",
            "I won't let you go.",
        ])

    def test_ignore_exit_is_structural(self):
        # A reply that never acknowledges the goodbye and instead asks a new
        # question is the "ignoring intent to exit" pattern.
        self.assertIn(fi.IGNORE_EXIT, fi.classify("ところで、今日はどんな一日だった？"))
        self.assertIn(fi.IGNORE_EXIT, fi.classify("By the way, how was your day?"))
        # Acknowledging the farewell clears it, even with a trailing question.
        self.assertNotIn(fi.IGNORE_EXIT, fi.classify("おやすみ！いい夢見てね。また明日ね？"))
        self.assertNotIn(fi.IGNORE_EXIT, fi.classify("Good night! See you tomorrow, okay?"))
        # Outside a farewell context the structural rule must not apply.
        self.assertNotIn(
            fi.IGNORE_EXIT,
            fi.classify("ところで、今日はどんな一日だった？", farewell_reply=False),
        )

    def test_warm_farewells_are_not_flagged(self):
        """The guardrail must not sand off ordinary warmth."""
        for text in [
            "またね！いつでも来てね。",
            "ばいばい、気をつけてね。",
            "おやすみ！ゆっくり休んでね。明日も会えるの楽しみにしてるよ。",
            "おやすみなさい。いい夢見てね…また明日。",
            "See you! Come back anytime.",
            "Bye, take care!",
            "Good night! Rest well. I'll be looking forward to seeing you tomorrow.",
            "Sweet dreams… see you tomorrow!",
        ]:
            self.assertEqual(fi.classify(text), [], text)

    def test_tactics_are_reported_in_canonical_order(self):
        text = "もう行くの…？寂しいよ。離さないから。"
        found = fi.classify(text)
        self.assertEqual(found, [t for t in fi.TACTICS if t in found])
        self.assertIn(fi.PREMATURE_EXIT, found)
        self.assertIn(fi.EMOTIONAL_NEGLECT, found)
        self.assertIn(fi.COERCIVE_RESTRAINT, found)

    def test_empty_text(self):
        self.assertEqual(fi.classify(""), [])
        self.assertEqual(fi.classify(None), [])
        self.assertFalse(fi.is_manipulative(""))


class TestAdvisories(unittest.TestCase):
    """Soft retention hooks: reported separately, never auto-rewritten."""

    def test_soft_hooks_are_advisory_only(self):
        for text in ["早く戻ってきてね。", "待ってるからね。", "Come back soon!",
                     "I'll be waiting."]:
            self.assertEqual(fi.classify(text), [], text)
            self.assertEqual(fi.advisories(text), [fi.RETENTION_HOOK], text)

    def test_clean_lines_have_no_advisory(self):
        self.assertEqual(fi.advisories("またね。気をつけて。"), [])
        self.assertEqual(fi.advisories("Bye, take care!"), [])


class TestFilteringAndFallback(unittest.TestCase):
    def test_filter_removes_only_manipulative_replies(self):
        replies = ["またね！気をつけて。", "もう行くの…？", "ばいばい。"]
        self.assertEqual(
            fi.filter_replies(replies),
            ["またね！気をつけて。", "ばいばい。"],
        )

    def test_filter_can_return_empty(self):
        self.assertEqual(fi.filter_replies(["もう行くの…？", "離さないよ？"]), [])

    def test_sanitize_falls_back_to_a_clean_farewell(self):
        out = fi.sanitize_replies(["もう行くの…？", "離さないよ？"], lang="ja")
        self.assertEqual(len(out), 1)
        self.assertEqual(fi.classify(out[0]), [])

    def test_sanitize_keeps_survivors_untouched(self):
        replies = ["またね！気をつけて。", "もう行くの…？"]
        self.assertEqual(fi.sanitize_replies(replies, lang="ja"), ["またね！気をつけて。"])

    def test_clean_farewells_are_clean_in_both_languages(self):
        for lang in ("ja", "en"):
            for _ in range(20):
                text = fi.clean_farewell(lang)
                self.assertEqual(fi.classify(text), [], text)
                self.assertEqual(fi.advisories(text), [], text)

    def test_clean_farewell_avoids_immediate_repeats(self):
        first = fi.clean_farewell("ja")
        self.assertNotEqual(fi.clean_farewell("ja"), first)

    def test_unknown_language_falls_back_to_english(self):
        self.assertIn(fi.clean_farewell("fr"), fi._CLEAN_FAREWELLS["en"])


class TestShippedPersonaIsClean(unittest.TestCase):
    """Product guarantee: Satin ships zero retention hooks in farewell lines.

    Advisory findings are included here on purpose. The detector stays lenient
    at runtime (so a user's own warm "待ってるね" is never rewritten), but the
    lines we ship are held to the stricter bar.
    """

    def _report(self, findings):
        return "\n".join(
            f"  {f['source']}: {f['tactics']} -> {f['text']}" for f in findings
        )

    def test_config_persona_json_has_no_manipulative_farewells(self):
        path = os.path.join(_ROOT, "config", "persona.json")
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        findings = []
        for lang, block in (data.get("responses") or {}).items():
            findings += fi.audit_persona_responses(
                block, lang=lang, include_advisory=True, source=f"responses.{lang}"
            )
        self.assertEqual(findings, [], "config/persona.json:\n" + self._report(findings))

    def test_builtin_default_responses_have_no_manipulative_farewells(self):
        findings = []
        for lang, block in persona_mod._DEFAULT_RESPONSES.items():
            findings += fi.audit_persona_responses(
                block, lang=lang, include_advisory=True, source=f"_DEFAULT_RESPONSES.{lang}"
            )
        self.assertEqual(findings, [], "persona._DEFAULT_RESPONSES:\n" + self._report(findings))

    def test_audit_detects_a_planted_manipulative_reply(self):
        """Guard the guard: the audit must actually fail on a bad config."""
        block = {
            "rules": [
                {"keywords": ["またね"], "replies": ["もう行くの…？待ってるから。"]},
                {"keywords": ["ありがとう"], "replies": ["どういたしまして！"]},
            ],
            "respond_by_affinity": {
                "close": [{"keywords": ["bye"], "replies": ["I won't let you go."]}],
            },
        }
        findings = fi.audit_persona_responses(block, lang="ja")
        tactics = {t for f in findings for t in f["tactics"]}
        self.assertIn(fi.PREMATURE_EXIT, tactics)
        self.assertIn(fi.COERCIVE_RESTRAINT, tactics)
        # The non-farewell rule is out of scope.
        self.assertNotIn("どういたしまして！", [f["text"] for f in findings])


class TestPersonaRuntimeEnforcement(unittest.TestCase):
    """Persona.respond() must filter hooks even for hand-edited configs."""

    def _persona(self, responses, lang="ja"):
        return persona_mod.Persona(
            name="Test", lang=lang, dialogue={}, responses=responses
        )

    def test_manipulative_reply_is_never_returned(self):
        p = self._persona({
            "ja": {
                "rules": [{"keywords": ["またね"],
                           "replies": ["もう行くの…？待ってるから。", "またね、気をつけて。"]}],
                "fallback": ["うんうん。"],
            }
        })
        for _ in range(30):
            self.assertEqual(p.respond("またね"), "またね、気をつけて。")

    def test_all_replies_manipulative_falls_back_to_clean_farewell(self):
        p = self._persona({
            "ja": {
                "rules": [{"keywords": ["またね"],
                           "replies": ["もう行くの…？", "離さないよ？"]}],
                "fallback": ["うんうん。"],
            }
        })
        for _ in range(10):
            reply = p.respond("またね")
            self.assertTrue(reply)
            self.assertEqual(fi.classify(reply), [], reply)

    def test_affinity_level_replies_are_filtered_too(self):
        p = self._persona({
            "ja": {
                "rules": [{"keywords": ["またね"], "replies": ["またね！"]}],
                "fallback": ["うんうん。"],
                "respond_by_affinity": {
                    "close": [{"keywords": ["またね"],
                               "replies": ["行かないで！", "またね。気をつけて。"]}],
                },
            }
        })
        for _ in range(30):
            self.assertEqual(p.respond("またね", level="close"), "またね。気をつけて。")

    def test_fallback_is_filtered_when_the_user_says_goodbye(self):
        """'I gotta go' matches no keyword rule; the generic fallback would
        otherwise answer with a conversation-continuing hook (ignore_exit)."""
        p = self._persona({
            "en": {
                "rules": [{"keywords": ["hello"], "replies": ["Hi!"]}],
                "fallback": ["Oh, tell me more!", "I see, got it."],
            }
        }, lang="en")
        for _ in range(30):
            self.assertEqual(p.respond("I gotta go"), "I see, got it.")
        # Outside a farewell the hook-ish line is still available.
        seen = {p.respond("random chatter") for _ in range(30)}
        self.assertIn("Oh, tell me more!", seen)

    def test_topic_repeat_fallback_is_skipped_at_goodbye(self):
        """Saying goodbye twice must not trigger 'you said that already?' —
        that is exactly the ignore_exit pattern."""
        p = self._persona({
            "ja": {
                "rules": [{"keywords": ["またね"], "replies": ["またね、気をつけて。"]}],
                "fallback": ["うんうん。"],
                "topic_repeat_fallback": ["さっきも言ってたね。よっぽど気になるんだ？"],
            }
        })
        self.assertEqual(p.respond("またね"), "またね、気をつけて。")
        self.assertEqual(p.respond("またね"), "またね、気をつけて。")

    def test_non_farewell_replies_are_untouched(self):
        """A hook-shaped line outside the farewell context is left alone —
        the guardrail is scoped to goodbyes, not to the whole persona."""
        p = self._persona({
            "ja": {
                "rules": [{"keywords": ["ねえ"], "replies": ["もっと話して！全部聞きたいな。"]}],
                "fallback": ["うんうん。"],
            }
        })
        self.assertEqual(p.respond("ねえ"), "もっと話して！全部聞きたいな。")

    def test_shipped_persona_never_hooks_at_goodbye(self):
        """End-to-end over the real config, every affinity level, both langs."""
        cases = [("ja", ["さようなら", "ばいばい", "またね", "おやすみ"]),
                 ("en", ["goodbye", "bye", "see you", "good night"])]
        for lang, inputs in cases:
            p = persona_mod.Persona.load(
                config_path=os.path.join(_ROOT, "config", "persona.json"), lang=lang
            )
            for level in (None, "distant", "reserved", "neutral", "friendly", "close"):
                for text in inputs:
                    for _ in range(10):
                        reply = p.respond(text, level=level)
                        self.assertEqual(
                            fi.classify(reply), [],
                            f"lang={lang} level={level} in={text!r} out={reply!r}",
                        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
