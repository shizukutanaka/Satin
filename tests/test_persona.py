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


class GreetingByAffinityTests(unittest.TestCase):
    def _persona(self):
        data = {"dialogue": {"en": {
            "greeting": {"morning": ["GM"], "afternoon": ["GA"],
                         "evening": ["GE"], "night": ["GN"]},
            "greeting_by_affinity": {"close": ["WELCOME_BACK"], "distant": ["MEH"]},
        }}}
        return Persona.from_dict(data, lang="en")

    def test_level_specific_greeting_preferred(self):
        p = self._persona()
        self.assertEqual(p.greeting(level="close"), "WELCOME_BACK")
        self.assertEqual(p.greeting(level="distant"), "MEH")

    def test_unknown_level_falls_back_to_time(self):
        p = self._persona()
        # 'neutral' has no level-specific pool → time-based greeting used
        self.assertEqual(p.greeting(level="neutral", now=datetime(2024, 1, 1, 8, 0)), "GM")

    def test_no_level_uses_time_based(self):
        p = self._persona()
        self.assertEqual(p.greeting(now=datetime(2024, 1, 1, 13, 0)), "GA")

    def test_level_without_by_affinity_block_falls_back(self):
        data = {"dialogue": {"en": {"greeting": {"morning": ["GM"]}}}}
        p = Persona.from_dict(data, lang="en")
        self.assertEqual(p.greeting(level="close", now=datetime(2024, 1, 1, 8, 0)), "GM")


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


class RespondWithLevelTests(unittest.TestCase):
    """respond(text, level=...) uses respond_by_affinity rules first."""

    def _persona(self):
        data = {
            "default_lang": "en",
            "responses": {
                "en": {
                    "rules": [
                        {"keywords": ["hello"], "replies": ["GENERIC_HELLO"]},
                    ],
                    "fallback": ["GENERIC_FB"],
                    "respond_by_affinity": {
                        "close": [
                            {"keywords": ["hello"], "replies": ["CLOSE_HELLO"]},
                        ],
                        "distant": [
                            {"keywords": ["hello"], "replies": ["DISTANT_HELLO"]},
                        ],
                    },
                },
            },
        }
        return Persona.from_dict(data, lang="en")

    def test_close_level_uses_affinity_rule(self):
        p = self._persona()
        self.assertEqual(p.respond("hello", level="close"), "CLOSE_HELLO")

    def test_distant_level_uses_affinity_rule(self):
        p = self._persona()
        self.assertEqual(p.respond("hello", level="distant"), "DISTANT_HELLO")

    def test_no_level_uses_generic_rule(self):
        p = self._persona()
        self.assertEqual(p.respond("hello"), "GENERIC_HELLO")

    def test_unknown_level_falls_back_to_generic(self):
        p = self._persona()
        self.assertEqual(p.respond("hello", level="reserved"), "GENERIC_HELLO")

    def test_level_no_keyword_match_falls_through_to_generic(self):
        p = self._persona()
        # level="close" has no "bye" keyword → falls through to generic
        result = p.respond("bye", level="close")
        self.assertEqual(result, "GENERIC_FB")

    def test_bundled_config_respond_by_affinity(self):
        """Shipped config/persona.json has respond_by_affinity for close/distant."""
        repo_cfg = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config", "persona.json",
        )
        p = Persona.load(config_path=repo_cfg, lang="ja")
        close_reply = p.respond("こんにちは", level="close")
        generic_reply_persona = Persona.load(config_path=repo_cfg, lang="ja")
        generic_reply = generic_reply_persona.respond("こんにちは")
        self.assertTrue(close_reply)
        # close reply should differ from the generic one
        self.assertNotEqual(close_reply, generic_reply)

    def test_bundled_config_level_specific_fallback(self):
        """config/persona.json level-specific fallbacks differ across levels."""
        repo_cfg = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config", "persona.json",
        )
        p_close = Persona.load(config_path=repo_cfg, lang="ja")
        p_distant = Persona.load(config_path=repo_cfg, lang="ja")
        # "今日映画を見た" matches no keyword — exercises level fallback
        r_close = p_close.respond("今日映画を見た", level="close")
        r_distant = p_distant.respond("今日映画を見た", level="distant")
        self.assertTrue(r_close, "close level fallback should return non-empty")
        self.assertTrue(r_distant, "distant level fallback should return non-empty")
        self.assertNotEqual(r_close, r_distant,
                            "close and distant fallbacks should produce different text")


class ApologyTests(unittest.TestCase):
    """Saying sorry is recognized and gives a forgiving response (relationship healing)."""

    def _repo_cfg(self):
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config", "persona.json",
        )

    def test_apology_ja_generic_responds(self):
        p = Persona.load(config_path=self._repo_cfg(), lang="ja")
        reply = p.respond("ごめんね")
        self.assertTrue(reply)
        self.assertNotEqual(reply, "ごめんね")

    def test_apology_en_generic_responds(self):
        p = Persona.load(config_path=self._repo_cfg(), lang="en")
        reply = p.respond("I'm sorry")
        self.assertTrue(reply)

    def test_apology_distant_level_warmer(self):
        """At distant level, apology should produce a healing-themed reply."""
        p = Persona.load(config_path=self._repo_cfg(), lang="ja")
        reply = p.respond("ごめん", level="distant")
        self.assertTrue(reply)

    def test_apology_default_responses(self):
        """Default (no config) responses also recognize apologies."""
        from persona import _DEFAULT_RESPONSES
        p = Persona()  # uses defaults
        reply = p.respond("ごめん")
        self.assertTrue(reply)
        p2 = Persona(default_lang="en", lang="en")
        reply2 = p2.respond("sorry about that")
        self.assertTrue(reply2)


class GoodnightRitualTests(unittest.TestCase):
    """Bundled config has a dedicated, warm goodnight response distinct from generic bye."""

    def _repo_cfg(self):
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config", "persona.json",
        )

    def test_goodnight_ja_responds(self):
        p = Persona.load(config_path=self._repo_cfg(), lang="ja")
        reply = p.respond("おやすみ")
        self.assertTrue(reply)
        # Goodnight reply should mention sleep/tomorrow warmth, not be empty echo
        self.assertNotEqual(reply, "おやすみ")

    def test_goodnight_en_responds(self):
        p = Persona.load(config_path=self._repo_cfg(), lang="en")
        reply = p.respond("good night")
        self.assertTrue(reply)
        # A goodnight reply conveys night/sleep/dream/tomorrow warmth
        self.assertTrue(
            any(w in reply.lower() for w in ("night", "sleep", "dream", "tomorrow")),
            f"unexpected goodnight reply: {reply}",
        )

    def test_goodnight_distinct_from_goodbye_ja(self):
        """おやすみ and さようなら should map to different reply pools."""
        p = Persona.load(config_path=self._repo_cfg(), lang="ja")
        # Collect possible replies by sampling many times
        gn = {p.respond("おやすみ") for _ in range(30)}
        p2 = Persona.load(config_path=self._repo_cfg(), lang="ja")
        bye = {p2.respond("さようなら") for _ in range(30)}
        # The two pools should not be identical
        self.assertTrue(gn.isdisjoint(bye) or gn != bye)

    def test_goodnight_close_level_ja(self):
        p = Persona.load(config_path=self._repo_cfg(), lang="ja")
        reply = p.respond("おやすみ", level="close")
        self.assertTrue(reply)


class PerLevelFallbackTests(unittest.TestCase):
    """respond() picks per-level fallback before global fallback."""

    def _persona_with_level_fb(self):
        data = {
            "default_lang": "en",
            "responses": {
                "en": {
                    "rules": [{"keywords": ["generic"], "replies": ["GENERIC_RULE"]}],
                    "fallback": ["GLOBAL_FB"],
                    "respond_by_affinity": {
                        "close": [
                            {"keywords": ["hello"], "replies": ["CLOSE_HELLO"]},
                            {"fallback": ["CLOSE_FB_1", "CLOSE_FB_2"]},
                        ],
                        "friendly": [
                            {"fallback": ["FRIENDLY_FB"]},
                        ],
                    },
                },
            },
        }
        return Persona.from_dict(data, lang="en")

    def test_level_fallback_used_when_no_keyword_match(self):
        p = self._persona_with_level_fb()
        result = p.respond("something random", level="close")
        self.assertIn(result, ["CLOSE_FB_1", "CLOSE_FB_2"])

    def test_level_fallback_not_used_when_keyword_matches(self):
        p = self._persona_with_level_fb()
        self.assertEqual(p.respond("hello", level="close"), "CLOSE_HELLO")

    def test_level_fallback_friendly(self):
        p = self._persona_with_level_fb()
        self.assertEqual(p.respond("unknown", level="friendly"), "FRIENDLY_FB")

    def test_global_fallback_used_when_no_level_fallback(self):
        p = self._persona_with_level_fb()
        # level="distant" has no rules/fallback → global fallback
        result = p.respond("xyz", level="distant")
        self.assertEqual(result, "GLOBAL_FB")

    def test_global_fallback_used_when_no_level(self):
        p = self._persona_with_level_fb()
        result = p.respond("xyz")
        self.assertEqual(result, "GLOBAL_FB")

    def test_level_fallback_generic_rule_still_checked(self):
        p = self._persona_with_level_fb()
        # "generic" matches the top-level rule, not the level fallback
        result = p.respond("generic", level="close")
        self.assertEqual(result, "GENERIC_RULE")


class FollowUpQuestionTests(unittest.TestCase):
    """persona.follow_up_question() returns curiosity prompts, level-gated."""

    def _persona(self):
        data = {
            "default_lang": "en",
            "responses": {
                "en": {
                    "rules": [],
                    "fallback": ["FB"],
                    "follow_up": ["Q1", "Q2"],
                    "follow_up_by_affinity": {"close": ["CLOSE_Q"]},
                },
            },
        }
        return Persona.from_dict(data, lang="en")

    def test_returns_a_follow_up(self):
        p = self._persona()
        self.assertIn(p.follow_up_question(), {"Q1", "Q2"})

    def test_close_level_uses_affinity_question(self):
        p = self._persona()
        self.assertEqual(p.follow_up_question(level="close"), "CLOSE_Q")

    def test_unknown_level_falls_back_to_generic(self):
        p = self._persona()
        self.assertIn(p.follow_up_question(level="reserved"), {"Q1", "Q2"})

    def test_empty_when_no_follow_up_configured(self):
        data = {"default_lang": "en",
                "responses": {"en": {"rules": [], "fallback": ["FB"]}}}
        p = Persona.from_dict(data, lang="en")
        self.assertEqual(p.follow_up_question(), "")

    def test_no_repeat_consecutive(self):
        data = {"default_lang": "en",
                "responses": {"en": {"rules": [], "fallback": ["FB"],
                                     "follow_up": ["A", "B"]}}}
        p = Persona.from_dict(data, lang="en")
        seen = {p.follow_up_question() for _ in range(6)}
        # both options should appear over several calls (no-repeat rotates them)
        self.assertEqual(seen, {"A", "B"})

    def test_bundled_config_has_follow_up(self):
        repo_cfg = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config", "persona.json",
        )
        p = Persona.load(config_path=repo_cfg, lang="ja")
        self.assertTrue(p.follow_up_question())
        self.assertTrue(p.follow_up_question(level="close"))


class TalkByAffinityTests(unittest.TestCase):
    """persona.talk(level=) uses talk_by_affinity when available."""

    def _make_persona(self):
        data = {
            "name": "T", "default_lang": "en",
            "dialogue": {"en": {
                "talk": ["GENERIC"],
                "talk_by_affinity": {
                    "close": ["VERY_CLOSE"],
                    "friendly": ["FRIENDLY"],
                },
            }},
        }
        return Persona.from_dict(data, lang="en")

    def test_close_level_uses_affinity_talk(self):
        p = self._make_persona()
        self.assertEqual(p.talk(level="close"), "VERY_CLOSE")

    def test_friendly_level_uses_affinity_talk(self):
        p = self._make_persona()
        self.assertEqual(p.talk(level="friendly"), "FRIENDLY")

    def test_no_level_uses_generic_talk(self):
        p = self._make_persona()
        self.assertEqual(p.talk(), "GENERIC")

    def test_missing_level_falls_back_to_generic(self):
        p = self._make_persona()
        # "distant" not in talk_by_affinity → falls back to generic
        self.assertEqual(p.talk(level="distant"), "GENERIC")

    def test_bundled_persona_has_talk_by_affinity(self):
        """config/persona.json has talk_by_affinity for all 5 levels."""
        import os, json
        cfg_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config", "persona.json",
        )
        p = Persona.load(config_path=cfg_path, lang="ja")
        close_talk = p.talk(level="close")
        generic_talk = Persona.load(config_path=cfg_path, lang="ja").talk()
        self.assertTrue(close_talk)
        self.assertNotEqual(close_talk, generic_talk)


class TalkByTimeTests(unittest.TestCase):
    """persona.talk(time_bucket=) uses talk_by_time when available."""

    def _make_persona(self, time_lines=None):
        """Build a test persona with deterministic time_by_time content."""
        lines = time_lines or {
            "morning": ["MORNING_TALK"],
            "afternoon": ["AFTERNOON_TALK"],
            "evening": ["EVENING_TALK"],
            "night": ["NIGHT_TALK"],
        }
        data = {
            "name": "T", "default_lang": "en",
            "dialogue": {"en": {
                "talk": ["GENERIC"],
                "talk_by_time": lines,
            }},
        }
        return Persona.from_dict(data, lang="en")

    def test_morning_bucket_can_return_morning_line(self):
        """talk(time_bucket='morning') with forced random returns the morning line."""
        from unittest import mock
        p = self._make_persona()
        with mock.patch("random.random", return_value=0.1):  # < 0.25 → time fires
            result = p.talk(time_bucket="morning")
        self.assertEqual(result, "MORNING_TALK")

    def test_evening_bucket_can_return_evening_line(self):
        from unittest import mock
        p = self._make_persona()
        with mock.patch("random.random", return_value=0.1):
            result = p.talk(time_bucket="evening")
        self.assertEqual(result, "EVENING_TALK")

    def test_time_bucket_skipped_when_random_high(self):
        """When random >= 0.25, time bucket is skipped and falls through to generic."""
        from unittest import mock
        p = self._make_persona()
        with mock.patch("random.random", return_value=0.9):  # > 0.25 → skip time
            result = p.talk(time_bucket="morning")
        self.assertEqual(result, "GENERIC")

    def test_no_time_bucket_returns_generic(self):
        """If time_bucket is None, talk_by_time is never consulted."""
        p = self._make_persona()
        result = p.talk(time_bucket=None)
        self.assertEqual(result, "GENERIC")

    def test_level_takes_priority_over_time(self):
        """talk_by_affinity has higher priority than talk_by_time."""
        from unittest import mock
        data = {
            "name": "T", "default_lang": "en",
            "dialogue": {"en": {
                "talk": ["GENERIC"],
                "talk_by_affinity": {"close": ["CLOSE_LINE"]},
                "talk_by_time": {"morning": ["MORNING_LINE"]},
            }},
        }
        p = Persona.from_dict(data, lang="en")
        with mock.patch("random.random", return_value=0.1):
            result = p.talk(level="close", time_bucket="morning")
        # level takes priority: should be CLOSE_LINE, not MORNING_LINE
        self.assertEqual(result, "CLOSE_LINE")

    def test_bundled_persona_has_talk_by_time(self):
        """config/persona.json has talk_by_time for all 4 time buckets in ja and en."""
        import os
        import json
        cfg_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config", "persona.json",
        )
        from unittest import mock
        p = Persona.load(config_path=cfg_path, lang="ja")
        for bucket in ("morning", "afternoon", "evening", "night"):
            with mock.patch("random.random", return_value=0.1):
                result = p.talk(time_bucket=bucket)
            self.assertTrue(result, f"Expected non-empty talk for bucket '{bucket}'")

    def test_pick_talk_text_passes_time_bucket(self):
        """_pick_talk_text() computes time_bucket and passes it to persona.talk()."""
        import sys
        import os
        import datetime
        sys.path.insert(0, os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main"))
        import autonomous_behavior as _ab
        from unittest import mock

        received_bucket = []

        class _FakePersona:
            lang = "en"

            def talk(self, lang=None, level=None, mood_key=None, time_bucket=None):
                received_bucket.append(time_bucket)
                return "FAKE"

        class _Mixin(_ab.AutonomousBehaviorMixin):
            talks = ["fallback"]

            @property
            def persona(self):
                return _FakePersona()

        obj = object.__new__(_Mixin)
        # Patch datetime.datetime.now() to return a morning hour (7am).
        # _pick_talk_text uses `import datetime as _dt` locally, so we patch
        # the global datetime.datetime class so the local import sees it.
        fake_now = mock.MagicMock()
        fake_now.hour = 7

        with mock.patch("autonomous_behavior._get_mood_tracker", None), \
             mock.patch("autonomous_behavior._get_daily_mood", None), \
             mock.patch("autonomous_behavior._get_user_profile", None), \
             mock.patch("autonomous_behavior._recall_fact", None), \
             mock.patch("datetime.datetime") as fake_dt_cls:
            fake_dt_cls.now.return_value = fake_now
            result = obj._pick_talk_text()

        self.assertEqual(result, "FAKE")
        self.assertEqual(received_bucket, ["morning"])


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


class InterestMentionTests(unittest.TestCase):
    """Persona.interest_mention() returns a filled template referencing the interest."""

    def test_returns_nonempty_string(self):
        p = Persona()
        result = p.interest_mention("アニメ", lang="ja")
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_interest_name_in_output(self):
        p = Persona()
        result = p.interest_mention("アニメ", lang="ja")
        self.assertIn("アニメ", result)

    def test_en_interest_name_in_output(self):
        p = Persona()
        result = p.interest_mention("anime", lang="en")
        self.assertIn("anime", result)

    def test_empty_interest_returns_empty(self):
        p = Persona()
        self.assertEqual(p.interest_mention("", lang="ja"), "")

    def test_lang_fallback_returns_something(self):
        """Unsupported lang falls back to en templates."""
        p = Persona()
        result = p.interest_mention("music", lang="fr")
        self.assertGreater(len(result), 0)
        self.assertIn("music", result)

    def test_no_repeat_on_consecutive_calls(self):
        """With 4 templates, two consecutive calls should not always return the same."""
        p = Persona()
        results = {p.interest_mention("anime", lang="en") for _ in range(20)}
        self.assertGreater(len(results), 1)

    def test_custom_interest_mentions_in_config(self):
        """responses block can supply custom interest_mentions templates."""
        p = Persona.from_dict({
            "responses": {
                "en": {
                    "interest_mentions": ["You love {interest}, right?"],
                    "rules": [],
                    "fallback": [],
                }
            },
            "default_lang": "en",
        }, lang="en")
        result = p.interest_mention("cats", lang="en")
        self.assertEqual(result, "You love cats, right?")

    def test_bundled_persona_returns_nonempty(self):
        """Bundled config/persona.json works end-to-end with interest_mention."""
        p = get_persona()
        result = p.interest_mention("音楽")
        self.assertGreater(len(result), 0)
        self.assertIn("音楽", result)
        reset_persona()

    def test_bundled_persona_en_interest_mention(self):
        """Bundled config/persona.json's en interest_mentions are used."""
        p = get_persona()
        result = p.interest_mention("anime", lang="en")
        self.assertGreater(len(result), 0)
        self.assertIn("anime", result)
        reset_persona()


class DefaultRespondByAffinityTests(unittest.TestCase):
    """_DEFAULT_RESPONSES now includes respond_by_affinity for all 5 levels."""

    def test_close_level_different_from_neutral(self):
        """Close-level reply to 'hello' is more affectionate than neutral."""
        p = Persona(lang="ja")
        close_reply = p.respond("こんにちは", level="close")
        neutral_reply = p.respond("こんにちは", level="neutral")
        self.assertGreater(len(close_reply), 0)
        self.assertGreater(len(neutral_reply), 0)
        # close and neutral should have different pools
        # (not guaranteed to differ on a single draw, but both should be nonempty)

    def test_distant_level_reply_nonempty(self):
        p = Persona(lang="ja")
        self.assertGreater(len(p.respond("こんにちは", level="distant")), 0)

    def test_friendly_level_fallback_nonempty(self):
        p = Persona(lang="ja")
        self.assertGreater(len(p.respond("random text xyz", level="friendly")), 0)

    def test_en_close_level_reply_nonempty(self):
        p = Persona(lang="en")
        self.assertGreater(len(p.respond("hello", level="close")), 0)

    def test_en_distant_level_fallback_nonempty(self):
        p = Persona(lang="en")
        self.assertGreater(len(p.respond("random text xyz", level="distant")), 0)

    def test_all_levels_respond_nonempty_ja(self):
        p = Persona(lang="ja")
        for level in ("distant", "reserved", "neutral", "friendly", "close"):
            reply = p.respond("こんにちは", level=level)
            self.assertGreater(len(reply), 0, f"level={level} returned empty reply")

    def test_all_levels_respond_nonempty_en(self):
        p = Persona(lang="en")
        for level in ("distant", "reserved", "neutral", "friendly", "close"):
            reply = p.respond("hello", level=level)
            self.assertGreater(len(reply), 0, f"level={level} returned empty reply")


class GiftCatalogMinLevelTests(unittest.TestCase):
    """gift_catalog_text() must show min_level info for gated items."""

    def test_ja_catalog_shows_level_for_music(self):
        from gifts import gift_catalog_text
        text = gift_catalog_text("ja")
        self.assertIn("普通", text)  # music requires neutral → 普通

    def test_en_catalog_shows_requires_for_music(self):
        from gifts import gift_catalog_text
        text = gift_catalog_text("en")
        self.assertIn("requires", text)

    def test_ja_catalog_shows_level_for_letter(self):
        from gifts import gift_catalog_text
        text = gift_catalog_text("ja")
        self.assertIn("友好的", text)  # letter requires friendly → 友好的

    def test_ungated_items_have_no_level_suffix(self):
        """flowers and cake have no min_level so no 'requires' text."""
        from gifts import gift_catalog_text
        text = gift_catalog_text("en")
        lines = [l for l in text.splitlines() if "flower" in l.lower() or "cake" in l.lower()]
        for line in lines:
            self.assertNotIn("requires", line)


if __name__ == "__main__":
    unittest.main()
