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
        """Two /reset-mood commands trigger the two-step confirm and actually reset."""
        from mood import MoodTracker, AFFINITY_START
        m = MoodTracker(affinity=90, interactions=10)
        out = self._run(["/reset-mood", "/reset-mood"], m)
        self.assertEqual(m.affinity, AFFINITY_START)
        self.assertEqual(m.interactions, 0)
        self.assertTrue(any("50" in line or "neutral" in line or "ニュートラル" in line
                            for line in out))

    def test_reset_mood_first_call_shows_confirmation_prompt(self):
        """First /reset-mood shows a warning, does NOT reset affinity."""
        from mood import MoodTracker, AFFINITY_START
        m = MoodTracker(affinity=90, interactions=10)
        out = self._run(["/reset-mood"], m)
        self.assertEqual(m.affinity, 90.0, "Affinity must not change on first call")
        full = " ".join(out)
        self.assertTrue(
            "もう一度" in full or "confirm" in full.lower() or "again" in full.lower(),
            f"Expected confirm prompt; got: {out}",
        )

    def test_reset_mood_cancelled_by_intervening_input(self):
        """A non-reset command between two /reset-mood calls cancels the pending state."""
        from mood import MoodTracker, AFFINITY_START
        m = MoodTracker(affinity=90, interactions=10)
        # reset → cancel via other cmd → reset again (should re-show prompt, NOT reset)
        out = self._run(["/reset-mood", "/mood", "/reset-mood"], m)
        self.assertEqual(m.affinity, 90.0, "Affinity must remain unchanged when cancelled")

    def test_reset_mood_disabled_when_none(self):
        """Two /reset-mood commands with mood=None shows 無効 (after confirm step)."""
        d = _Driver(["/reset-mood", "/reset-mood"])
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

    def test_daily_login_message_at_greeting(self):
        """First conversation of the day shows a daily-login welcome + bonus."""
        from mood import MoodTracker
        m = MoodTracker(affinity=50, interactions=1)
        before = m.affinity
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
        # A daily-login line should appear and affinity should have risen
        self.assertGreater(m.affinity, before)
        self.assertEqual(m._login_streak, 1)

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

    def test_whoami_shows_remembered_facts(self):
        prof = self._profile()
        prof.set_fact("favorite_food", "ラーメン")
        d = _Driver(["/whoami"])
        persona_cli.run_chat(
            persona=_persona(), conv_log=None, profile=prof,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        self.assertTrue(any("ラーメン" in line for line in d.out))

    def test_qa_loop_remembers_answer(self):
        """When the avatar asks a getting-to-know-you question, the next
        non-command input is stored as a fact."""
        from mood import MoodTracker
        prof = self._profile()
        mood = MoodTracker(affinity=50)  # neutral level
        # 4 messages to reach the follow-up cadence, then the answer on turn 5.
        d = _Driver(["a", "b", "c", "d", "ラーメンが好き"])
        # Force the 50% question gate to always fire.
        with mock.patch("random.random", return_value=0.0):
            persona_cli.run_chat(
                persona=_persona(), conv_log=None, profile=prof, mood=mood,
                input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
            )
        # At least one fact should have been captured from the answer.
        self.assertTrue(prof.facts, "expected a fact to be remembered")
        self.assertIn("ラーメンが好き", prof.facts.values())

    def test_no_question_at_distant_level(self):
        """Getting-to-know-you questions should not fire at distant level."""
        from mood import MoodTracker
        prof = self._profile()
        mood = MoodTracker(affinity=5)  # distant level
        d = _Driver(["a", "b", "c", "d", "answer"])
        with mock.patch("random.random", return_value=0.0):
            persona_cli.run_chat(
                persona=_persona(), conv_log=None, profile=prof, mood=mood,
                input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
            )
        # No profile question was asked, so "answer" must not be stored as a fact.
        self.assertEqual(prof.facts, {})


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


class HurtEventIntegrationTests(unittest.TestCase):
    """run_chat() integrates hurt_event: rude input triggers emotional reaction."""

    def _run(self, message, affinity=50.0, interactions=1):
        from mood import MoodTracker
        tracker = MoodTracker(affinity=affinity, interactions=interactions,
                              negative_delta=6.0)
        outputs = []
        it = iter([message, "/quit"])
        persona_cli.run_chat(
            persona=Persona.from_dict({"name": "T"}),
            input_fn=lambda _: next(it),
            output_fn=outputs.append,
            greet=False,
            mood=tracker,
        )
        return outputs, tracker

    def _run_with_messages(self, messages, affinity=50.0, interactions=1):
        from mood import MoodTracker
        tracker = MoodTracker(affinity=affinity, interactions=interactions,
                              negative_delta=6.0)
        outputs = []
        it = iter(messages + ["/quit"])
        persona_cli.run_chat(
            persona=Persona.from_dict({"name": "T"}),
            input_fn=lambda _: next(it),
            output_fn=outputs.append,
            greet=False,
            mood=tracker,
        )
        return outputs, tracker

    def test_rude_message_triggers_hurt_reply(self):
        """Multiple negative keywords cause a large delta and trigger a hurt response."""
        from mood import _HURT_THRESHOLD
        # "嫌い うざい ばか" hits 3 negative words → delta = -3 * 6 = -18
        # but capped at -10, which is below _HURT_THRESHOLD (-4)
        outputs, tracker = self._run("嫌い うざい ばか", affinity=80.0)
        full = " ".join(outputs)
        # The reply should contain a hurt message, not the generic persona fallback
        from mood import _HURT_MESSAGES
        hurt_words = _HURT_MESSAGES["ja"]
        self.assertTrue(
            any(hw in full for hw in hurt_words),
            f"Expected hurt message in output; got: {full!r}"
        )

    def test_mild_negative_does_not_trigger_hurt(self):
        """A single negative keyword gives only a small delta — no hurt response."""
        # "嫌い" alone → delta = -6, capped at -6; this IS below threshold (-4),
        # so let's use a word that gives -4 exactly. But with delta_cap at 10,
        # "嫌い" gives -6. So actually it SHOULD trigger hurt.
        # Let me use a custom tracker with small negative_delta
        from mood import MoodTracker, _HURT_THRESHOLD
        tracker = MoodTracker(affinity=50.0, interactions=1,
                              negative_delta=2.0)  # small delta: 1 word → -2 > -4
        outputs = []
        it = iter(["嫌い", "/quit"])
        persona_cli.run_chat(
            persona=Persona.from_dict({"name": "T"}),
            input_fn=lambda _: next(it),
            output_fn=outputs.append,
            greet=False,
            mood=tracker,
        )
        full = " ".join(outputs)
        from mood import _HURT_MESSAGES
        hurt_words = _HURT_MESSAGES["ja"]
        self.assertFalse(
            any(hw in full for hw in hurt_words),
            f"Expected NO hurt message for mild negative; got: {full!r}"
        )

    def test_hurt_reply_without_mood_no_crash(self):
        """Without mood tracker, rude input produces normal response, no crash."""
        outputs = []
        it = iter(["嫌い うざい ばか", "/quit"])
        persona_cli.run_chat(
            persona=Persona.from_dict({"name": "T"}),
            input_fn=lambda _: next(it),
            output_fn=outputs.append,
            greet=False,
            mood=None,
        )
        self.assertTrue(any("T:" in o for o in outputs))


class RitualEventTests(unittest.TestCase):
    """_detect_ritual_event() and its integration into run_chat()."""

    def test_detect_apology_ja(self):
        result = persona_cli._detect_ritual_event("ごめんね")
        self.assertIsNotNone(result)
        event_name, bonus = result
        self.assertIn("apology", event_name)
        self.assertEqual(bonus, persona_cli._APOLOGY_BONUS)

    def test_detect_apology_en(self):
        result = persona_cli._detect_ritual_event("I'm so sorry")
        self.assertIsNotNone(result)
        event_name, bonus = result
        self.assertIn("apology", event_name)
        self.assertEqual(bonus, persona_cli._APOLOGY_BONUS)

    def test_detect_goodnight_ja(self):
        result = persona_cli._detect_ritual_event("おやすみ！")
        self.assertIsNotNone(result)
        event_name, bonus = result
        self.assertIn("goodnight", event_name)
        self.assertEqual(bonus, persona_cli._GOODNIGHT_BONUS)

    def test_detect_goodnight_en(self):
        result = persona_cli._detect_ritual_event("good night!")
        self.assertIsNotNone(result)
        event_name, bonus = result
        self.assertIn("goodnight", event_name)
        self.assertEqual(bonus, persona_cli._GOODNIGHT_BONUS)

    def test_detect_both_returns_larger_bonus(self):
        result = persona_cli._detect_ritual_event("ごめん、おやすみなさい")
        self.assertIsNotNone(result)
        _, bonus = result
        self.assertEqual(bonus, max(persona_cli._APOLOGY_BONUS, persona_cli._GOODNIGHT_BONUS))

    def test_detect_none_for_normal_text(self):
        self.assertIsNone(persona_cli._detect_ritual_event("今日はいい天気だね"))
        self.assertIsNone(persona_cli._detect_ritual_event("How are you?"))

    def test_detect_case_insensitive(self):
        self.assertIsNotNone(persona_cli._detect_ritual_event("SORRY"))
        self.assertIsNotNone(persona_cli._detect_ritual_event("Good Night"))

    def _run_with_mood(self, message, affinity=50.0):
        from mood import MoodTracker
        tracker = MoodTracker(affinity=affinity)
        inputs = iter([message, "/quit"])
        outputs = []
        persona_cli.run_chat(
            persona=Persona.from_dict({"name": "T"}),
            input_fn=lambda _: next(inputs),
            output_fn=outputs.append,
            greet=False,
            mood=tracker,
        )
        return outputs, tracker

    def test_apology_increases_affinity(self):
        """Saying ごめん should raise affinity by the apology bonus."""
        _, tracker = self._run_with_mood("ごめんね", affinity=50.0)
        self.assertGreater(tracker.affinity, 50.0)

    def test_goodnight_increases_affinity(self):
        """Saying おやすみ should raise affinity by the goodnight bonus."""
        _, tracker = self._run_with_mood("おやすみ", affinity=50.0)
        self.assertGreater(tracker.affinity, 50.0)

    def test_apology_bonus_is_correct_amount(self):
        """Apology-only message with no other sentiment keywords → exact bonus."""
        # "ごめん" has no positive/negative keywords from the default list, so
        # raw_delta == 0 and only the ritual bonus is applied.
        from mood import MoodTracker
        tracker = MoodTracker(affinity=50.0)
        inputs = iter(["ごめん", "/quit"])
        outputs = []
        persona_cli.run_chat(
            persona=Persona.from_dict({"name": "T"}),
            input_fn=lambda _: next(inputs),
            output_fn=outputs.append,
            greet=False,
            mood=tracker,
        )
        self.assertAlmostEqual(tracker.affinity, 50.0 + persona_cli._APOLOGY_BONUS, places=4)

    def test_goodnight_bonus_is_correct_amount(self):
        """Goodnight-only message → exact bonus applied."""
        from mood import MoodTracker
        tracker = MoodTracker(affinity=50.0)
        inputs = iter(["おやすみ", "/quit"])
        outputs = []
        persona_cli.run_chat(
            persona=Persona.from_dict({"name": "T"}),
            input_fn=lambda _: next(inputs),
            output_fn=outputs.append,
            greet=False,
            mood=tracker,
        )
        self.assertAlmostEqual(tracker.affinity, 50.0 + persona_cli._GOODNIGHT_BONUS, places=4)

    def test_ritual_bonus_not_applied_without_mood(self):
        """Without a mood tracker, saying おやすみ should not crash."""
        inputs = iter(["おやすみ", "/quit"])
        outputs = []
        persona_cli.run_chat(
            persona=Persona.from_dict({"name": "T"}),
            input_fn=lambda _: next(inputs),
            output_fn=outputs.append,
            greet=False,
            mood=None,
        )
        self.assertTrue(any("T:" in o for o in outputs))


class MoodMultiplierDisplayTests(unittest.TestCase):
    """The /mood command shows the daily mood affinity multiplier effect."""

    def _run(self, inputs, mood):
        import persona_cli as pc
        from persona import Persona
        out = []
        it = iter(inputs + ["/quit"])
        pc.run_chat(
            persona=Persona.from_dict({"name": "T"}),
            input_fn=lambda _: next(it),
            output_fn=out.append,
            greet=False,
            mood=mood,
        )
        return out

    def test_mood_shows_multiplier_when_not_neutral(self):
        """If daily mood has a non-1.0 multiplier, /mood output includes the % change."""
        from mood import MoodTracker
        from unittest import mock
        import persona_cli as pc

        m = MoodTracker(affinity=50, interactions=0)
        # Force daily mood to "energetic" (multiplier=1.2)
        with mock.patch.object(pc, "_get_daily_mood", lambda salt="": "energetic"), \
             mock.patch.object(pc, "_mood_affinity_multiplier", lambda key: 1.2), \
             mock.patch.object(pc, "_mood_label", lambda key, lang="ja": "energetic"), \
             mock.patch.object(pc, "_mood_emoji", lambda key: "⚡"):
            out = self._run(["/mood"], m)
        # Should contain +20% somewhere
        self.assertTrue(any("+20" in line for line in out),
                        f"Expected +20% in output; got: {out}")

    def test_mood_neutral_multiplier_not_shown(self):
        """Multiplier of 1.0 (calm) should NOT add a percentage to the output."""
        from mood import MoodTracker
        from unittest import mock
        import persona_cli as pc

        m = MoodTracker(affinity=50, interactions=0)
        with mock.patch.object(pc, "_get_daily_mood", lambda salt="": "calm"), \
             mock.patch.object(pc, "_mood_affinity_multiplier", lambda key: 1.0), \
             mock.patch.object(pc, "_mood_label", lambda key, lang="ja": "calm"), \
             mock.patch.object(pc, "_mood_emoji", lambda key: "😌"):
            out = self._run(["/mood"], m)
        self.assertFalse(any("%" in line for line in out),
                         f"Expected no % in output for neutral multiplier; got: {out}")

    def test_mood_negative_multiplier_shown(self):
        """Melancholy mood (0.8 → -20%) should appear with negative sign."""
        from mood import MoodTracker
        from unittest import mock
        import persona_cli as pc

        m = MoodTracker(affinity=50, interactions=0)
        with mock.patch.object(pc, "_get_daily_mood", lambda salt="": "melancholy"), \
             mock.patch.object(pc, "_mood_affinity_multiplier", lambda key: 0.8), \
             mock.patch.object(pc, "_mood_label", lambda key, lang="ja": "melancholy"), \
             mock.patch.object(pc, "_mood_emoji", lambda key: "🌧"):
            out = self._run(["/mood"], m)
        self.assertTrue(any("-20" in line for line in out),
                        f"Expected -20% in output; got: {out}")


class RecapCommandTests(unittest.TestCase):
    """/recap shows today's conversation summary and recent exchanges."""

    def _run(self, inputs, conv_log=None):
        import persona_cli as pc
        from persona import Persona
        from mood import MoodTracker
        out = []
        it = iter(inputs + ["/quit"])
        pc.run_chat(
            persona=Persona.from_dict({"name": "T"}),
            input_fn=lambda _: next(it),
            output_fn=out.append,
            greet=False,
            mood=MoodTracker(affinity=50),
            conv_log=conv_log,
        )
        return out

    def test_recap_no_crash_without_conv_log(self):
        """/recap must not crash when conversation log is None."""
        out = self._run(["/recap"], conv_log=None)
        # Should produce at least one output line
        self.assertTrue(len(out) > 0)

    def test_recap_shows_summary_when_summary_greeting_available(self):
        """/recap calls _summary_greeting and outputs its result."""
        from unittest import mock
        import persona_cli as pc

        out = []
        it = iter(["/recap", "/quit"])
        with mock.patch.object(pc, "_summary_greeting",
                               lambda lang="ja": "TODAY_SUMMARY_TEXT"):
            pc.run_chat(
                persona=__import__("persona").Persona.from_dict({"name": "T"}),
                input_fn=lambda _: next(it),
                output_fn=out.append,
                greet=False,
                mood=__import__("mood").MoodTracker(affinity=50),
                conv_log=None,
            )
        self.assertTrue(any("TODAY_SUMMARY_TEXT" in line for line in out))

    def test_recap_shows_no_data_message_when_empty(self):
        """/recap prints a fallback when no data is available."""
        from unittest import mock
        import persona_cli as pc

        out = []
        it = iter(["/recap", "/quit"])
        with mock.patch.object(pc, "_summary_greeting", lambda lang="ja": ""):
            pc.run_chat(
                persona=__import__("persona").Persona.from_dict({"name": "T"}),
                input_fn=lambda _: next(it),
                output_fn=out.append,
                greet=False,
                mood=__import__("mood").MoodTracker(affinity=50),
                conv_log=None,
            )
        recap_output = [l for l in out if "今日" in l or "No conv" in l or "記録" in l]
        self.assertTrue(len(recap_output) > 0,
                        f"Expected fallback message; got: {out}")

    def test_recap_shows_recent_exchanges_from_log(self):
        """/recap displays the last 3 conversation entries from the log."""
        from unittest import mock
        import persona_cli as pc

        class _FakeLog:
            def recent(self, n):
                return [
                    {"event_type": "user_comment",
                     "details": {"text": "こんにちは"}},
                    {"event_type": "avatar_reply",
                     "details": {"text": "やっほー！"}},
                ]

        out = []
        it = iter(["/recap", "/quit"])
        with mock.patch.object(pc, "_summary_greeting", lambda lang="ja": ""):
            pc.run_chat(
                persona=__import__("persona").Persona.from_dict({"name": "T"}),
                input_fn=lambda _: next(it),
                output_fn=out.append,
                greet=False,
                mood=__import__("mood").MoodTracker(affinity=50),
                conv_log=_FakeLog(),
            )
        self.assertTrue(any("こんにちは" in l for l in out),
                        f"Expected recent exchange in output; got: {out}")
        self.assertTrue(any("やっほー" in l for l in out))


class CallemeBirthdayLoggingTests(unittest.TestCase):
    """/callme and /birthday commands log their exchange to conv_log."""

    def _run(self, inputs, profile=None, conv_log=None):
        from conversation_log import ConversationLog
        from user_profile import UserProfile
        import tempfile, os
        d = _Driver(inputs)
        tmp = tempfile.mkdtemp()
        try:
            log = conv_log or ConversationLog(os.path.join(tmp, "c.jsonl"))
            prof = profile or UserProfile()
            import persona_cli as pc
            pc.run_chat(
                persona=_persona(), conv_log=log, profile=prof,
                input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
            )
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)
        return d.out, log

    def _avatar_texts(self, log):
        from conversation_log import EVENT_AVATAR_REPLY
        return [e.get("details", {}).get("text", e.get("text", ""))
                for e in log.recent(20)
                if e.get("event_type") == EVENT_AVATAR_REPLY]

    def test_callme_logs_name_confirmation(self):
        """After /callme Taro, the log has an avatar reply mentioning Taro."""
        from conversation_log import ConversationLog
        import tempfile, os
        tmp = tempfile.mkdtemp()
        try:
            log = ConversationLog(os.path.join(tmp, "c.jsonl"))
            self._run(["/callme Taro"], conv_log=log)
            avatar_texts = self._avatar_texts(log)
            self.assertTrue(any("Taro" in t for t in avatar_texts),
                            f"Expected Taro in log; got: {avatar_texts}")
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)

    def test_birthday_logs_date_confirmation(self):
        """After /birthday 06-15, the log has an avatar reply mentioning 06-15."""
        from conversation_log import ConversationLog
        import tempfile, os
        tmp = tempfile.mkdtemp()
        try:
            log = ConversationLog(os.path.join(tmp, "c.jsonl"))
            self._run(["/birthday 06-15"], conv_log=log)
            avatar_texts = self._avatar_texts(log)
            self.assertTrue(any("06-15" in t for t in avatar_texts),
                            f"Expected 06-15 in log; got: {avatar_texts}")
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)

    def test_callme_without_arg_does_not_log(self):
        """/callme with no arg shows usage and does not log an avatar reply."""
        from conversation_log import ConversationLog
        import tempfile, os
        tmp = tempfile.mkdtemp()
        try:
            log = ConversationLog(os.path.join(tmp, "c.jsonl"))
            self._run(["/callme"], conv_log=log)
            avatar_texts = self._avatar_texts(log)
            self.assertEqual(avatar_texts, [])
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)


class LikeForgetLoggingTests(unittest.TestCase):
    """/like and /forget commands log their exchange to conv_log for /recap and /search."""

    def _run(self, inputs, profile=None, conv_log=None):
        from conversation_log import ConversationLog
        import tempfile, os
        d = _Driver(inputs)
        tmp = tempfile.mkdtemp()
        try:
            log = conv_log or ConversationLog(os.path.join(tmp, "c.jsonl"))
            import persona_cli as pc
            pc.run_chat(
                persona=_persona(), conv_log=log, profile=profile,
                input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
            )
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)
        return d.out, log

    def _profile(self):
        from user_profile import UserProfile
        return UserProfile()

    def _avatar_texts(self, log):
        from conversation_log import EVENT_AVATAR_REPLY
        return [e.get("details", {}).get("text", e.get("text", ""))
                for e in log.recent(20)
                if e.get("event_type") == EVENT_AVATAR_REPLY]

    def test_like_logs_to_conversation(self):
        """After /like アニメ, the conversation log has an avatar reply about アニメ."""
        from conversation_log import ConversationLog
        import tempfile, os
        tmp = tempfile.mkdtemp()
        try:
            log = ConversationLog(os.path.join(tmp, "c.jsonl"))
            self._run(["/like アニメ"], profile=self._profile(), conv_log=log)
            avatar_texts = self._avatar_texts(log)
            self.assertTrue(any("アニメ" in t for t in avatar_texts),
                            f"Expected アニメ in log; got: {avatar_texts}")
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)

    def test_forget_logs_to_conversation(self):
        """After /forget ゲーム, the conversation log has an avatar reply about ゲーム."""
        from conversation_log import ConversationLog
        from user_profile import UserProfile
        import tempfile, os
        tmp = tempfile.mkdtemp()
        try:
            prof = UserProfile()
            prof.add_interest("ゲーム")
            log = ConversationLog(os.path.join(tmp, "c.jsonl"))
            self._run(["/forget ゲーム"], profile=prof, conv_log=log)
            avatar_texts = self._avatar_texts(log)
            self.assertTrue(any("ゲーム" in t for t in avatar_texts),
                            f"Expected ゲーム in log; got: {avatar_texts}")
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)

    def test_like_without_arg_does_not_log(self):
        """/like with no argument shows usage; nothing meaningful logged."""
        from conversation_log import ConversationLog
        import tempfile, os
        tmp = tempfile.mkdtemp()
        try:
            log = ConversationLog(os.path.join(tmp, "c.jsonl"))
            self._run(["/like"], profile=self._profile(), conv_log=log)
            avatar_texts = self._avatar_texts(log)
            # No avatar reply logged for bare /like
            self.assertEqual(avatar_texts, [])
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)

    def test_like_appears_in_recap(self):
        """Interest added via /like shows up when /recap is called."""
        from conversation_log import ConversationLog
        from user_profile import UserProfile
        import tempfile, os, unittest.mock as mock
        import persona_cli as pc
        tmp = tempfile.mkdtemp()
        try:
            log = ConversationLog(os.path.join(tmp, "c.jsonl"))
            prof = UserProfile()
            out1 = []
            it = iter(["/like 音楽", "/quit"])
            with mock.patch.object(pc, "_summary_greeting", lambda lang="ja": ""):
                pc.run_chat(
                    persona=_persona(), conv_log=log, profile=prof,
                    input_fn=lambda _: next(it),
                    output_fn=out1.append, greet=False,
                    mood=__import__("mood").MoodTracker(affinity=50),
                )
            out2 = []
            it2 = iter(["/recap", "/quit"])
            with mock.patch.object(pc, "_summary_greeting", lambda lang="ja": ""):
                pc.run_chat(
                    persona=_persona(), conv_log=log, profile=prof,
                    input_fn=lambda _: next(it2),
                    output_fn=out2.append, greet=False,
                    mood=__import__("mood").MoodTracker(affinity=50),
                )
            self.assertTrue(any("音楽" in l for l in out2),
                            f"Expected 音楽 in /recap output; got: {out2}")
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)


class GiftLoggingTests(unittest.TestCase):
    """/gift logs the avatar's reply exchange to conv_log."""

    def _avatar_texts(self, log):
        from conversation_log import EVENT_AVATAR_REPLY
        return [e.get("details", {}).get("text", e.get("text", ""))
                for e in log.recent(20)
                if e.get("event_type") == EVENT_AVATAR_REPLY]

    def _make_log(self):
        import tempfile, os
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "c.jsonl")
        from conversation_log import ConversationLog
        return ConversationLog(path), tmp

    def test_gift_logs_avatar_reply(self):
        """/gift with a known item logs the avatar's reaction text."""
        from unittest import mock
        import persona_cli as pc

        log, tmp = self._make_log()
        try:
            # Stub lookup_gift to return (bonus=5.0, reply="GIFT_REPLY")
            with mock.patch.object(pc, "_lookup_gift",
                                   lambda item, lang="ja", level=None: (5.0, "GIFT_REPLY")), \
                 mock.patch.object(pc, "_lookup_gift_key",
                                   lambda item, lang="ja": "flower"):
                it = iter(["/gift flower", "/quit"])
                pc.run_chat(
                    persona=_persona(), conv_log=log,
                    input_fn=lambda _: next(it),
                    output_fn=lambda _: None, greet=False,
                )
            avatar_texts = self._avatar_texts(log)
            self.assertTrue(any("GIFT_REPLY" in t for t in avatar_texts),
                            f"Expected GIFT_REPLY in log; got: {avatar_texts}")
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)

    def test_gift_list_does_not_log(self):
        """/gift list (catalog display) does not create a log entry."""
        import persona_cli as pc
        log, tmp = self._make_log()
        try:
            it = iter(["/gift list", "/quit"])
            pc.run_chat(
                persona=_persona(), conv_log=log,
                input_fn=lambda _: next(it),
                output_fn=lambda _: None, greet=False,
            )
            avatar_texts = self._avatar_texts(log)
            self.assertEqual(avatar_texts, [])
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)

    def test_gift_unknown_item_does_not_log(self):
        """Unknown gift item shows an error but does not log a gift reply."""
        from unittest import mock
        import persona_cli as pc
        log, tmp = self._make_log()
        try:
            with mock.patch.object(pc, "_lookup_gift",
                                   lambda item, lang="ja", level=None: None):
                it = iter(["/gift unknown_xyz", "/quit"])
                pc.run_chat(
                    persona=_persona(), conv_log=log,
                    input_fn=lambda _: next(it),
                    output_fn=lambda _: None, greet=False,
                )
            avatar_texts = self._avatar_texts(log)
            self.assertEqual(avatar_texts, [])
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)


class FullReplyLoggingTests(unittest.TestCase):
    """run_chat() logs the fully-composed reply including hurt, milestone, and follow-up."""

    def _avatar_texts(self, log):
        from conversation_log import EVENT_AVATAR_REPLY
        return [e.get("details", {}).get("text", e.get("text", ""))
                for e in log.recent(20)
                if e.get("event_type") == EVENT_AVATAR_REPLY]

    def test_hurt_message_is_logged(self):
        """When hurt_msg overrides the normal reply, the logged text is the hurt message."""
        from unittest import mock
        import persona_cli as pc
        from mood import MoodTracker
        import tempfile, os
        from conversation_log import ConversationLog

        tmp = tempfile.mkdtemp()
        try:
            log = ConversationLog(os.path.join(tmp, "c.jsonl"))
            tracker = MoodTracker(affinity=80.0, interactions=1, negative_delta=6.0)
            # Stub _check_hurt_event to always return a fixed message
            with mock.patch.object(pc, "_check_hurt_event",
                                   lambda delta, lang="ja": "HURT_REPLY" if delta < -3 else ""):
                it = iter(["嫌い うざい ばか", "/quit"])
                pc.run_chat(
                    persona=_persona(), conv_log=log, mood=tracker,
                    input_fn=lambda _: next(it),
                    output_fn=lambda _: None, greet=False,
                )
            avatar_texts = self._avatar_texts(log)
            self.assertTrue(any("HURT_REPLY" in t for t in avatar_texts),
                            f"Expected HURT_REPLY in log; got: {avatar_texts}")
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)

    def test_follow_up_question_included_in_log(self):
        """Follow-up question appended to reply is captured in the logged text."""
        from unittest import mock
        import persona_cli as pc
        import tempfile, os
        from conversation_log import ConversationLog

        data = {
            "name": "Mimi", "default_lang": "en",
            "responses": {"en": {
                "rules": [{"keywords": ["hello"], "replies": ["HI"]}],
                "fallback": ["FB"],
                "follow_up": ["FOLLOW_Q"],
            }},
        }
        persona = __import__("persona").Persona.from_dict(data, lang="en")
        tmp = tempfile.mkdtemp()
        try:
            log = ConversationLog(os.path.join(tmp, "c.jsonl"))
            n = pc._FOLLOW_UP_EVERY
            it = iter(["hello"] * n + ["/quit"])
            pc.run_chat(
                persona=persona, conv_log=log,
                input_fn=lambda _: next(it),
                output_fn=lambda _: None, greet=False,
            )
            avatar_texts = self._avatar_texts(log)
            self.assertTrue(any("FOLLOW_Q" in t for t in avatar_texts),
                            f"Expected FOLLOW_Q in logged text; got: {avatar_texts}")
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)

    def test_normal_reply_still_logged_without_extras(self):
        """Without hurt/milestone/follow-up, the plain reply is still logged."""
        import tempfile, os
        from conversation_log import ConversationLog
        import persona_cli as pc

        tmp = tempfile.mkdtemp()
        try:
            log = ConversationLog(os.path.join(tmp, "c.jsonl"))
            it = iter(["hello", "/quit"])
            pc.run_chat(
                persona=_persona(), conv_log=log,
                input_fn=lambda _: next(it),
                output_fn=lambda _: None, greet=False,
            )
            avatar_texts = self._avatar_texts(log)
            self.assertTrue(any("HI" in t for t in avatar_texts),
                            f"Expected HI in log; got: {avatar_texts}")
        finally:
            import shutil; shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
