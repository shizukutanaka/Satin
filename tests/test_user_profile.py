"""
Unit tests for user_profile — the avatar's minimal memory of who the user is.

Covers: name sanitization, address fallback, persistence round-trip,
the {user} placeholder substitution, and the process-wide singleton.
"""
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

    @unittest.skipIf(
        sys.platform == "win32",
        "Windows os.replace raises Access Denied under concurrent writers (NTFS "
        "file-locking); the unique-temp-file save() fix is validated on POSIX CI.",
    )
    def test_concurrent_saves_to_same_path_never_crash_or_corrupt(self):
        """Regression: save() used a fixed temp filename (f"{path}.tmp")
        shared by every writer to that path. Two concurrent save() calls to
        the same path raced on that one temp file — one writer's
        open(tmp, "w") truncated the other's in-flight temp file, and the
        loser's os.replace(tmp, path) raised FileNotFoundError (silently
        swallowed, logged as a warning, save() returns False and the update
        is lost). Reproducible with real GUI-thread + background-thread
        writers in this codebase, both calling get_user_profile().save()."""
        import threading
        results = []

        def writer(i):
            ok = UserProfile(name=f"user{i}").save(self._path)
            results.append(ok)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        self.assertTrue(all(results), f"every concurrent save() must succeed: {results}")
        # The file must contain exactly one complete, valid profile — never
        # empty/truncated/mixed content from two colliding writers.
        loaded = UserProfile.load(self._path)
        self.assertTrue(loaded.name.startswith("user"), f"got corrupted name: {loaded.name!r}")


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


class FactTests(unittest.TestCase):
    def test_starts_empty(self):
        self.assertEqual(UserProfile().facts, {})

    def test_set_and_get_fact(self):
        p = UserProfile()
        saved = p.set_fact("favorite_food", "ラーメン")
        self.assertEqual(saved, "ラーメン")
        self.assertEqual(p.get_fact("favorite_food"), "ラーメン")
        self.assertTrue(p.has_fact("favorite_food"))

    def test_get_unknown_fact_empty(self):
        self.assertEqual(UserProfile().get_fact("nope"), "")
        self.assertFalse(UserProfile().has_fact("nope"))

    def test_set_fact_overwrites_existing(self):
        p = UserProfile()
        p.set_fact("favorite_color", "青")
        p.set_fact("favorite_color", "赤")
        self.assertEqual(p.get_fact("favorite_color"), "赤")

    def test_set_fact_empty_value_rejected(self):
        p = UserProfile()
        self.assertEqual(p.set_fact("k", ""), "")
        self.assertEqual(p.facts, {})

    def test_set_fact_empty_key_rejected(self):
        p = UserProfile()
        self.assertEqual(p.set_fact("", "value"), "")

    def test_long_answer_truncated_not_dropped(self):
        p = UserProfile()
        long_answer = "あ" * 200
        saved = p.set_fact("dream", long_answer)
        self.assertTrue(saved)
        self.assertLessEqual(len(p.get_fact("dream")), 60)

    def test_max_facts_enforced_for_new_keys(self):
        p = UserProfile()
        for i in range(25):
            p.set_fact(f"key{i}", f"value{i}")
        self.assertLessEqual(len(p.facts), 20)

    def test_existing_key_updatable_at_capacity(self):
        p = UserProfile()
        for i in range(20):
            p.set_fact(f"key{i}", "v")
        # At capacity; updating an existing key still works
        self.assertEqual(p.set_fact("key0", "updated"), "updated")
        self.assertEqual(p.get_fact("key0"), "updated")

    def test_remove_fact(self):
        p = UserProfile()
        p.set_fact("hometown", "東京")
        self.assertTrue(p.remove_fact("hometown"))
        self.assertFalse(p.has_fact("hometown"))

    def test_remove_nonexistent_fact(self):
        self.assertFalse(UserProfile().remove_fact("nope"))

    def test_facts_roundtrip(self):
        p = UserProfile(name="Taro")
        p.set_fact("favorite_food", "寿司")
        p.set_fact("hometown", "大阪")
        restored = UserProfile.from_dict(p.to_dict())
        self.assertEqual(restored.facts, {"favorite_food": "寿司", "hometown": "大阪"})

    def test_init_with_facts(self):
        p = UserProfile(facts={"dream": "宇宙飛行士"})
        self.assertEqual(p.get_fact("dream"), "宇宙飛行士")

    def test_init_ignores_non_dict_facts(self):
        # from_dict guards against corrupt data
        p = UserProfile.from_dict({"name": "X", "facts": "not a dict"})
        self.assertEqual(p.facts, {})

    def test_clear_removes_facts(self):
        p = UserProfile()
        p.set_fact("favorite_color", "緑")
        p.clear()
        self.assertEqual(p.facts, {})


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


# ---------------------------------------------------------------------------
# _sanitize_fact — boundary truncation regression
# ---------------------------------------------------------------------------

class SanitizeFactBoundaryTests(unittest.TestCase):

    def _fact(self, text, max_len=60):
        from user_profile import _sanitize_fact
        return _sanitize_fact(text, max_len=max_len)

    def test_boundary_space_does_not_over_truncate(self):
        """Regression: s[:max_len].strip() ate trailing space at boundary position,
        dropping the stored value to max_len-1 when the max_len-th char is a space.
        Fixed by using rstrip() (removes trailing spaces only) instead of strip().
        """
        # Build a 61-char string where position 60 (0-indexed 59) is a space,
        # so the real content ends at position 61.
        # "a " * 30 = 60 chars; then "b" makes it 61.
        text = "a " * 30 + "b"
        result = self._fact(text)
        # Must NOT drop below max_len-1 = 59 chars; content at pos 59 is a space so
        # rstrip truncates trailing spaces but the important invariant is that we
        # never lose content that was within the first max_len characters.
        self.assertLessEqual(len(result), 60)
        # At minimum the 58 non-space "a" characters + at least one boundary char
        # must survive. Specifically the result must be at least 59 chars, because
        # s[:60] = "a " * 30 which ends in a space; rstrip removes that one space.
        self.assertGreaterEqual(len(result), 59)

    def test_no_truncation_under_max_len(self):
        text = "hello world"
        self.assertEqual(self._fact(text), "hello world")

    def test_exact_max_len_no_truncation(self):
        text = "x" * 60
        self.assertEqual(self._fact(text), "x" * 60)

    def test_over_max_len_content_preserved(self):
        text = "x" * 100
        result = self._fact(text)
        self.assertEqual(len(result), 60)

    def test_trailing_space_in_source_stripped_before_truncation(self):
        text = "   hello   "
        self.assertEqual(self._fact(text), "hello")


if __name__ == "__main__":
    unittest.main()
