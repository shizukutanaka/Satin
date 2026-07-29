"""
Tests for first_run — the first-launch onboarding (first-principles gap).

The product's value is "a companion that remembers you and grows a
relationship", but on first launch a user saw only a static avatar, a
jargon button ("自律モードON") and a placeholder implying text-to-speech —
so memory/affinity/slash-commands were invisible at first contact. These
tests cover the detection (must fire exactly once, for genuinely new users)
and the message content.
"""
import os
import sys
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import first_run  # noqa: E402


class IsFirstRunTests(unittest.TestCase):
    def test_true_for_brand_new_user(self):
        self.assertTrue(first_run.is_first_run(0, False, False))

    def test_false_when_has_interactions(self):
        self.assertFalse(first_run.is_first_run(1, False, False))

    def test_false_when_profile_name_known(self):
        # Returning user who taught a name but whose mood file was reset.
        self.assertFalse(first_run.is_first_run(0, True, False))

    def test_false_when_conversation_history_exists(self):
        self.assertFalse(first_run.is_first_run(0, False, True))

    def test_false_when_any_trace_present(self):
        self.assertFalse(first_run.is_first_run(5, True, True))

    def test_none_interactions_treated_as_zero(self):
        # Mood unreadable → fall back to the other traces.
        self.assertTrue(first_run.is_first_run(None, False, False))
        self.assertFalse(first_run.is_first_run(None, True, False))


class WelcomeMessageTests(unittest.TestCase):
    def test_japanese_mentions_help_and_memory(self):
        msg = first_run.welcome_message("ja")
        self.assertIn("/help", msg)
        self.assertIn("/callme", msg)
        self.assertIn("覚え", msg)

    def test_english_mentions_help_and_memory(self):
        msg = first_run.welcome_message("en")
        self.assertIn("/help", msg)
        self.assertIn("/callme", msg)
        self.assertIn("learns about you", msg)

    def test_english_selected_for_en_variants(self):
        self.assertEqual(first_run.welcome_message("en-US"),
                         first_run.welcome_message("en"))

    def test_defaults_to_japanese(self):
        self.assertEqual(first_run.welcome_message(None),
                         first_run.welcome_message("ja"))
        self.assertEqual(first_run.welcome_message("fr"),
                         first_run.welcome_message("ja"))

    def test_messages_are_non_empty_and_multiline(self):
        for lang in ("ja", "en"):
            msg = first_run.welcome_message(lang)
            self.assertTrue(msg.strip())
            self.assertIn("\n", msg, "welcome should list what the user can do")


if __name__ == "__main__":
    unittest.main()
