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


class LevelGatingTests(unittest.TestCase):
    """lookup_gift() returns (0.0, decline_msg) when level < min_level."""

    def test_music_declined_for_distant(self):
        result = lookup_gift("音楽", lang="ja", level="distant")
        self.assertIsNotNone(result)
        bonus, reply = result
        self.assertEqual(bonus, 0.0)
        self.assertGreater(len(reply), 0)

    def test_music_declined_for_reserved(self):
        result = lookup_gift("music", lang="en", level="reserved")
        self.assertIsNotNone(result)
        bonus, reply = result
        self.assertEqual(bonus, 0.0)
        self.assertGreater(len(reply), 0)

    def test_music_accepted_at_neutral(self):
        result = lookup_gift("音楽", lang="ja", level="neutral")
        self.assertIsNotNone(result)
        bonus, _ = result
        self.assertGreater(bonus, 0.0)

    def test_music_accepted_at_close(self):
        result = lookup_gift("music", lang="en", level="close")
        self.assertIsNotNone(result)
        bonus, _ = result
        self.assertGreater(bonus, 0.0)

    def test_ribbon_declined_for_distant(self):
        result = lookup_gift("リボン", lang="ja", level="distant")
        self.assertIsNotNone(result)
        bonus, _ = result
        self.assertEqual(bonus, 0.0)

    def test_ribbon_accepted_at_neutral(self):
        result = lookup_gift("ribbon", lang="en", level="neutral")
        self.assertIsNotNone(result)
        bonus, _ = result
        self.assertGreater(bonus, 0.0)

    def test_letter_declined_for_neutral(self):
        result = lookup_gift("手紙", lang="ja", level="neutral")
        self.assertIsNotNone(result)
        bonus, reply = result
        self.assertEqual(bonus, 0.0)
        self.assertGreater(len(reply), 0)

    def test_letter_declined_en_for_reserved(self):
        result = lookup_gift("letter", lang="en", level="reserved")
        self.assertIsNotNone(result)
        bonus, reply = result
        self.assertEqual(bonus, 0.0)

    def test_letter_accepted_at_friendly(self):
        result = lookup_gift("手紙", lang="ja", level="friendly")
        self.assertIsNotNone(result)
        bonus, _ = result
        self.assertGreater(bonus, 0.0)

    def test_letter_accepted_at_close(self):
        result = lookup_gift("letter", lang="en", level="close")
        self.assertIsNotNone(result)
        bonus, _ = result
        self.assertGreater(bonus, 0.0)

    def test_no_level_arg_bypasses_gate(self):
        """Callers that don't pass level still get the bonus (backward compat)."""
        result = lookup_gift("手紙", lang="ja")
        self.assertIsNotNone(result)
        bonus, _ = result
        self.assertGreater(bonus, 0.0)

    def test_flowers_always_accepted(self):
        """Items without min_level are always accepted regardless of level."""
        for lvl in ("distant", "reserved", "neutral", "friendly", "close"):
            result = lookup_gift("花", lang="ja", level=lvl)
            self.assertIsNotNone(result)
            bonus, _ = result
            self.assertGreater(bonus, 0.0, f"flowers should be accepted at level={lvl}")

    def test_decline_message_nonempty_ja(self):
        result = lookup_gift("手紙", lang="ja", level="distant")
        self.assertIsNotNone(result)
        _, msg = result
        self.assertGreater(len(msg.strip()), 0)

    def test_decline_message_nonempty_en(self):
        result = lookup_gift("letter", lang="en", level="distant")
        self.assertIsNotNone(result)
        _, msg = result
        self.assertGreater(len(msg.strip()), 0)


class CLILevelGatingIntegrationTests(unittest.TestCase):
    """_give_gift() must respect level-gating and not apply bonus on decline."""

    def setUp(self):
        import persona_cli
        self._pc = persona_cli

    def test_music_declined_at_reserved_no_bonus(self):
        from mood import MoodTracker
        tracker = MoodTracker(affinity=10.0)  # reserved level
        before = tracker.affinity
        logs = []
        self._pc._give_gift("音楽", tracker, "Avatar", "ja", logs.append)
        self.assertEqual(tracker.affinity, before, "Affinity must not change on decline")

    def test_music_declined_shows_decline_message(self):
        from mood import MoodTracker
        tracker = MoodTracker(affinity=10.0)
        logs = []
        self._pc._give_gift("音楽", tracker, "Avatar", "ja", logs.append)
        full_output = " ".join(logs)
        self.assertGreater(len(full_output), 0)
        # Should show the decline text, not a bonus line
        self.assertNotIn("+", full_output)

    def test_letter_accepted_at_friendly(self):
        from mood import MoodTracker
        tracker = MoodTracker(affinity=60.0)  # friendly level
        before = tracker.affinity
        self._pc._give_gift("手紙", tracker, "Avatar", "ja", lambda t: None)
        self.assertGreater(tracker.affinity, before)

    def test_no_mood_no_level_check(self):
        """Without a mood tracker, level gating is bypassed (level=None)."""
        logs = []
        self._pc._give_gift("音楽", None, "Avatar", "ja", logs.append)
        # With no level, should get a reply (not the decline) — but won't crash either way
        self.assertTrue(len(logs) > 0)


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


class GiftCooldownTests(unittest.TestCase):
    """MoodTracker gift_received_today / record_gift, and _give_gift() cooldown enforcement."""

    def test_gift_received_today_false_initially(self):
        from mood import MoodTracker
        tracker = MoodTracker()
        self.assertFalse(tracker.gift_received_today("flowers"))

    def test_record_gift_marks_as_received(self):
        from mood import MoodTracker
        tracker = MoodTracker()
        tracker.record_gift("flowers")
        self.assertTrue(tracker.gift_received_today("flowers"))

    def test_different_gift_not_marked(self):
        from mood import MoodTracker
        tracker = MoodTracker()
        tracker.record_gift("flowers")
        self.assertFalse(tracker.gift_received_today("chocolate"))

    def test_gift_history_persists_in_to_dict(self):
        from mood import MoodTracker
        tracker = MoodTracker()
        tracker.record_gift("cake")
        d = tracker.to_dict()
        self.assertIn("gift_history", d)
        import datetime
        self.assertEqual(d["gift_history"]["cake"], datetime.date.today().isoformat())

    def test_gift_history_loads_from_dict(self):
        from mood import MoodTracker
        import datetime
        today = datetime.date.today().isoformat()
        tracker = MoodTracker.from_dict({"gift_history": {"flowers": today}})
        self.assertTrue(tracker.gift_received_today("flowers"))

    def test_old_date_in_history_is_not_today(self):
        from mood import MoodTracker
        tracker = MoodTracker.from_dict({"gift_history": {"flowers": "2000-01-01"}})
        self.assertFalse(tracker.gift_received_today("flowers"))

    def test_give_gift_cooldown_blocks_second_gift(self):
        """Giving the same gift twice in one session should block the second."""
        import persona_cli
        from mood import MoodTracker
        from unittest import mock
        import mood as _mood_mod
        tracker = MoodTracker(affinity=50.0)
        logs1 = []
        logs2 = []
        with mock.patch.object(_mood_mod, "_default_mood_path", lambda: "/dev/null"), \
             mock.patch.object(_mood_mod, "_default_mood_history_path", lambda: "/dev/null"):
            # First gift should succeed
            try:
                persona_cli._give_gift("花", tracker, "Avatar", "ja", logs1.append)
            except Exception:
                pass
            # Second gift of the same item should be blocked by cooldown
            persona_cli._give_gift("花", tracker, "Avatar", "ja", logs2.append)

        # If cooldown fired, the second output should NOT include "+" bonus
        # but SHOULD include some message from the avatar
        self.assertTrue(len(logs2) > 0)
        second_output = " ".join(logs2)
        self.assertNotIn("+", second_output, "Cooldown should prevent bonus on repeat gift")

    def test_lookup_gift_key_returns_canonical_key(self):
        from gifts import lookup_gift_key
        self.assertEqual(lookup_gift_key("花", lang="ja"), "flowers")
        self.assertEqual(lookup_gift_key("flowers", lang="en"), "flowers")
        self.assertEqual(lookup_gift_key("チョコ", lang="ja"), "chocolate")

    def test_lookup_gift_key_unknown_returns_none(self):
        from gifts import lookup_gift_key
        self.assertIsNone(lookup_gift_key("xyz_unknown_xyzzy", lang="ja"))

    def test_cooldown_message_nonempty(self):
        from gifts import cooldown_message
        self.assertGreater(len(cooldown_message("ja")), 0)
        self.assertGreater(len(cooldown_message("en")), 0)


class GiftDailyMoodMultiplierTests(unittest.TestCase):
    """Gift bonus is multiplied by the daily mood affinity multiplier."""

    def setUp(self):
        import persona_cli
        self._pc = persona_cli

    def test_energetic_mood_amplifies_gift_bonus(self):
        """energetic mood (1.2x multiplier) makes the flower bonus larger."""
        from mood import MoodTracker
        from unittest import mock
        import mood as _mood_mod

        tracker = MoodTracker(affinity=50.0)
        before = tracker.affinity

        with mock.patch.object(_mood_mod, "_default_mood_path", lambda: "/dev/null"), \
             mock.patch.object(_mood_mod, "_default_mood_history_path", lambda: "/dev/null"), \
             mock.patch.object(self._pc, "_get_daily_mood", lambda: "energetic"):
            self._pc._give_gift("花", tracker, "Avatar", "ja", lambda t: None)

        # energetic multiplier is 1.2x, flower base bonus is 5.0 → 6.0
        self.assertGreater(tracker.affinity - before, 5.0)

    def test_melancholy_mood_reduces_gift_bonus(self):
        """melancholy mood (< 1.0x multiplier) reduces the gift bonus."""
        from mood import MoodTracker
        from unittest import mock
        import mood as _mood_mod

        tracker = MoodTracker(affinity=50.0)
        before = tracker.affinity

        with mock.patch.object(_mood_mod, "_default_mood_path", lambda: "/dev/null"), \
             mock.patch.object(_mood_mod, "_default_mood_history_path", lambda: "/dev/null"), \
             mock.patch.object(self._pc, "_get_daily_mood", lambda: "melancholy"):
            self._pc._give_gift("花", tracker, "Avatar", "ja", lambda t: None)

        # melancholy multiplier < 1.0, flower base is 5.0 → less than 5.0
        self.assertLess(tracker.affinity - before, 5.0)
        # But still positive
        self.assertGreater(tracker.affinity - before, 0.0)

    def test_calm_mood_no_change_in_bonus(self):
        """calm mood (1.0x multiplier) leaves the gift bonus unchanged."""
        from mood import MoodTracker
        from unittest import mock
        import mood as _mood_mod

        tracker = MoodTracker(affinity=50.0)
        before = tracker.affinity

        with mock.patch.object(_mood_mod, "_default_mood_path", lambda: "/dev/null"), \
             mock.patch.object(_mood_mod, "_default_mood_history_path", lambda: "/dev/null"), \
             mock.patch.object(self._pc, "_get_daily_mood", lambda: "calm"):
            self._pc._give_gift("花", tracker, "Avatar", "ja", lambda t: None)

        actual_bonus = tracker.affinity - before
        self.assertAlmostEqual(actual_bonus, 5.0, places=1)


if __name__ == "__main__":
    unittest.main()
