"""
Unit tests for user_profile — the avatar's minimal memory of who the user is.

Covers: name sanitization, address fallback, persistence round-trip,
the {user} placeholder substitution, and the process-wide singleton.
"""
import json
import os
import sys
import tempfile
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import user_profile  # noqa: E402
from user_profile import UserProfile, personalize  # noqa: E402


class SanitizeTests(unittest.TestCase):
    def test_strips_whitespace(self):
        self.assertEqual(UserProfile(name="  Taro  ").name, "Taro")

    def test_collapses_newlines(self):
        p = UserProfile(name="Ta\nro\r")
        self.assertNotIn("\n", p.name)
        self.assertNotIn("\r", p.name)

    def test_truncates_long_name(self):
        p = UserProfile(name="x" * 100)
        self.assertLessEqual(len(p.name), 40)

    def test_empty_name(self):
        self.assertEqual(UserProfile().name, "")
        self.assertFalse(UserProfile().has_name())


class AddressTests(unittest.TestCase):
    def test_address_uses_name_when_set(self):
        self.assertEqual(UserProfile(name="Taro").address("ja"), "Taro")

    def test_address_fallback_ja(self):
        self.assertEqual(UserProfile().address("ja"), "きみ")

    def test_address_fallback_en(self):
        self.assertEqual(UserProfile().address("en"), "you")


class SetNameTests(unittest.TestCase):
    def test_set_name_returns_sanitized(self):
        p = UserProfile()
        self.assertEqual(p.set_name("  Hana "), "Hana")
        self.assertEqual(p.name, "Hana")

    def test_clear(self):
        p = UserProfile(name="X", note="Y")
        p.clear()
        self.assertEqual(p.name, "")
        self.assertEqual(p.note, "")


class BirthdayTests(unittest.TestCase):
    def test_valid_mm_dd(self):
        self.assertEqual(UserProfile(birthday="06-15").birthday, "06-15")

    def test_single_digits_normalized(self):
        self.assertEqual(UserProfile(birthday="6-5").birthday, "06-05")

    def test_slash_separator_accepted(self):
        self.assertEqual(UserProfile(birthday="12/25").birthday, "12-25")

    def test_leap_day_allowed(self):
        self.assertEqual(UserProfile(birthday="02-29").birthday, "02-29")

    def test_invalid_month_rejected(self):
        self.assertEqual(UserProfile(birthday="13-01").birthday, "")

    def test_invalid_day_rejected(self):
        self.assertEqual(UserProfile(birthday="02-30").birthday, "")

    def test_garbage_rejected(self):
        self.assertEqual(UserProfile(birthday="not a date").birthday, "")

    def test_set_birthday_returns_normalized(self):
        p = UserProfile()
        self.assertEqual(p.set_birthday("6-15"), "06-15")
        self.assertTrue(p.has_birthday())

    def test_changing_birthday_resets_celebrated_marker(self):
        p = UserProfile(birthday="06-15", last_birthday_year=2026)
        p.set_birthday("07-01")
        self.assertEqual(p._last_birthday_year, 0)

    def test_birthday_roundtrips(self):
        import tempfile
        d = tempfile.mkdtemp()
        path = os.path.join(d, "p.json")
        try:
            UserProfile(birthday="06-15", last_birthday_year=2026).save(path)
            loaded = UserProfile.load(path)
            self.assertEqual(loaded.birthday, "06-15")
            self.assertEqual(loaded._last_birthday_year, 2026)
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._path = os.path.join(self._tmp, "user_profile.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_save_and_load_roundtrip(self):
        UserProfile(name="Taro", note="likes cats").save(self._path)
        loaded = UserProfile.load(self._path)
        self.assertEqual(loaded.name, "Taro")
        self.assertEqual(loaded.note, "likes cats")

    def test_load_missing_returns_empty(self):
        loaded = UserProfile.load(os.path.join(self._tmp, "nope.json"))
        self.assertEqual(loaded.name, "")

    def test_load_corrupt_returns_empty(self):
        with open(self._path, "w", encoding="utf-8") as f:
            f.write("{not valid json")
        loaded = UserProfile.load(self._path)
        self.assertEqual(loaded.name, "")

    def test_saved_file_is_owner_only(self):
        UserProfile(name="Secret").save(self._path)
        if os.name != "nt":
            mode = os.stat(self._path).st_mode & 0o777
            self.assertEqual(mode, 0o600)


class PersonalizeTests(unittest.TestCase):
    def test_replaces_placeholder_with_name(self):
        p = UserProfile(name="Taro")
        self.assertEqual(personalize("Hi {user}!", p, "en"), "Hi Taro!")

    def test_fallback_when_no_name_ja(self):
        self.assertEqual(personalize("やあ{user}", UserProfile(), "ja"), "やあきみ")

    def test_fallback_when_profile_none(self):
        self.assertEqual(personalize("Hi {user}", None, "en"), "Hi you")

    def test_no_placeholder_unchanged(self):
        self.assertEqual(personalize("Hello there", UserProfile(name="X"), "en"),
                         "Hello there")

    def test_empty_text(self):
        self.assertEqual(personalize("", UserProfile(name="X"), "en"), "")


class InterestTests(unittest.TestCase):
    def test_starts_empty(self):
        self.assertEqual(UserProfile().interests, [])

    def test_has_interests_false_when_empty(self):
        self.assertFalse(UserProfile().has_interests())

    def test_add_interest_stores_it(self):
        p = UserProfile()
        result = p.add_interest("アニメ")
        self.assertEqual(result, "アニメ")
        self.assertIn("アニメ", p.interests)
        self.assertTrue(p.has_interests())

    def test_add_interest_no_duplicates(self):
        p = UserProfile()
        p.add_interest("音楽")
        p.add_interest("音楽")
        self.assertEqual(p.interests.count("音楽"), 1)

    def test_add_interest_trims_whitespace(self):
        p = UserProfile()
        p.add_interest("  ゲーム  ")
        self.assertIn("ゲーム", p.interests)

    def test_add_interest_empty_returns_empty(self):
        p = UserProfile()
        self.assertEqual(p.add_interest(""), "")
        self.assertEqual(p.interests, [])

    def test_add_interest_too_long_rejected(self):
        p = UserProfile()
        result = p.add_interest("x" * 100)
        self.assertEqual(result, "")

    def test_add_interest_max_10(self):
        p = UserProfile()
        for i in range(12):
            p.add_interest(f"thing{i}")
        self.assertLessEqual(len(p.interests), 10)

    def test_remove_interest(self):
        p = UserProfile(interests=["アニメ", "音楽"])
        removed = p.remove_interest("アニメ")
        self.assertTrue(removed)
        self.assertNotIn("アニメ", p.interests)

    def test_remove_nonexistent_returns_false(self):
        p = UserProfile()
        self.assertFalse(p.remove_interest("xyz"))

    def test_interests_roundtrip(self):
        import tempfile, os, shutil
        d = tempfile.mkdtemp()
        path = os.path.join(d, "p.json")
        try:
            UserProfile(interests=["アニメ", "ゲーム"]).save(path)
            loaded = UserProfile.load(path)
            self.assertEqual(loaded.interests, ["アニメ", "ゲーム"])
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_clear_removes_interests(self):
        p = UserProfile(interests=["アニメ"])
        p.clear()
        self.assertEqual(p.interests, [])

    def test_init_with_interests(self):
        p = UserProfile(interests=["読書", "映画"])
        self.assertEqual(p.interests, ["読書", "映画"])

    def test_init_deduplicates(self):
        p = UserProfile(interests=["音楽", "音楽"])
        self.assertEqual(p.interests.count("音楽"), 1)


class SingletonTests(unittest.TestCase):
    def setUp(self):
        user_profile.reset_user_profile()

    def tearDown(self):
        user_profile.reset_user_profile()

    def test_singleton_is_shared(self):
        a = user_profile.get_user_profile()
        b = user_profile.get_user_profile()
        self.assertIs(a, b)

    def test_reset_creates_new_instance(self):
        a = user_profile.get_user_profile()
        user_profile.reset_user_profile()
        b = user_profile.get_user_profile()
        self.assertIsNot(a, b)


if __name__ == "__main__":
    unittest.main()
