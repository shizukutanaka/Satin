"""
Unit tests for special_days — birthday and seasonal-event greetings.

Dating-sim inspired: the avatar celebrates the user's birthday (once a year,
with an affinity bonus) and recognises calendar events (New Year, Valentine's,
Christmas...). Dates are injectable so tests are deterministic.
"""
import datetime
import os
import sys
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import special_days  # noqa: E402
from special_days import seasonal_greeting, birthday_greeting, BIRTHDAY_AFFINITY_BONUS  # noqa: E402
from user_profile import UserProfile  # noqa: E402


class SeasonalGreetingTests(unittest.TestCase):
    def test_christmas_ja(self):
        msg = seasonal_greeting("ja", datetime.date(2026, 12, 25))
        self.assertIn("クリスマス", msg)

    def test_christmas_en(self):
        msg = seasonal_greeting("en", datetime.date(2026, 12, 25))
        self.assertIn("Christmas", msg)

    def test_new_year_ja(self):
        self.assertIn("あけまして", seasonal_greeting("ja", datetime.date(2027, 1, 1)))

    def test_valentine(self):
        self.assertTrue(seasonal_greeting("en", datetime.date(2026, 2, 14)))

    def test_ordinary_day_returns_empty(self):
        self.assertEqual(seasonal_greeting("ja", datetime.date(2026, 6, 15)), "")

    def test_is_stateless_repeatable(self):
        d = datetime.date(2026, 12, 25)
        a = seasonal_greeting("ja", d)
        b = seasonal_greeting("ja", d)
        self.assertEqual(a, b)
        self.assertTrue(a)


class BirthdayGreetingTests(unittest.TestCase):
    def test_no_profile(self):
        self.assertEqual(birthday_greeting(None, "ja", datetime.date(2026, 6, 15)), "")

    def test_no_birthday_set(self):
        p = UserProfile(name="Taro")
        self.assertEqual(birthday_greeting(p, "ja", datetime.date(2026, 6, 15)), "")

    def test_not_birthday_today(self):
        p = UserProfile(birthday="06-15")
        self.assertEqual(birthday_greeting(p, "ja", datetime.date(2026, 1, 1)), "")

    def test_birthday_today_ja(self):
        p = UserProfile(name="たろう", birthday="06-15")
        msg = birthday_greeting(p, "ja", datetime.date(2026, 6, 15))
        self.assertIn("誕生日", msg)
        self.assertIn("たろう", msg)

    def test_birthday_today_en(self):
        p = UserProfile(name="Taro", birthday="06-15")
        msg = birthday_greeting(p, "en", datetime.date(2026, 6, 15))
        self.assertIn("birthday", msg.lower())
        self.assertIn("Taro", msg)

    def test_birthday_without_name(self):
        p = UserProfile(birthday="06-15")
        msg = birthday_greeting(p, "ja", datetime.date(2026, 6, 15))
        self.assertIn("誕生日", msg)

    def test_celebrated_only_once_per_year(self):
        p = UserProfile(birthday="06-15")
        first = birthday_greeting(p, "ja", datetime.date(2026, 6, 15))
        self.assertTrue(first)
        second = birthday_greeting(p, "ja", datetime.date(2026, 6, 15))
        self.assertEqual(second, "")

    def test_celebrated_again_next_year(self):
        p = UserProfile(birthday="06-15")
        birthday_greeting(p, "ja", datetime.date(2026, 6, 15))
        nxt = birthday_greeting(p, "ja", datetime.date(2027, 6, 15))
        self.assertTrue(nxt)

    def test_marker_records_year(self):
        p = UserProfile(birthday="06-15")
        birthday_greeting(p, "ja", datetime.date(2026, 6, 15))
        self.assertEqual(p._last_birthday_year, 2026)

    def test_bonus_constant_positive(self):
        self.assertGreater(BIRTHDAY_AFFINITY_BONUS, 0)


if __name__ == "__main__":
    unittest.main()
