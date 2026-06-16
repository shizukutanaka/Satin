"""
Unit tests for persona_cli — the headless chat REPL.

The loop takes injectable input_fn/output_fn so it is fully testable without a
terminal. Covers: greeting, response, commands (/help, /name, /history, /quit),
EOF/blank handling, echo fallback, and conversation logging.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import persona_cli  # noqa: E402
from persona import Persona  # noqa: E402
from conversation_log import (  # noqa: E402
    ConversationLog,
    EVENT_AVATAR_REPLY,
    EVENT_USER_COMMENT,
)


def _persona():
    data = {
        "name": "Mimi",
        "default_lang": "en",
        "dialogue": {"en": {"greeting": {
            "morning": ["GM"], "afternoon": ["GA"], "evening": ["GE"], "night": ["GN"],
        }}},
        "responses": {"en": {
            "rules": [
                {"keywords": ["hello"], "replies": ["HI"]},
                {"keywords": ["bye", "さようなら"], "replies": ["SEEYA"]},
            ],
            "fallback": ["FB"],
        }},
    }
    return Persona.from_dict(data, lang="en")


class _Driver:
    """Feeds scripted inputs and captures outputs."""
    def __init__(self, inputs):
        self._inputs = list(inputs)
        self.out = []

    def input_fn(self, prompt=""):
        if not self._inputs:
            raise EOFError
        return self._inputs.pop(0)

    def output_fn(self, line):
        self.out.append(line)


class RespondToTests(unittest.TestCase):
    def test_keyword_reply(self):
        p = _persona()
        self.assertEqual(persona_cli.respond_to("hello", p), "HI")

    def test_echo_fallback_when_empty_response(self):
        # A persona whose respond() returns "" (no rules, no fallback) echoes input.
        p = Persona.from_dict({"responses": {"en": {"rules": [], "fallback": []}},
                               "default_lang": "en"}, lang="en")
        self.assertEqual(persona_cli.respond_to("anything", p), "anything")

    def test_logs_exchange(self):
        tmp = tempfile.mkdtemp()
        try:
            log = ConversationLog(os.path.join(tmp, "c.jsonl"))
            persona_cli.respond_to("hello", _persona(), log)
            evs = log.recent()
            self.assertEqual([e["event_type"] for e in evs],
                             [EVENT_USER_COMMENT, EVENT_AVATAR_REPLY])
            self.assertEqual(evs[1]["details"]["text"], "HI")
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_log_failure_does_not_raise(self):
        class _BadLog:
            def log_exchange(self, *a, **k):
                raise RuntimeError("disk full")
        # must not raise, still returns reply
        self.assertEqual(persona_cli.respond_to("hello", _persona(), _BadLog()), "HI")

    def test_level_passed_to_persona_respond(self):
        """respond_to() with level= uses respond_by_affinity rules when available."""
        data = {
            "name": "Test", "default_lang": "en",
            "responses": {"en": {
                "rules": [{"keywords": ["hello"], "replies": ["GENERIC"]}],
                "fallback": ["FB"],
                "respond_by_affinity": {
                    "close": [{"keywords": ["hello"], "replies": ["CLOSE_HI"]}],
                },
            }},
        }
        p = Persona.from_dict(data, lang="en")
        reply = persona_cli.respond_to("hello", p, level="close")
        self.assertEqual(reply, "CLOSE_HI")

    def test_level_none_uses_generic_rules(self):
        data = {
            "name": "Test", "default_lang": "en",
            "responses": {"en": {
                "rules": [{"keywords": ["hello"], "replies": ["GENERIC"]}],
                "fallback": [],
                "respond_by_affinity": {
                    "close": [{"keywords": ["hello"], "replies": ["CLOSE_HI"]}],
                },
            }},
        }
        p = Persona.from_dict(data, lang="en")
        reply = persona_cli.respond_to("hello", p, level=None)
        self.assertEqual(reply, "GENERIC")


class RunChatTests(unittest.TestCase):
    def setUp(self):
        # Inject a temp-file conversation log so the loop never writes to CWD
        # via the shared singleton (which defaults to ./avatar_event_log.jsonl).
        self._tmp = tempfile.mkdtemp()
        self._log = ConversationLog(os.path.join(self._tmp, "c.jsonl"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _run(self, inputs, **kw):
        d = _Driver(inputs)
        n = persona_cli.run_chat(
            persona=_persona(), conv_log=self._log,
            input_fn=d.input_fn, output_fn=d.output_fn, **kw,
        )
        return n, d.out

    def test_greeting_shown_first(self):
        n, out = self._run([], greet=True)
        self.assertTrue(out[0].startswith("Mimi: G"))  # one of GM/GA/GE/GN

    def test_no_greet_skips_greeting(self):
        n, out = self._run([], greet=False)
        # First line is the help text, not a greeting
        self.assertNotIn("Mimi: G", out[0])

    def test_basic_exchange_counts(self):
        n, out = self._run(["hello", "hello"], greet=False)
        self.assertEqual(n, 2)
        self.assertIn("Mimi: HI", out)

    def test_follow_up_appended_every_n_exchanges(self):
        """The avatar proactively asks a follow-up question every N exchanges."""
        data = {
            "name": "Mimi", "default_lang": "en",
            "responses": {"en": {
                "rules": [{"keywords": ["hello"], "replies": ["HI"]}],
                "fallback": ["FB"],
                "follow_up": ["WHATS_NEW"],
            }},
        }
        persona = Persona.from_dict(data, lang="en")
        d = _Driver(["hello"] * persona_cli._FOLLOW_UP_EVERY)
        persona_cli.run_chat(
            persona=persona, conv_log=self._log,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        # The Nth reply line should carry the appended follow-up question
        self.assertTrue(any("WHATS_NEW" in line for line in d.out))

    def test_follow_up_not_appended_before_threshold(self):
        data = {
            "name": "Mimi", "default_lang": "en",
            "responses": {"en": {
                "rules": [{"keywords": ["hello"], "replies": ["HI"]}],
                "fallback": ["FB"],
                "follow_up": ["WHATS_NEW"],
            }},
        }
        persona = Persona.from_dict(data, lang="en")
        d = _Driver(["hello"])  # only 1 exchange (< N)
        persona_cli.run_chat(
            persona=persona, conv_log=self._log,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        self.assertFalse(any("WHATS_NEW" in line for line in d.out))

    def test_blank_lines_ignored(self):
        n, out = self._run(["", "  ", "hello"], greet=False)
        self.assertEqual(n, 1)

    def test_quit_command_stops_and_says_farewell(self):
        n, out = self._run(["hello", "/quit", "hello"], greet=False)
        self.assertEqual(n, 1)  # only the first hello counts; loop stops at /quit
        self.assertIn("Mimi: SEEYA", out)

    def test_help_command(self):
        n, out = self._run(["/help"], greet=False)
        self.assertTrue(any("コマンド" in line for line in out))
        self.assertEqual(n, 0)

    def test_name_command(self):
        n, out = self._run(["/name"], greet=False)
        self.assertIn("Mimi", out)

    def test_eof_ends_loop(self):
        # No quit; EOF (empty input list) must terminate cleanly.
        n, out = self._run(["hello"], greet=False)
        self.assertEqual(n, 1)

    def test_stats_command_shows_session_count(self):
        n, out = self._run(["hello", "/stats"], greet=False)
        self.assertEqual(n, 1)
        self.assertTrue(any("1" in line for line in out))

    def test_stats_does_not_count_as_exchange(self):
        n, out = self._run(["/stats"], greet=False)
        self.assertEqual(n, 0)


class RunChatHistoryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.log = ConversationLog(os.path.join(self._tmp, "c.jsonl"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_history_shows_logged_exchanges(self):
        d = _Driver(["hello", "/history"])
        persona_cli.run_chat(
            persona=_persona(), conv_log=self.log,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        self.assertTrue(any("You: hello" in line for line in d.out))
        self.assertTrue(any("Avatar: HI" in line for line in d.out))

    def test_history_empty_message(self):
        d = _Driver(["/history"])
        persona_cli.run_chat(
            persona=_persona(), conv_log=self.log,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        self.assertTrue(any("まだ会話履歴" in line for line in d.out))

    def test_search_finds_matching_entry(self):
        d = _Driver(["hello", "/search hello"])
        persona_cli.run_chat(
            persona=_persona(), conv_log=self.log,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        self.assertTrue(any("hello" in line and "You" in line for line in d.out))

    def test_search_no_match_shows_message(self):
        d = _Driver(["hello", "/search zzznomatch"])
        persona_cli.run_chat(
            persona=_persona(), conv_log=self.log,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        self.assertTrue(any("見つかりませんでした" in line for line in d.out))

    def test_search_no_query_shows_usage(self):
        d = _Driver(["/search"])
        persona_cli.run_chat(
            persona=_persona(), conv_log=self.log,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        self.assertTrue(any("/search" in line for line in d.out))

    def test_search_unavailable_without_log(self):
        outs = []
        persona_cli._print_search(None, "hello", outs.append)
        self.assertTrue(any("利用できません" in line for line in outs))


class MoodIntegrationTests(unittest.TestCase):
    """run_chat updates the injected mood tracker and exposes /mood."""

    def _run(self, inputs, mood):
        from mood import MoodTracker  # local import; mood is optional
        d = _Driver(inputs)
        tmp = tempfile.mkdtemp()
        try:
            log = ConversationLog(os.path.join(tmp, "c.jsonl"))
            persona_cli.run_chat(
                persona=_persona(), conv_log=log, mood=mood,
                input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
            )
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
        return d.out

    def test_positive_input_raises_affinity(self):
        from mood import MoodTracker
        m = MoodTracker(affinity=50)
        self._run(["thank you", "I love you"], m)
        self.assertGreater(m.affinity, 50)

    def test_mood_command_shows_level(self):
        from mood import MoodTracker
        m = MoodTracker(affinity=85)
        out = self._run(["/mood"], m)
        self.assertTrue(any("close" in line for line in out))

    def test_commands_do_not_affect_affinity(self):
        from mood import MoodTracker
        m = MoodTracker(affinity=50)
        self._run(["/help", "/mood", "/name"], m)
        self.assertEqual(m.affinity, 50)
        self.assertEqual(m.interactions, 0)

    def test_mood_shows_interaction_count(self):
        from mood import MoodTracker
        m = MoodTracker(affinity=50, interactions=7)
        out = self._run(["/mood"], m)
        self.assertTrue(any("7" in line and ("回" in line or "Conversation" in line)
                            for line in out))

    def test_mood_shows_next_milestone(self):
        from mood import MoodTracker
        m = MoodTracker(affinity=50, interactions=7)
        out = self._run(["/mood"], m)
        # next interaction milestone after 7 is 10
        self.assertTrue(any("10" in line for line in out))

    def test_mood_shows_days_known(self):
        import time
        from mood import MoodTracker
        m = MoodTracker(affinity=50, interactions=5)
        m._first_interaction_time = time.time() - 5 * 86400
        out = self._run(["/mood"], m)
        self.assertTrue(any("5" in line and ("日" in line or "day" in line.lower())
                            for line in out))

    def test_mood_no_stats_when_zero_interactions(self):
        from mood import MoodTracker
        m = MoodTracker(affinity=50, interactions=0)
        out = self._run(["/mood"], m)
        # Should not show a conversation count line for a fresh tracker
        self.assertFalse(any("会話回数" in line or "Conversations:" in line
                             for line in out))

    def test_reset_mood_command_resets_to_neutral(self):
        from mood import MoodTracker, AFFINITY_START
        m = MoodTracker(affinity=90, interactions=10)
        out = self._run(["/reset-mood"], m)
        self.assertEqual(m.affinity, AFFINITY_START)
        self.assertEqual(m.interactions, 0)
        self.assertTrue(any("50" in line or "neutral" in line or "ニュートラル" in line
                            for line in out))

    def test_reset_mood_disabled_when_none(self):
        d = _Driver(["/reset-mood"])
        persona_cli.run_chat(
            persona=_persona(), conv_log=None, mood=None,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        self.assertTrue(any("無効" in line for line in d.out))

    def test_mood_disabled_when_none(self):
        d = _Driver(["/mood"])
        persona_cli.run_chat(
            persona=_persona(), conv_log=None, mood=None,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        self.assertTrue(any("無効" in line for line in d.out))

    def test_high_affinity_uses_warm_greeting(self):
        """A close-relationship mood selects the affinity-specific greeting."""
        from mood import MoodTracker
        data = {
            "name": "Mimi", "default_lang": "en",
            "dialogue": {"en": {
                "greeting": {"morning": ["GENERIC"], "afternoon": ["GENERIC"],
                             "evening": ["GENERIC"], "night": ["GENERIC"]},
                "greeting_by_affinity": {"close": ["WELCOME_BACK"]},
            }},
            "responses": {"en": {"rules": [], "fallback": ["FB"]}},
        }
        persona = Persona.from_dict(data, lang="en")
        m = MoodTracker(affinity=90)  # 'close'
        d = _Driver([])
        persona_cli.run_chat(
            persona=persona, conv_log=None, mood=m,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=True,
        )
        self.assertEqual(d.out[0], "Mimi: WELCOME_BACK")

    def test_level_milestone_appended_to_reply(self):
        """CLI appends milestone message to reply when affinity level crosses a threshold."""
        from mood import MoodTracker
        # friendly threshold is 60; put affinity just below so one positive hit crosses it
        m = MoodTracker(affinity=59.0, positive_delta=10.0)
        data = {
            "name": "Mimi", "default_lang": "en",
            "responses": {"en": {"rules": [], "fallback": ["OK"]}},
        }
        persona = Persona.from_dict(data, lang="en")
        d = _Driver(["thank you"])
        persona_cli.run_chat(
            persona=persona, conv_log=None, mood=m,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        # At least one reply line should contain the milestone message (non-empty extra text)
        reply_lines = [l for l in d.out if l.startswith("Mimi:")]
        self.assertTrue(len(reply_lines) >= 1)
        # The reply should be longer than just "Mimi: OK" (milestone appended)
        combined = " ".join(reply_lines)
        self.assertGreater(len(combined), len("Mimi: OK"))

    def test_anniversary_message_shown_at_greeting(self):
        """A relationship milestone is celebrated in the greeting."""
        import time
        from mood import MoodTracker
        m = MoodTracker(affinity=60, interactions=5)
        m._first_interaction_time = time.time() - 30 * 86400  # 30 days ago
        data = {
            "name": "Mimi", "default_lang": "en",
            "dialogue": {"en": {"greeting": {
                "morning": ["GM"], "afternoon": ["GM"],
                "evening": ["GM"], "night": ["GM"]}}},
            "responses": {"en": {"rules": [], "fallback": ["FB"]}},
        }
        persona = Persona.from_dict(data, lang="en")
        d = _Driver([])
        persona_cli.run_chat(
            persona=persona, conv_log=None, mood=m,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=True,
        )
        self.assertTrue(any("30 days" in line for line in d.out))


class AbsenceMessageTests(unittest.TestCase):
    """_absence_message() emits nothing for recent/no interactions, message for long absence."""

    def _mood_with_timestamp(self, hours_ago: float, interactions: int = 5):
        import time
        from mood import MoodTracker
        m = MoodTracker(affinity=70, interactions=interactions)
        m._last_interaction_time = time.time() - hours_ago * 3600
        return m

    def test_no_message_when_no_interactions(self):
        import time
        from mood import MoodTracker
        m = MoodTracker(affinity=50, interactions=0)
        m._last_interaction_time = time.time() - 72 * 3600
        self.assertEqual(persona_cli._absence_message(m, "Mimi", "en"), "")

    def test_no_message_within_24h(self):
        m = self._mood_with_timestamp(hours_ago=12)
        self.assertEqual(persona_cli._absence_message(m, "Mimi", "en"), "")

    def test_no_message_with_no_timestamp(self):
        from mood import MoodTracker
        m = MoodTracker(affinity=50, interactions=5)
        m._last_interaction_time = 0.0
        self.assertEqual(persona_cli._absence_message(m, "Mimi", "en"), "")

    def test_one_day_absence_en(self):
        m = self._mood_with_timestamp(hours_ago=25)
        msg = persona_cli._absence_message(m, "Mimi", "en")
        self.assertIn("day", msg.lower())
        self.assertIn("missed", msg.lower())

    def test_multi_day_absence_en(self):
        m = self._mood_with_timestamp(hours_ago=72)
        msg = persona_cli._absence_message(m, "Mimi", "en")
        self.assertIn("3", msg)

    def test_one_day_absence_ja(self):
        m = self._mood_with_timestamp(hours_ago=25)
        msg = persona_cli._absence_message(m, "Mimi", "ja")
        self.assertIn("昨日", msg)

    def test_multi_day_absence_ja(self):
        m = self._mood_with_timestamp(hours_ago=72)
        msg = persona_cli._absence_message(m, "Mimi", "ja")
        self.assertIn("日", msg)

    def test_absence_shown_before_greeting_in_run_chat(self):
        """When greet=True and mood has a long absence, absence message appears before greeting."""
        import time
        from mood import MoodTracker
        m = MoodTracker(affinity=70, interactions=3)
        m._last_interaction_time = time.time() - 50 * 3600  # ~2 days ago
        d = _Driver([])
        tmp = tempfile.mkdtemp()
        try:
            log = ConversationLog(os.path.join(tmp, "c.jsonl"))
            persona_cli.run_chat(
                persona=_persona(), conv_log=log, mood=m,
                input_fn=d.input_fn, output_fn=d.output_fn, greet=True,
            )
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
        # First line should be the absence message (contains "day" or "日")
        absence_lines = [l for l in d.out if "day" in l.lower() or "日" in l]
        self.assertTrue(len(absence_lines) > 0)


class UserProfileIntegrationTests(unittest.TestCase):
    """run_chat learns and uses the user's name via /callme, /whoami."""

    def setUp(self):
        import user_profile
        self._up = user_profile
        self._tmp = tempfile.mkdtemp()
        self._ppath = os.path.join(self._tmp, "up.json")
        # Redirect profile persistence to the temp file
        self._patcher = mock.patch.object(persona_cli, "_profile_path",
                                          lambda: self._ppath)
        self._patcher.start()

    def tearDown(self):
        import shutil
        self._patcher.stop()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _profile(self, **kw):
        return self._up.UserProfile(**kw)

    def test_callme_sets_and_confirms_name(self):
        prof = self._profile()
        d = _Driver(["/callme Taro"])
        persona_cli.run_chat(
            persona=_persona(), conv_log=None, profile=prof,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        self.assertEqual(prof.name, "Taro")
        self.assertTrue(any("Taro" in line for line in d.out))

    def test_callme_persists_to_disk(self):
        prof = self._profile()
        d = _Driver(["/callme Hana"])
        persona_cli.run_chat(
            persona=_persona(), conv_log=None, profile=prof,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        self.assertTrue(os.path.exists(self._ppath))
        loaded = self._up.UserProfile.load(self._ppath)
        self.assertEqual(loaded.name, "Hana")

    def test_callme_without_name_shows_usage(self):
        prof = self._profile()
        d = _Driver(["/callme"])
        persona_cli.run_chat(
            persona=_persona(), conv_log=None, profile=prof,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        self.assertTrue(any("/callme" in line for line in d.out))

    def test_birthday_sets_and_persists(self):
        prof = self._profile()
        d = _Driver(["/birthday 06-15"])
        persona_cli.run_chat(
            persona=_persona(), conv_log=None, profile=prof,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        self.assertEqual(prof.birthday, "06-15")
        loaded = self._up.UserProfile.load(self._ppath)
        self.assertEqual(loaded.birthday, "06-15")

    def test_birthday_invalid_shows_help(self):
        prof = self._profile()
        d = _Driver(["/birthday 99-99"])
        persona_cli.run_chat(
            persona=_persona(), conv_log=None, profile=prof,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        self.assertEqual(prof.birthday, "")
        self.assertTrue(any("MM-DD" in line for line in d.out))

    def test_birthday_without_arg_shows_usage(self):
        prof = self._profile()
        d = _Driver(["/birthday"])
        persona_cli.run_chat(
            persona=_persona(), conv_log=None, profile=prof,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        self.assertTrue(any("/birthday" in line for line in d.out))

    def test_whoami_shows_birthday(self):
        prof = self._profile(name="Yuki", birthday="03-03")
        d = _Driver(["/whoami"])
        persona_cli.run_chat(
            persona=_persona(), conv_log=None, profile=prof,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        self.assertTrue(any("03-03" in line for line in d.out))

    def test_whoami_unknown(self):
        prof = self._profile()
        d = _Driver(["/whoami"])
        persona_cli.run_chat(
            persona=_persona(), conv_log=None, profile=prof,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        self.assertTrue(any("まだ呼び名" in line or "don't know" in line.lower()
                            for line in d.out))

    def test_whoami_known(self):
        prof = self._profile(name="Yuki")
        d = _Driver(["/whoami"])
        persona_cli.run_chat(
            persona=_persona(), conv_log=None, profile=prof,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        self.assertTrue(any("Yuki" in line for line in d.out))

    def test_greeting_addresses_known_user_by_name(self):
        prof = self._profile(name="Ken")
        d = _Driver([])
        persona_cli.run_chat(
            persona=_persona(), conv_log=None, profile=prof,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=True,
        )
        # The first (greeting) line should contain the name
        self.assertTrue(any("Ken" in line for line in d.out))

    def test_user_placeholder_substituted_in_reply(self):
        # A persona whose fallback contains {user}; the reply must show the name
        data = {
            "name": "Mimi", "default_lang": "en",
            "responses": {"en": {"rules": [], "fallback": ["Hi {user}!"]}},
        }
        persona = Persona.from_dict(data, lang="en")
        prof = self._profile(name="Sam")
        d = _Driver(["whatever"])
        persona_cli.run_chat(
            persona=persona, conv_log=None, profile=prof,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        self.assertTrue(any("Hi Sam!" in line for line in d.out))

    def test_like_adds_interest(self):
        prof = self._profile()
        d = _Driver(["/like アニメ"])
        persona_cli.run_chat(
            persona=_persona(), conv_log=None, profile=prof,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        self.assertIn("アニメ", prof.interests)
        self.assertTrue(any("アニメ" in line for line in d.out))

    def test_like_persists_to_disk(self):
        prof = self._profile()
        d = _Driver(["/like 音楽"])
        persona_cli.run_chat(
            persona=_persona(), conv_log=None, profile=prof,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        loaded = self._up.UserProfile.load(self._ppath)
        self.assertIn("音楽", loaded.interests)

    def test_like_without_arg_shows_usage(self):
        prof = self._profile()
        d = _Driver(["/like"])
        persona_cli.run_chat(
            persona=_persona(), conv_log=None, profile=prof,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        self.assertTrue(any("/like" in line for line in d.out))

    def test_forget_removes_interest(self):
        prof = self._profile(interests=["ゲーム"])
        d = _Driver(["/forget ゲーム"])
        persona_cli.run_chat(
            persona=_persona(), conv_log=None, profile=prof,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        self.assertNotIn("ゲーム", prof.interests)

    def test_forget_nonexistent_shows_message(self):
        prof = self._profile()
        d = _Driver(["/forget xyz"])
        persona_cli.run_chat(
            persona=_persona(), conv_log=None, profile=prof,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        self.assertTrue(any("xyz" in line for line in d.out))

    def test_whoami_shows_interests(self):
        prof = self._profile(interests=["アニメ", "ゲーム"])
        d = _Driver(["/whoami"])
        persona_cli.run_chat(
            persona=_persona(), conv_log=None, profile=prof,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        self.assertTrue(any("アニメ" in line for line in d.out))


class MainEntryTests(unittest.TestCase):
    def _eof_input(self):
        import builtins
        orig = builtins.input
        builtins.input = lambda *a, **k: (_ for _ in ()).throw(EOFError())
        return orig

    def test_main_no_mood_no_greet_immediate_eof(self):
        # --no-mood avoids touching the real config/mood.json; EOF ends at once.
        orig = self._eof_input()
        try:
            rc = persona_cli.main(["--no-greet", "--no-mood", "--lang", "en"])
        finally:
            import builtins
            builtins.input = orig
        self.assertEqual(rc, 0)

    def test_main_persists_mood_to_default_path(self):
        """With mood enabled, main() loads and saves the affinity file."""
        import mood as _mood
        from unittest import mock
        tmp = tempfile.mkdtemp()
        mood_path = os.path.join(tmp, "mood.json")
        orig = self._eof_input()
        try:
            _mood.reset_mood_tracker()
            with mock.patch.object(_mood, "_default_mood_path", lambda: mood_path):
                rc = persona_cli.main(["--no-greet", "--lang", "en"])
            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(mood_path), "mood file should be saved")
        finally:
            import builtins
            builtins.input = orig
            _mood.reset_mood_tracker()
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


class InteractionMilestoneIntegrationTests(unittest.TestCase):
    """Tests that interaction count milestones appear in CLI output."""

    def setUp(self):
        import mood as _mood
        _mood.reset_mood_tracker()

    def tearDown(self):
        import mood as _mood
        _mood.reset_mood_tracker()

    def _run(self, messages, interactions_start=0, affinity=50.0):
        from mood import MoodTracker
        tracker = MoodTracker(affinity=affinity, interactions=interactions_start)
        inputs = iter(messages + ["/quit"])
        outputs = []
        persona_cli.run_chat(
            persona=Persona.from_dict({"name": "T"}),
            input_fn=lambda _: next(inputs),
            output_fn=outputs.append,
            greet=False,
            mood=tracker,
        )
        return outputs, tracker

    def test_milestone_at_10_ja(self):
        """10th exchange triggers milestone message (ja)."""
        outputs, tracker = self._run(["こんにちは"], interactions_start=9)
        self.assertEqual(tracker.interactions, 10)
        full = " ".join(outputs)
        self.assertIn("10", full)

    def test_milestone_at_10_en(self):
        """10th exchange triggers milestone message (en)."""
        from mood import MoodTracker
        tracker = MoodTracker(affinity=50.0, interactions=9)
        inputs = iter(["hello", "/quit"])
        outputs = []
        persona_cli.run_chat(
            persona=Persona.from_dict({"name": "T", "default_lang": "en"}),
            input_fn=lambda _: next(inputs),
            output_fn=outputs.append,
            greet=False,
            mood=tracker,
        )
        self.assertEqual(tracker.interactions, 10)
        full = " ".join(outputs)
        self.assertIn("10", full)

    def test_no_milestone_at_9(self):
        """9th exchange does not trigger milestone."""
        outputs, tracker = self._run(["こんにちは"], interactions_start=8)
        self.assertEqual(tracker.interactions, 9)
        full = " ".join(outputs)
        # "10" might appear in other numbers but NOT in milestone text
        # Verify by checking interaction count
        self.assertNotIn("10回", full)

    def test_milestone_at_100(self):
        """100th exchange triggers milestone."""
        outputs, tracker = self._run(["hello"], interactions_start=99)
        self.assertEqual(tracker.interactions, 100)
        full = " ".join(outputs)
        self.assertIn("100", full)

    def test_no_milestone_for_normal_exchanges(self):
        """Non-milestone exchanges don't produce milestone text."""
        outputs, tracker = self._run(["こんにちは"], interactions_start=5)
        self.assertEqual(tracker.interactions, 6)
        full = " ".join(outputs)
        # Should not contain any milestone count keywords
        for count in ["10回", "25回", "50回", "100回"]:
            self.assertNotIn(count, full)


if __name__ == "__main__":
    unittest.main()
