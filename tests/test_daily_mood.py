"""
Unit tests for daily_mood — date-seeded character temperament.

Covers: determinism, valid keys, label/description/emoji accessors,
language fallback (en/ja), and distribution sanity.
"""
import os
import sys
import unittest
from datetime import date

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from daily_mood import (  # noqa: E402
    all_mood_keys,
    get_daily_mood,
    mood_description,
    mood_emoji,
    mood_label,
)

_KNOWN_KEYS = {"energetic", "cheerful", "calm", "thoughtful", "melancholy", "mischievous"}


class DeterminismTests(unittest.TestCase):
    def test_same_date_same_result(self):
        d = date(2026, 1, 1)
        self.assertEqual(get_daily_mood(d), get_daily_mood(d))

    def test_same_date_same_salt_same_result(self):
        d = date(2026, 6, 15)
        self.assertEqual(get_daily_mood(d, "Alice"), get_daily_mood(d, "Alice"))

    def test_different_dates_may_differ(self):
        results = {get_daily_mood(date(2026, 1, i)) for i in range(1, 8)}
        self.assertGreater(len(results), 1)

    def test_different_salts_may_differ(self):
        d = date(2026, 6, 1)
        results = {get_daily_mood(d, str(i)) for i in range(20)}
        self.assertGreater(len(results), 1)

    def test_no_date_uses_today(self):
        result = get_daily_mood()
        self.assertIn(result, _KNOWN_KEYS)


class ValidKeyTests(unittest.TestCase):
    def test_result_is_known_key(self):
        for day in range(1, 32):
            try:
                d = date(2026, 1, day)
            except ValueError:
                continue
            self.assertIn(get_daily_mood(d), _KNOWN_KEYS, f"day={day}")

    def test_all_mood_keys_complete(self):
        keys = set(all_mood_keys())
        self.assertEqual(keys, _KNOWN_KEYS)


class LabelTests(unittest.TestCase):
    def test_ja_label_nonempty(self):
        for key in _KNOWN_KEYS:
            self.assertGreater(len(mood_label(key, "ja")), 0, key)

    def test_en_label_nonempty(self):
        for key in _KNOWN_KEYS:
            self.assertGreater(len(mood_label(key, "en")), 0, key)

    def test_en_prefix_triggers_english(self):
        label_en = mood_label("energetic", "en")
        label_ja = mood_label("energetic", "ja")
        self.assertNotEqual(label_en, label_ja)

    def test_en_us_falls_back_to_english(self):
        self.assertEqual(mood_label("cheerful", "en-US"), mood_label("cheerful", "en"))

    def test_unknown_key_returns_key_itself(self):
        self.assertEqual(mood_label("nonexistent"), "nonexistent")


class DescriptionTests(unittest.TestCase):
    def test_ja_description_nonempty(self):
        for key in _KNOWN_KEYS:
            self.assertGreater(len(mood_description(key, "ja")), 0, key)

    def test_en_description_nonempty(self):
        for key in _KNOWN_KEYS:
            self.assertGreater(len(mood_description(key, "en")), 0, key)

    def test_unknown_key_returns_empty(self):
        self.assertEqual(mood_description("nope"), "")

    def test_descriptions_differ_across_moods(self):
        descs = {mood_description(k, "ja") for k in _KNOWN_KEYS}
        self.assertEqual(len(descs), len(_KNOWN_KEYS))


class EmojiTests(unittest.TestCase):
    def test_all_keys_have_emoji(self):
        for key in _KNOWN_KEYS:
            self.assertGreater(len(mood_emoji(key)), 0, key)

    def test_unknown_key_returns_empty(self):
        self.assertEqual(mood_emoji("phantom"), "")

    def test_emojis_differ_across_moods(self):
        emojis = {mood_emoji(k) for k in _KNOWN_KEYS}
        self.assertEqual(len(emojis), len(_KNOWN_KEYS))


class DistributionTests(unittest.TestCase):
    """All 6 moods should appear across a reasonable date range."""

    def test_all_moods_appear_in_100_days(self):
        from datetime import timedelta
        start = date(2026, 1, 1)
        seen = set()
        for i in range(100):
            seen.add(get_daily_mood(start + timedelta(days=i)))
        self.assertEqual(seen, _KNOWN_KEYS)


if __name__ == "__main__":
    unittest.main()
