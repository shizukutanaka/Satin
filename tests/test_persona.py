"""
Unit tests for persona.Persona — the configurable dialogue/persona system.

Covers:
- Default persona works without any config file
- Loading from a JSON dict (name, dialogue, default_lang)
- Language fallback chain (requested -> default_lang -> en -> any)
- Region code fallback (en-US -> en)
- Time-of-day greetings (morning/afternoon/evening/night)
- No-immediate-repeat selection
- Corrupt/missing config falls back to defaults without raising
- Singleton get_persona / reset_persona
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import persona as _persona  # noqa: E402
from persona import Persona, get_persona, reset_persona  # noqa: E402


class DefaultPersonaTests(unittest.TestCase):
    def test_default_has_name(self):
        p = Persona()
        self.assertEqual(p.name, "Satin")

    def test_talk_returns_nonempty_string(self):
        p = Persona()
        self.assertTrue(p.talk())
        self.assertIsInstance(p.talk(), str)

    def test_rest_returns_nonempty_string(self):
        p = Persona()
        self.assertTrue(p.rest())

    def test_greeting_returns_nonempty_string(self):
        p = Persona()
        self.assertTrue(p.greeting())


class FromDictTests(unittest.TestCase):
    def test_custom_name_and_lines(self):
        data = {
            "name": "Mimi",
            "default_lang": "en",
            "dialogue": {"en": {"talk": ["Hi there"], "rest": ["Resting"]}},
        }
        p = Persona.from_dict(data)
        self.assertEqual(p.name, "Mimi")
        self.assertEqual(p.talk(), "Hi there")
        self.assertEqual(p.rest(), "Resting")

    def test_empty_dict_falls_back_to_defaults(self):
        p = Persona.from_dict({})
        self.assertEqual(p.name, "Satin")
        self.assertTrue(p.talk())

    def test_non_dict_input_is_safe(self):
        p = Persona.from_dict(None)  # type: ignore[arg-type]
        self.assertTrue(p.talk())


class LanguageFallbackTests(unittest.TestCase):
    def test_requested_lang_used(self):
        data = {"dialogue": {
            "ja": {"talk": ["こんにちは"]},
            "en": {"talk": ["Hello"]},
        }}
        p = Persona.from_dict(data, lang="en")
        self.assertEqual(p.talk(), "Hello")

    def test_missing_lang_falls_back_to_default_lang(self):
        data = {"default_lang": "ja", "dialogue": {"ja": {"talk": ["こんにちは"]}}}
        p = Persona.from_dict(data, lang="fr")  # fr not present
        self.assertEqual(p.talk(), "こんにちは")

    def test_region_code_falls_back_to_base_lang(self):
        data = {"dialogue": {"en": {"talk": ["Hello"]}}}
        p = Persona.from_dict(data, lang="en-US")
        self.assertEqual(p.talk(), "Hello")

    def test_per_call_lang_override(self):
        data = {"dialogue": {
            "ja": {"talk": ["こんにちは"]},
            "en": {"talk": ["Hello"]},
        }}
        p = Persona.from_dict(data, lang="ja")
        self.assertEqual(p.talk(lang="en"), "Hello")


class GreetingTimeTests(unittest.TestCase):
    def _persona(self):
        data = {"dialogue": {"en": {"greeting": {
            "morning": ["GM"], "afternoon": ["GA"],
            "evening": ["GE"], "night": ["GN"],
        }}}}
        return Persona.from_dict(data, lang="en")

    def test_morning(self):
        self.assertEqual(self._persona().greeting(now=datetime(2024, 1, 1, 8, 0)), "GM")

    def test_afternoon(self):
        self.assertEqual(self._persona().greeting(now=datetime(2024, 1, 1, 13, 0)), "GA")

    def test_evening(self):
        self.assertEqual(self._persona().greeting(now=datetime(2024, 1, 1, 19, 0)), "GE")

    def test_night(self):
        self.assertEqual(self._persona().greeting(now=datetime(2024, 1, 1, 23, 0)), "GN")
        self.assertEqual(self._persona().greeting(now=datetime(2024, 1, 1, 3, 0)), "GN")

    def test_greeting_falls_back_to_talk_when_absent(self):
        data = {"dialogue": {"en": {"talk": ["Hello"]}}}  # no greeting block
        p = Persona.from_dict(data, lang="en")
        self.assertEqual(p.greeting(), "Hello")


class NoRepeatTests(unittest.TestCase):
    def test_two_options_never_repeat_consecutively(self):
        data = {"dialogue": {"en": {"talk": ["A", "B"]}}}
        p = Persona.from_dict(data, lang="en")
        prev = p.talk()
        for _ in range(50):
            cur = p.talk()
            self.assertNotEqual(cur, prev)
            prev = cur

    def test_single_option_always_returns_it(self):
        data = {"dialogue": {"en": {"talk": ["only"]}}}
        p = Persona.from_dict(data, lang="en")
        for _ in range(5):
            self.assertEqual(p.talk(), "only")


class LoadFromFileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        reset_persona()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)
        reset_persona()

    def test_load_valid_file(self):
        path = os.path.join(self._tmp, "persona.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"name": "Loaded", "dialogue": {"en": {"talk": ["x"]}}}, f)
        p = Persona.load(config_path=path, lang="en")
        self.assertEqual(p.name, "Loaded")
        self.assertEqual(p.talk(), "x")

    def test_load_missing_file_returns_default(self):
        p = Persona.load(config_path=os.path.join(self._tmp, "nope.json"))
        self.assertEqual(p.name, "Satin")

    def test_load_corrupt_file_returns_default(self):
        path = os.path.join(self._tmp, "bad.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{ this is not valid json ")
        p = Persona.load(config_path=path)
        self.assertEqual(p.name, "Satin")
        self.assertTrue(p.talk())

    def test_bundled_default_config_loads(self):
        """The shipped config/persona.json must parse and expose lines."""
        repo_cfg = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config", "persona.json",
        )
        self.assertTrue(os.path.exists(repo_cfg), "config/persona.json should ship")
        p = Persona.load(config_path=repo_cfg, lang="ja")
        self.assertTrue(p.talk())
        self.assertTrue(p.greeting())
        # The shipped config ships response rules: a known keyword must reply.
        self.assertTrue(p.respond("こんにちは"))


class RespondTests(unittest.TestCase):
    """Rule-based respond() — keyword match, fallback, empty input, lang fallback."""

    def _persona(self, lang="en"):
        data = {
            "default_lang": "en",
            "responses": {
                "en": {
                    "rules": [
                        {"keywords": ["hello", "hi there"], "replies": ["HELLO_A", "HELLO_B"]},
                        {"keywords": ["thank"], "replies": ["THANKS"]},
                    ],
                    "fallback": ["FB_A", "FB_B"],
                },
            },
        }
        return Persona.from_dict(data, lang=lang)

    def test_keyword_match_returns_rule_reply(self):
        p = self._persona()
        self.assertIn(p.respond("hello"), {"HELLO_A", "HELLO_B"})

    def test_match_is_case_insensitive_substring(self):
        p = self._persona()
        self.assertIn(p.respond("Oh HELLO there, friend"), {"HELLO_A", "HELLO_B"})

    def test_first_matching_rule_wins(self):
        p = self._persona()
        # "thank" rule has a single deterministic reply
        self.assertEqual(p.respond("thank you so much"), "THANKS")

    def test_no_match_returns_fallback(self):
        p = self._persona()
        self.assertIn(p.respond("quantum chromodynamics"), {"FB_A", "FB_B"})

    def test_empty_input_returns_empty(self):
        p = self._persona()
        self.assertEqual(p.respond(""), "")
        self.assertEqual(p.respond("   "), "")

    def test_none_input_returns_empty(self):
        p = self._persona()
        self.assertEqual(p.respond(None), "")  # type: ignore[arg-type]

    def test_language_fallback_to_en(self):
        p = self._persona(lang="fr")  # fr has no responses → falls back to en
        self.assertIn(p.respond("hello"), {"HELLO_A", "HELLO_B"})

    def test_region_code_falls_back_to_base_lang(self):
        p = self._persona(lang="en-US")
        self.assertIn(p.respond("hello"), {"HELLO_A", "HELLO_B"})

    def test_no_immediate_repeat_in_rule_pool(self):
        p = self._persona()
        prev = p.respond("hello")
        for _ in range(40):
            cur = p.respond("hello")
            self.assertNotEqual(cur, prev)
            prev = cur

    def test_no_immediate_repeat_in_fallback_pool(self):
        p = self._persona()
        prev = p.respond("xyzzy")
        for _ in range(40):
            cur = p.respond("plover")  # both miss → fallback pool
            self.assertNotEqual(cur, prev)
            prev = cur

    def test_default_persona_responds_without_config(self):
        """Persona() with no config still replies (built-in _DEFAULT_RESPONSES)."""
        p = Persona(lang="en")
        self.assertTrue(p.respond("hello"))      # keyword path
        self.assertTrue(p.respond("blahblah"))   # fallback path

    def test_empty_fallback_returns_empty_on_no_match(self):
        data = {"responses": {"en": {"rules": [
            {"keywords": ["hi"], "replies": ["HI"]}], "fallback": []}}}
        p = Persona.from_dict(data, lang="en")
        self.assertEqual(p.respond("no keywords here"), "")


class SingletonTests(unittest.TestCase):
    def tearDown(self):
        reset_persona()

    def test_get_persona_returns_same_instance(self):
        reset_persona()
        a = get_persona()
        b = get_persona()
        self.assertIs(a, b)

    def test_reset_creates_new_instance(self):
        a = get_persona()
        reset_persona()
        b = get_persona()
        self.assertIsNot(a, b)


if __name__ == "__main__":
    unittest.main()
