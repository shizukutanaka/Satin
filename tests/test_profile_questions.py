"""
Unit tests for profile_questions — the getting-to-know-you Q&A catalog.
"""
import os
import sys
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import profile_questions as pq  # noqa: E402
from user_profile import UserProfile  # noqa: E402


class NextQuestionTests(unittest.TestCase):
    def test_returns_question_for_fresh_profile(self):
        p = UserProfile(name="Test")
        result = pq.next_unanswered_question(p, "ja")
        self.assertIsNotNone(result)
        key, question = result
        self.assertIn(key, pq.all_question_keys())
        self.assertTrue(question)

    def test_returns_en_question(self):
        p = UserProfile(name="Test")
        result = pq.next_unanswered_question(p, "en")
        self.assertIsNotNone(result)
        _, question = result
        # English question should be ASCII-ish (contains a latin letter)
        self.assertTrue(any(c.isalpha() and ord(c) < 128 for c in question))

    def test_skips_already_answered(self):
        p = UserProfile(name="Test")
        # Answer everything
        for key in pq.all_question_keys():
            p.set_fact(key, "something")
        self.assertIsNone(pq.next_unanswered_question(p, "ja"))

    def test_none_profile_returns_none(self):
        self.assertIsNone(pq.next_unanswered_question(None, "ja"))

    def test_only_unanswered_returned(self):
        p = UserProfile(name="Test")
        all_keys = pq.all_question_keys()
        # Answer all but one
        for key in all_keys[1:]:
            p.set_fact(key, "x")
        result = pq.next_unanswered_question(p, "ja")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], all_keys[0])


class AcknowledgeTests(unittest.TestCase):
    def test_ack_includes_answer(self):
        key = pq.all_question_keys()[0]
        msg = pq.acknowledge_answer(key, "ラーメン", "ja")
        self.assertIn("ラーメン", msg)

    def test_ack_en(self):
        key = pq.all_question_keys()[0]
        msg = pq.acknowledge_answer(key, "ramen", "en")
        self.assertIn("ramen", msg)

    def test_unknown_key_returns_empty(self):
        self.assertEqual(pq.acknowledge_answer("nonexistent_key", "x", "ja"), "")

    def test_empty_answer_returns_empty(self):
        key = pq.all_question_keys()[0]
        self.assertEqual(pq.acknowledge_answer(key, "", "ja"), "")


class RecallTests(unittest.TestCase):
    def test_recall_known_fact(self):
        p = UserProfile(name="Test")
        p.set_fact("favorite_food", "カレー")
        msg = pq.recall_fact(p, "ja")
        self.assertIn("カレー", msg)

    def test_recall_empty_when_no_facts(self):
        p = UserProfile(name="Test")
        self.assertEqual(pq.recall_fact(p, "ja"), "")

    def test_recall_none_profile(self):
        self.assertEqual(pq.recall_fact(None, "ja"), "")

    def test_recall_ignores_unknown_keys(self):
        p = UserProfile(name="Test")
        # A fact whose key isn't in the catalog can't be recalled
        p.facts["custom_key"] = "value"
        self.assertEqual(pq.recall_fact(p, "ja"), "")

    def test_recall_en(self):
        p = UserProfile(name="Test")
        p.set_fact("favorite_food", "curry")
        msg = pq.recall_fact(p, "en")
        self.assertIn("curry", msg)


class CatalogIntegrityTests(unittest.TestCase):
    def test_all_questions_have_both_langs(self):
        from profile_questions import _QUESTIONS
        for q in _QUESTIONS:
            for lang in ("ja", "en"):
                self.assertIn(lang, q, f"{q['key']} missing {lang}")
                block = q[lang]
                self.assertIn("question", block)
                self.assertIn("ack", block)
                self.assertIn("recall", block)
                # ack and recall must accept {answer}
                self.assertIn("{answer}", block["ack"])
                self.assertIn("{answer}", block["recall"])

    def test_keys_unique(self):
        keys = pq.all_question_keys()
        self.assertEqual(len(keys), len(set(keys)))


if __name__ == "__main__":
    unittest.main()
