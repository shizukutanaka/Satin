"""
Unit tests for gifts — the /gift command catalog and lookup.
"""
import os
import sys
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from gifts import (  # noqa: E402
    all_gift_keys,
    gift_catalog_text,
    lookup_gift,
)

_KNOWN_KEYS = {"flowers", "chocolate", "book", "music", "cake", "ribbon", "letter"}


class LookupTests(unittest.TestCase):
    def test_ja_flower_exact(self):
        result = lookup_gift("花", lang="ja")
        self.assertIsNotNone(result)
        bonus, reply = result
        self.assertGreater(bonus, 0)
        self.assertIsInstance(reply, str)
        self.assertGreater(len(reply), 0)

    def test_en_flower_exact(self):
        result = lookup_gift("flowers", lang="en")
        self.assertIsNotNone(result)
        bonus, reply = result
        self.assertGreater(bonus, 0)

    def test_ja_case_insensitive(self):
        result = lookup_gift("チョコ", lang="ja")
        self.assertIsNotNone(result)

    def test_en_case_insensitive(self):
        result = lookup_gift("CHOCOLATE", lang="en")
        self.assertIsNotNone(result)

    def test_unknown_item_returns_none(self):
        self.assertIsNone(lookup_gift("unknown_xyzzy_item", lang="ja"))
        self.assertIsNone(lookup_gift("unknown_xyzzy_item", lang="en"))

    def test_empty_returns_none(self):
        self.assertIsNone(lookup_gift("", lang="ja"))
        self.assertIsNone(lookup_gift("", lang="en"))

    def test_all_ja_aliases_resolve(self):
        from gifts import _GIFTS
        for gift in _GIFTS:
            for alias in gift["ja"]["aliases"]:
                result = lookup_gift(alias, lang="ja")
                self.assertIsNotNone(result, f"ja alias '{alias}' not found")

    def test_all_en_aliases_resolve(self):
        from gifts import _GIFTS
        for gift in _GIFTS:
            for alias in gift["en"]["aliases"]:
                result = lookup_gift(alias, lang="en")
                self.assertIsNotNone(result, f"en alias '{alias}' not found")

    def test_affinity_bonus_positive(self):
        for key in _KNOWN_KEYS:
            from gifts import _GIFTS
            gift = next(g for g in _GIFTS if g["key"] == key)
            self.assertGreater(gift["affinity"], 0, key)

    def test_letter_has_highest_affinity(self):
        from gifts import _GIFTS
        letter_bonus = next(g["affinity"] for g in _GIFTS if g["key"] == "letter")
        for g in _GIFTS:
            if g["key"] != "letter":
                self.assertGreaterEqual(letter_bonus, g["affinity"])

    def test_replies_are_nonempty(self):
        for key in _KNOWN_KEYS:
            result_ja = lookup_gift(key, lang="ja")
            if result_ja:
                _, reply = result_ja
                self.assertGreater(len(reply), 0, f"{key} ja reply empty")


class AllGiftKeysTests(unittest.TestCase):
    def test_returns_all_known_keys(self):
        self.assertEqual(set(all_gift_keys()), _KNOWN_KEYS)

    def test_no_duplicates(self):
        keys = all_gift_keys()
        self.assertEqual(len(keys), len(set(keys)))


class CatalogTextTests(unittest.TestCase):
    def test_ja_catalog_nonempty(self):
        text = gift_catalog_text("ja")
        self.assertIsInstance(text, str)
        self.assertGreater(len(text), 0)

    def test_en_catalog_nonempty(self):
        text = gift_catalog_text("en")
        self.assertIsInstance(text, str)
        self.assertGreater(len(text), 0)

    def test_catalog_shows_bonus(self):
        text = gift_catalog_text("ja")
        self.assertIn("+", text)

    def test_catalog_line_count(self):
        text = gift_catalog_text("ja")
        lines = [l for l in text.splitlines() if l.strip()]
        self.assertEqual(len(lines), len(_KNOWN_KEYS))


class CLIGiftIntegrationTests(unittest.TestCase):
    """Test _give_gift() helper via persona_cli."""

    def setUp(self):
        import persona_cli
        self._pc = persona_cli

    def test_give_flower_increases_affinity(self):
        from mood import MoodTracker
        tracker = MoodTracker(affinity=30.0)
        before = tracker.affinity
        self._pc._give_gift("花", tracker, "TestAvatar", "ja", lambda t: None)
        self.assertGreater(tracker.affinity, before)

    def test_give_unknown_item_no_crash(self):
        logs = []
        self._pc._give_gift("xyz_unknown_item", None, "TestAvatar", "ja", logs.append)
        self.assertTrue(any("xyz_unknown_item" in l or "分からない" in l for l in logs))

    def test_give_list_shows_catalog(self):
        logs = []
        self._pc._give_gift("list", None, "TestAvatar", "ja", logs.append)
        self.assertTrue(any("+" in l for l in logs))

    def test_give_empty_shows_catalog(self):
        logs = []
        self._pc._give_gift("", None, "TestAvatar", "en", logs.append)
        # Should show list or usage
        self.assertTrue(len(logs) > 0)

    def test_give_letter_en_reply(self):
        from mood import MoodTracker
        tracker = MoodTracker(affinity=50.0)
        logs = []
        self._pc._give_gift("letter", tracker, "Avatar", "en", logs.append)
        self.assertTrue(any("TestAvatar" in l or "Avatar" in l or "letter" in l.lower()
                            or "affinity" in l.lower() for l in logs))


class GiftPersistenceTests(unittest.TestCase):
    """_give_gift() must save mood immediately so bonus survives an abrupt exit."""

    def setUp(self):
        import persona_cli
        self._pc = persona_cli

    def test_mood_saved_immediately_after_gift(self):
        """Affinity bonus from /gift is written to disk inside _give_gift()."""
        import json
        import os
        import tempfile
        from mood import MoodTracker

        tmp = tempfile.mkdtemp()
        mood_path = os.path.join(tmp, "mood.json")
        history_path = os.path.join(tmp, "history.json")
        tracker = MoodTracker(affinity=20.0)

        # _give_gift() does `from mood import _default_mood_path` locally, so patch at source
        from unittest import mock
        import mood as _mood_mod
        with mock.patch.object(_mood_mod, "_default_mood_path", lambda: mood_path), \
             mock.patch.object(_mood_mod, "_default_mood_history_path",
                               lambda: history_path):
            self._pc._give_gift("花", tracker, "Avatar", "ja", lambda t: None)

        self.assertTrue(os.path.exists(mood_path),
                        "mood.json must be written immediately after a gift")
        with open(mood_path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertGreater(data["affinity"], 20.0,
                           "Saved affinity should reflect the gift bonus")

        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    def test_mood_save_failure_does_not_crash(self):
        """If mood save throws (disk full, etc.), _give_gift() still completes."""
        from mood import MoodTracker
        tracker = MoodTracker(affinity=30.0)
        logs = []
        from unittest import mock
        import mood as _mood_mod
        with mock.patch.object(_mood_mod, "_default_mood_path",
                               lambda: "/nonexistent/path/mood.json"), \
             mock.patch.object(_mood_mod, "_default_mood_history_path",
                               lambda: "/nonexistent/path/history.json"):
            self._pc._give_gift("花", tracker, "Avatar", "ja", logs.append)

        # Should have printed the reply and the bonus message without crashing
        self.assertTrue(any("花" in l or "+" in l or "Avatar" in l for l in logs))


if __name__ == "__main__":
    unittest.main()
