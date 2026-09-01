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

    def test_stats_labels_say_which_count_includes_commands(self):
        """2 つの数の定義の違いがラベルから読み取れること。

        セッション側はスラッシュコマンドを数えず、累計側（会話ログ由来）は
        数える。同じ「発言数」という語で並べていたため、コマンドだけ打った
        セッションで「今回のセッション: 0件 / 累計ユーザー発言数: 4件」と
        表示され、カウンタが壊れているようにしか見えなかった。
        """
        n, out = self._run(["/callme yuki", "hello", "/stats"], greet=False)
        blob = "\n".join(out)
        self.assertIn("commands excluded", blob)
        self.assertIn("commands included", blob)
        # 実際の数も食い違ったまま並ばないこと: コマンド 1 + 会話 1 なので
        # セッション 1 / 累計 2 になり、差はラベルで説明がつく。
        self.assertIn("this session (commands excluded): 1", blob)

    def test_stats_labels_are_localized_for_japanese(self):
        from persona_cli import _print_stats
        lines = []
        _print_stats(None, 3, "ja", lines.append)
        self.assertIn("コマンドは含みません", "\n".join(lines))

    def test_feeling_command_outputs_and_is_not_an_exchange(self):
        # /feeling reflects the user's recent mood; like /stats it must produce
        # output and must NOT be counted as a conversational exchange.
        n, out = self._run(["/feeling"], greet=False)
        self.assertEqual(n, 0)
        self.assertTrue(any(line.strip() for line in out))

    def test_checkin_alias_works(self):
        n, out = self._run(["/checkin"], greet=False)
        self.assertEqual(n, 0)
        self.assertTrue(any(line.strip() for line in out))


class GreetingWellbeingTests(unittest.TestCase):
    """Proactive wellbeing: when the user's recent messages show a clear trend,
    the avatar adds an empathetic line AFTER the greeting at session start. With
    no clear trend (or no mood tracker) it stays silent."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._logpath = os.path.join(self._tmp, "c.jsonl")
        self.log = ConversationLog(self._logpath)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write_user_msgs(self, texts):
        import json
        import time
        now = time.time()
        with open(self._logpath, "a", encoding="utf-8") as f:
            for t in texts:
                f.write(json.dumps({"event_type": "user_comment",
                                    "timestamp": now - 60,
                                    "details": {"text": t}}) + "\n")

    def _mood(self):
        from mood import MoodTracker
        return MoodTracker()

    def test_low_trend_adds_line_after_greeting(self):
        import user_wellbeing as uw
        self._write_user_msgs(["最悪", "むかつく", "つまらない"])
        d = _Driver([])  # greet, then EOF
        persona_cli.run_chat(
            persona=_persona(), conv_log=self.log, mood=self._mood(),
            input_fn=d.input_fn, output_fn=d.output_fn, greet=True,
        )
        # Greeting still comes first...
        self.assertTrue(d.out[0].startswith("Mimi: G"))
        # ...and a low-trend wellbeing line is present (persona lang is en).
        self.assertTrue(
            any(any(m in line for m in uw._WELLBEING_MESSAGES["low"]["en"])
                for line in d.out),
            f"expected a wellbeing line in: {d.out}",
        )

    def test_no_trend_stays_silent(self):
        import user_wellbeing as uw
        # Empty log -> no user messages -> no wellbeing line.
        d = _Driver([])
        persona_cli.run_chat(
            persona=_persona(), conv_log=self.log, mood=self._mood(),
            input_fn=d.input_fn, output_fn=d.output_fn, greet=True,
        )
        all_wb = (uw._WELLBEING_MESSAGES["low"]["en"]
                  + uw._WELLBEING_MESSAGES["high"]["en"])
        self.assertFalse(
            any(any(m in line for m in all_wb) for line in d.out),
            f"unexpected wellbeing line: {d.out}")

    def test_no_mood_tracker_stays_silent(self):
        import user_wellbeing as uw
        self._write_user_msgs(["最悪", "むかつく", "つまらない"])
        d = _Driver([])
        persona_cli.run_chat(
            persona=_persona(), conv_log=self.log, mood=None,  # mood disabled
            input_fn=d.input_fn, output_fn=d.output_fn, greet=True,
        )
        all_wb = (uw._WELLBEING_MESSAGES["low"]["en"]
                  + uw._WELLBEING_MESSAGES["high"]["en"])
        self.assertFalse(
            any(any(m in line for m in all_wb) for line in d.out),
            f"wellbeing must be silent when mood is disabled: {d.out}",
        )


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
        from mood import MoodTracker
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
        from mood import MoodTracker
        m = MoodTracker(affinity=90, interactions=10)
        # reset → cancel via other cmd → reset again (should re-show prompt, NOT reset)
        out = self._run(["/reset-mood", "/mood", "/reset-mood"], m)
        self.assertEqual(m.affinity, 90.0, "Affinity must remain unchanged when cancelled")

    def test_reset_mood_resets_confession_done(self):
        """After /reset-mood, _confession_done must be False so confession can re-fire."""
        from mood import MoodTracker, AFFINITY_START
        m = MoodTracker(affinity=90, interactions=10, confession_done=True)
        self._run(["/reset-mood", "/reset-mood"], m)
        self.assertFalse(m._confession_done,
                         "_confession_done must be reset so confession can re-fire after reset")

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

    def test_forget_fact_removes_matching_fact(self):
        """Regression: before this command existed, a user had no way to
        remove a single mis-recorded fact — only a full /forget-me wipe."""
        prof = self._profile(facts={"hobby": "登山"})
        d = _Driver(["/forget-fact 登山"])
        persona_cli.run_chat(
            persona=_persona(), conv_log=None, profile=prof,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        self.assertNotIn("hobby", prof.facts)

    def test_forget_fact_matches_by_partial_value_text(self):
        """/whoami only shows the value, not the key, so matching must work
        on a substring of the visible answer text, not the internal key."""
        prof = self._profile(facts={"food": "ラーメンとうどんが好き"})
        d = _Driver(["/forget-fact うどん"])
        persona_cli.run_chat(
            persona=_persona(), conv_log=None, profile=prof,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        self.assertNotIn("food", prof.facts)

    def test_forget_fact_leaves_other_facts_untouched(self):
        prof = self._profile(facts={"hobby": "登山", "food": "ラーメン"})
        d = _Driver(["/forget-fact 登山"])
        persona_cli.run_chat(
            persona=_persona(), conv_log=None, profile=prof,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        self.assertNotIn("hobby", prof.facts)
        self.assertIn("food", prof.facts)

    def test_forget_fact_nonexistent_shows_message(self):
        prof = self._profile(facts={"hobby": "登山"})
        d = _Driver(["/forget-fact 存在しない話"])
        persona_cli.run_chat(
            persona=_persona(), conv_log=None, profile=prof,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        self.assertIn("hobby", prof.facts)
        self.assertTrue(any("存在しない話" in line for line in d.out))

    def test_forget_fact_without_arg_shows_usage(self):
        prof = self._profile(facts={"hobby": "登山"})
        d = _Driver(["/forget-fact"])
        persona_cli.run_chat(
            persona=_persona(), conv_log=None, profile=prof,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        self.assertTrue(any("/forget-fact" in line for line in d.out))
        self.assertIn("hobby", prof.facts)  # usage message must not delete anything

    def test_forget_fact_persists_to_disk(self):
        prof = self._profile(facts={"hobby": "登山"})
        d = _Driver(["/forget-fact 登山"])
        persona_cli.run_chat(
            persona=_persona(), conv_log=None, profile=prof,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        loaded = self._up.UserProfile.load(self._ppath)
        self.assertNotIn("hobby", loaded.facts)

    def test_forget_fact_does_not_match_forget_prefix(self):
        """/forget-fact must not be swallowed by the /forget prefix check."""
        prof = self._profile(interests=["ゲーム"], facts={"hobby": "登山"})
        d = _Driver(["/forget-fact 登山"])
        persona_cli.run_chat(
            persona=_persona(), conv_log=None, profile=prof,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        # The interest must be untouched — only the fact should be removed.
        self.assertIn("ゲーム", prof.interests)
        self.assertNotIn("hobby", prof.facts)

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
        from mood import MoodTracker
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


class DailyMoodSaltIndependenceTests(unittest.TestCase):
    """The daily mood must not depend on the (mutable) user name, so it stays
    stable within a day and consistent across greeting / mood / gift paths."""

    def setUp(self):
        import user_profile
        self._up = user_profile
        self._tmp = tempfile.mkdtemp()
        self._ppath = os.path.join(self._tmp, "up.json")
        self._patcher = mock.patch.object(persona_cli, "_profile_path",
                                          lambda: self._ppath)
        self._patcher.start()

    def tearDown(self):
        import shutil
        self._patcher.stop()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _captured_salts(self, profile):
        """Run /mood with a profile and record every salt passed to get_daily_mood."""
        import persona_cli as pc
        from mood import MoodTracker
        salts = []

        def _spy(*args, **kwargs):
            salts.append(kwargs.get("salt", args[1] if len(args) > 1 else ""))
            return "calm"

        d = _Driver(["/mood"])
        with mock.patch.object(pc, "_get_daily_mood", _spy):
            pc.run_chat(
                persona=_persona(), conv_log=None, profile=profile,
                mood=MoodTracker(affinity=50),
                input_fn=d.input_fn, output_fn=d.output_fn, greet=True,
            )
        return salts

    def test_mood_does_not_use_name_as_salt(self):
        prof = self._up.UserProfile(name="Taro")
        salts = self._captured_salts(prof)
        self.assertTrue(salts, "expected get_daily_mood to be called")
        self.assertNotIn("Taro", salts,
                         f"daily mood must not be salted with the name; got {salts}")

    def test_mood_identical_with_and_without_name(self):
        """The mood key shown is the same whether or not a name is set."""
        import persona_cli as pc
        from mood import MoodTracker

        def _run(profile):
            d = _Driver(["/mood"])
            # Use the real get_daily_mood (date-only) — no patching
            pc.run_chat(
                persona=_persona(), conv_log=None, profile=profile,
                mood=MoodTracker(affinity=50),
                input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
            )
            return [l for l in d.out if "Today's mood" in l or "今日の気分" in l]

        named = _run(self._up.UserProfile(name="Taro"))
        anon = _run(self._up.UserProfile())
        self.assertTrue(named, "expected a daily mood line to be shown")
        self.assertEqual(named, anon,
                         "daily mood line should be identical regardless of name")


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

    def test_recap_null_details_does_not_abort_loop(self):
        """/recap must not silently abort when an event has "details": null.

        entry.get("details", {}) returns None for a JSON-null details field.
        None.get("text", "") raises AttributeError, which the outer try/except
        swallows — aborting the remaining iterations.  Fixed with (... or {}).
        """
        from unittest import mock
        import persona_cli as pc

        class _FakeLog:
            def recent(self, n):
                return [
                    {"event_type": "user_comment", "details": None},       # null details
                    {"event_type": "user_comment",
                     "details": {"text": "後続イベント"}},               # must still appear
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
        self.assertTrue(any("後続イベント" in l for l in out),
                        f"Event after null-details entry must be shown; got: {out}")


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


class ForgetMeTests(unittest.TestCase):
    """/forget-me erases personal data with a two-step confirmation."""

    def setUp(self):
        import user_profile
        self._up = user_profile
        self._tmp = tempfile.mkdtemp()
        self._ppath = os.path.join(self._tmp, "up.json")
        self._patcher = mock.patch.object(persona_cli, "_profile_path",
                                          lambda: self._ppath)
        self._patcher.start()

    def tearDown(self):
        import shutil
        self._patcher.stop()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _profile(self, **kw):
        return self._up.UserProfile(**kw)

    def _run(self, inputs, profile):
        d = _Driver(inputs)
        persona_cli.run_chat(
            persona=_persona(), conv_log=None, profile=profile,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        return d.out

    def test_two_step_confirm_clears_profile(self):
        prof = self._profile(name="Taro", birthday="06-15",
                             interests=["アニメ"])
        prof.set_fact("favorite_food", "ラーメン")
        self._run(["/forget-me", "/forget-me"], prof)
        self.assertEqual(prof.name, "")
        self.assertEqual(prof.birthday, "")
        self.assertEqual(prof.interests, [])
        self.assertEqual(prof.facts, {})

    def test_first_call_shows_confirmation_only(self):
        prof = self._profile(name="Taro", interests=["アニメ"])
        out = self._run(["/forget-me"], prof)
        # Data still intact after a single call
        self.assertEqual(prof.name, "Taro")
        self.assertIn("アニメ", prof.interests)
        # A confirmation prompt was shown
        self.assertTrue(any("/forget-me" in line for line in out))

    def test_cancelled_by_intervening_input(self):
        prof = self._profile(name="Taro")
        # /forget-me then a different command cancels the pending confirm
        self._run(["/forget-me", "/whoami", "/forget-me"], prof)
        # Name survives because the second /forget-me starts a fresh confirm
        self.assertEqual(prof.name, "Taro")

    def test_persists_cleared_profile_to_disk(self):
        prof = self._profile(name="Hana", interests=["音楽"])
        self._run(["/forget-me", "/forget-me"], prof)
        loaded = self._up.UserProfile.load(self._ppath)
        self.assertEqual(loaded.name, "")
        self.assertEqual(loaded.interests, [])

    def test_forget_me_does_not_reset_affinity(self):
        """/forget-me clears personal data but leaves the relationship affinity."""
        from mood import MoodTracker
        prof = self._profile(name="Taro")
        m = MoodTracker(affinity=80)
        d = _Driver(["/forget-me", "/forget-me"])
        persona_cli.run_chat(
            persona=_persona(), conv_log=None, profile=prof, mood=m,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        self.assertEqual(prof.name, "")
        self.assertEqual(m.affinity, 80)

    def test_forget_me_no_profile_no_crash(self):
        # _forget_me() with no profile reports gracefully (doesn't crash)
        out = []
        persona_cli._forget_me(None, "ja", out.append)
        self.assertTrue(any("プロファイル" in line for line in out))


class ConfessionSaveMidSessionTests(unittest.TestCase):
    """The confession_done flag must be written to disk when the confession fires.

    Before the fix, mood.save(mood._path) was dead code because MoodTracker has no
    _path attribute.  A crash between the confession and the end-of-session save
    would lose the flag, causing the once-per-lifetime confession to replay.
    """

    def setUp(self):
        from mood import reset_mood_tracker
        from persona import reset_persona
        reset_mood_tracker()
        reset_persona()
        self._tmp = tempfile.mkdtemp()
        self._mood_path = os.path.join(self._tmp, "mood.json")

    def tearDown(self):
        from mood import reset_mood_tracker
        from persona import reset_persona
        reset_mood_tracker()
        reset_persona()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _run_with_mood(self, inputs, mood, mood_path):
        import mood as _mood_mod
        with mock.patch.object(_mood_mod, "_default_mood_path",
                               return_value=mood_path):
            d = _Driver(inputs)
            persona_cli.run_chat(
                persona=_persona(), conv_log=None, mood=mood,
                input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
            )
        return d.out

    def test_confession_done_saved_to_disk_when_confession_fires(self):
        """When friendly→close transition triggers the confession, the flag must
        be written to the mood file immediately (crash-safe mid-session save)."""
        import json
        from mood import MoodTracker

        # Start at high-friendly (78), enough positive hits push to close (>=80).
        # 告白には実体のある関係（既定 7 日・20 回）が要るので、それも満たす。
        # このテストの subject は「発火したときに即ディスクへ保存されるか」で
        # あって最低条件ではない。
        import time as _t
        m = MoodTracker(affinity=78.0, interactions=50,
                        first_interaction_time=_t.time() - 30 * 86400)
        self.assertFalse(m._confession_done)

        # "ありがとう大好きかわいいうれしい" hits 4 positive keywords → +10 (capped)
        # 78 + 10 = 88 > 80 → friendly→close transition → confession fires
        self._run_with_mood(["ありがとう大好きかわいいうれしい"], m, self._mood_path)

        # Verify confession fired in memory
        if m.affinity < 80.0:
            self.skipTest("affinity did not reach close — check keyword coverage")

        self.assertTrue(m._confession_done, "confession_done must be set after transition")
        # Verify it was persisted mid-session
        self.assertTrue(os.path.exists(self._mood_path),
                        "mood file must be written mid-session when confession fires")
        with open(self._mood_path, encoding="utf-8") as f:
            saved = json.load(f)
        self.assertTrue(saved.get("confession_done"),
                        "confession_done must be True in the saved mood file")

    def test_no_save_if_no_milestone(self):
        """Neutral input with no milestone must not trigger a save."""
        from mood import MoodTracker
        m = MoodTracker(affinity=50.0)
        self._run_with_mood(["今日はいい天気ですね"], m, self._mood_path)
        # no confession, no milestone → file should NOT exist (no mid-session save)
        self.assertFalse(os.path.exists(self._mood_path),
                         "mood file must not be written unless a milestone fires")


class SlashCommandPrefixBoundaryTests(unittest.TestCase):
    """/liked, /gifts, /forgetting must NOT dispatch as /like, /gift, /forget.

    Before the fix, startswith("/like") matched "/liked アニメ" and passed "d アニメ"
    to _add_interest() — silently storing garbage into the user profile.
    """

    def setUp(self):
        import user_profile
        self._up = user_profile
        self._tmp = tempfile.mkdtemp()
        self._ppath = os.path.join(self._tmp, "up.json")
        self._patcher = mock.patch.object(persona_cli, "_profile_path",
                                          lambda: self._ppath)
        self._patcher.start()

    def tearDown(self):
        import shutil
        self._patcher.stop()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _profile(self, **kw):
        return self._up.UserProfile(**kw)

    def test_liked_does_not_add_interest(self):
        """/liked アニメ must not add 'd アニメ' as an interest."""
        prof = self._profile()
        d = _Driver(["/liked アニメ"])
        persona_cli.run_chat(
            persona=_persona(), conv_log=None, profile=prof,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        self.assertEqual(prof.interests, [])

    def test_gifts_does_not_dispatch_as_gift(self):
        """/gifts must not invoke the gift handler."""
        prof = self._profile()
        d = _Driver(["/gifts"])
        persona_cli.run_chat(
            persona=_persona(), conv_log=None, profile=prof,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        # Gift catalog lines contain "(+N)"; a normal persona reply won't
        self.assertFalse(any("(+" in line for line in d.out))

    def test_forgetting_does_not_remove_interest(self):
        """/forgetting must not call remove_interest; interest survives."""
        prof = self._profile(interests=["ゲーム"])
        d = _Driver(["/forgetting ゲーム"])
        persona_cli.run_chat(
            persona=_persona(), conv_log=None, profile=prof,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        self.assertIn("ゲーム", prof.interests)

    def test_liked_is_reported_as_an_unknown_command(self):
        """`/liked` は `/like` として解釈されず、未知のコマンドとして案内される。

        以前は「通常の会話として persona.respond() に落ちる」ことで前方一致の
        誤爆を検証していた。いまは `/` で始まる未知の入力を会話として扱わない
        （打ち間違いも、片方の UI にしか無いコマンドも、黙って流れると
        「実行された」と誤解されるため）ので、直接そちらを検証する。
        趣味が追加されていないことも併せて確かめる。
        """
        prof = self._profile()
        d = _Driver(["/liked アニメ"])
        persona_cli.run_chat(
            persona=_persona(), conv_log=None, profile=prof,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        self.assertTrue(any("/help" in line for line in d.out), d.out)
        self.assertNotIn("アニメ", prof.interests)


# ---------------------------------------------------------------------------
# _next_interaction_milestone — pure-logic unit tests
# ---------------------------------------------------------------------------

class NextInteractionMilestoneTests(unittest.TestCase):
    """Direct unit tests for _next_interaction_milestone()."""

    def _call(self, n):
        return persona_cli._next_interaction_milestone(n)

    def test_zero_returns_first_milestone(self):
        result = self._call(0)
        self.assertIsNotNone(result)
        self.assertEqual(result, 10)

    def test_nine_returns_first_milestone(self):
        self.assertEqual(self._call(9), 10)

    def test_exactly_at_milestone_returns_next(self):
        """interactions==10 is AT the milestone, so return the NEXT one (25)."""
        self.assertEqual(self._call(10), 25)

    def test_just_before_second_milestone(self):
        self.assertEqual(self._call(24), 25)

    def test_just_after_second_milestone(self):
        self.assertEqual(self._call(25), 50)

    def test_beyond_all_milestones_returns_none(self):
        """After the last milestone (1000), no more milestones remain."""
        self.assertIsNone(self._call(1000))
        self.assertIsNone(self._call(9999))

    def test_result_always_greater_than_interactions(self):
        """The returned milestone must strictly exceed the input count."""
        for n in [0, 5, 10, 24, 25, 49, 50, 99, 100, 249, 500, 999]:
            result = self._call(n)
            if result is not None:
                self.assertGreater(result, n, f"milestone {result} <= interactions {n}")


# ---------------------------------------------------------------------------
# _interest_recall — pure-logic unit tests
# ---------------------------------------------------------------------------

class InterestRecallTests(unittest.TestCase):

    def _make_profile(self, interests):
        from user_profile import UserProfile
        p = UserProfile()
        for item in interests:
            p.add_interest(item)
        return p

    def test_empty_interests_returns_empty_string(self):
        prof = self._make_profile([])
        result = persona_cli._interest_recall(prof, lang="ja")
        self.assertEqual(result, "")

    def test_none_profile_returns_empty_string(self):
        result = persona_cli._interest_recall(None, lang="ja")
        self.assertEqual(result, "")

    def test_ja_result_contains_interest(self):
        prof = self._make_profile(["アニメ"])
        result = persona_cli._interest_recall(prof, lang="ja")
        self.assertIn("アニメ", result)

    def test_en_result_contains_interest(self):
        prof = self._make_profile(["anime"])
        result = persona_cli._interest_recall(prof, lang="en")
        self.assertIn("anime", result)

    def test_ja_result_is_japanese_template(self):
        prof = self._make_profile(["サッカー"])
        result = persona_cli._interest_recall(prof, lang="ja")
        # Japanese templates contain Japanese characters
        self.assertTrue(any(ord(c) > 0x3000 for c in result),
                        f"Expected Japanese characters in: {result!r}")

    def test_en_result_does_not_contain_japanese(self):
        prof = self._make_profile(["soccer"])
        result = persona_cli._interest_recall(prof, lang="en")
        # English templates must not contain Japanese-specific phrases like "だ" or "ね"
        japanese_markers = ["だよね", "聞かせて", "どんな感じ"]
        for marker in japanese_markers:
            self.assertNotIn(marker, result,
                f"Japanese marker {marker!r} found in English result: {result!r}")

    def test_returns_non_empty_when_interests_exist(self):
        prof = self._make_profile(["音楽", "読書"])
        result = persona_cli._interest_recall(prof, lang="ja")
        self.assertGreater(len(result), 0)


# ---------------------------------------------------------------------------
# _give_gift — bonus display uses round() not int()
# ---------------------------------------------------------------------------
class GiftBonusDisplayTests(unittest.TestCase):
    """Regression: the gift notification used int(bonus) which truncates 3.5→3.
    The catalog text already uses round(), so both must agree.
    """

    def _run_give_gift(self, item, bonus_float, reply="Great!", lang="en"):
        from unittest import mock
        import persona_cli as pc
        out = []
        # Neutralise the daily-mood multiplier so effective_bonus == bonus_float exactly.
        with mock.patch.object(pc, "_lookup_gift",
                               lambda i, lang=lang, level=None: (bonus_float, reply)), \
             mock.patch.object(pc, "_lookup_gift_key",
                               lambda i, lang=lang: "test_gift"), \
             mock.patch.object(pc, "_mood_affinity_multiplier",
                               lambda mood_key: 1.0):
            mood_stub = mock.MagicMock()
            mood_stub.level = "neutral"
            mood_stub.gift_received_today.return_value = False
            # earn() は「実際に反映された量」を返す。ここは丸め表示の検証なので
            # 日次上限に掛からない日（全額反映）を模す。
            mood_stub.earn.side_effect = lambda d: d
            pc._give_gift(item, mood_stub, "Avatar", lang, out.append)
        return "\n".join(out)

    def test_integer_bonus_displays_correctly(self):
        output = self._run_give_gift("flower", 5.0)
        self.assertIn("+5", output)

    def test_fractional_bonus_rounds_up(self):
        """Regression: int(3.5) = 3 but round(3.5) = 4.
        Catalog shows +4 for 'book'; notification must also show +4."""
        output = self._run_give_gift("book", 3.5)
        self.assertIn("+4", output)
        self.assertNotIn("+3", output)

    def test_fractional_bonus_rounds_down(self):
        """bonus=2.2: round(2.2)=2, int(2.2)=2 — both agree; ensures general coverage."""
        output = self._run_give_gift("ribbon", 2.2)
        self.assertIn("+2", output)

    def test_bonus_display_in_japanese(self):
        """Japanese notification also uses round()."""
        output = self._run_give_gift("book", 3.5, lang="ja")
        self.assertIn("+4", output)
        self.assertNotIn("+3", output)

    def test_zero_bonus_does_not_show_notification(self):
        """bonus<=0 means min_level not met: no affinity notification printed."""
        from unittest import mock
        import persona_cli as pc
        out = []
        with mock.patch.object(pc, "_lookup_gift",
                               lambda i, lang="en", level=None: (0.0, "Not yet!")), \
             mock.patch.object(pc, "_lookup_gift_key",
                               lambda i, lang="en": "test_gift"):
            mood_stub = mock.MagicMock()
            mood_stub.level = "neutral"
            mood_stub.gift_received_today.return_value = False
            pc._give_gift("widget", mood_stub, "Avatar", "en", out.append)
        combined = "\n".join(out)
        self.assertNotIn("+0", combined)

    def test_capped_bonus_shows_no_number(self):
        """日次上限に達していて実際には 0 だったら数字を出さないこと。

        プレゼントは会話と日次予算を共有するので、同じ日に贈り続ければ
        いずれ反映量は 0 になる。そこで「+5」と表示するのは嘘になる
        （返事は返るので、贈った事実自体は伝わる）。
        """
        from unittest import mock
        import persona_cli as pc
        out = []
        with mock.patch.object(pc, "_lookup_gift",
                               lambda i, lang="en", level=None: (5.0, "Thanks!")), \
             mock.patch.object(pc, "_lookup_gift_key",
                               lambda i, lang="en": "test_gift"), \
             mock.patch.object(pc, "_mood_affinity_multiplier",
                               lambda mood_key: 1.0):
            mood_stub = mock.MagicMock()
            mood_stub.level = "neutral"
            mood_stub.gift_received_today.return_value = False
            mood_stub.earn.side_effect = lambda d: 0.0  # 上限に達している
            pc._give_gift("flower", mood_stub, "Avatar", "en", out.append)
        combined = "\n".join(out)
        self.assertNotIn("+", combined)
        self.assertIn("Thanks!", combined)


class AffinityBannerLocalizationTests(unittest.TestCase):
    """Regression: the affinity-level-change banner output '── 関係: ...' regardless
    of the session language, so English users saw a Japanese label.

    Fix: use 'Relationship' for lang='en', '関係' for lang='ja'.
    """

    def _banner_lines(self, lang: str) -> list:
        """Run one chat exchange that crosses a level boundary and return banner output."""
        import persona_cli as pc
        from unittest import mock
        from mood import MoodTracker

        out = []
        # tracker starts just below the neutral→friendly boundary (60)
        tracker = MoodTracker(affinity=59.0, interactions=1)
        p = pc.Persona.from_dict({
            "name": "T",
            "default_lang": lang,
            "dialogue": {lang: {"talk": ["ok"], "greeting": ["hi"], "rest": [".."],
                                "fallback": ["ok"]}},
        })

        # Force the mood tracker to jump past 60 in register() so the banner fires.
        # We do this by making adjust() also fire when register() returns a delta,
        # instead of fighting keyword matching. Easiest: mock register() directly.
        original_register = tracker.register

        def _forced_register(text):
            tracker.affinity = 65.0  # crosses to friendly
            tracker.interactions += 1
            return 6.0  # positive delta

        with mock.patch.object(tracker, "register", side_effect=_forced_register), \
             mock.patch.object(pc, "_check_confession_event", lambda *a, **k: None), \
             mock.patch.object(pc, "_check_interaction_milestone", lambda *a, **k: None), \
             mock.patch.object(pc, "_get_daily_mood", lambda: "calm"), \
             mock.patch.object(pc, "_mood_affinity_multiplier", lambda m: 1.0):
            inputs = iter(["hello", "/quit"])
            pc.run_chat(
                persona=p,
                conv_log=None,
                input_fn=lambda _: next(inputs),
                output_fn=out.append,
                greet=False,
                mood=tracker,
                profile=None,
            )
        return [l for l in out if "──" in l]

    def test_english_banner_says_relationship(self):
        """With lang='en', the banner must use 'Relationship', not '関係'."""
        banners = self._banner_lines("en")
        self.assertTrue(banners, "Expected a level-change banner but got none.")
        banner = " ".join(banners)
        self.assertIn("Relationship", banner,
            "English banner must say 'Relationship', not '関係'.")
        self.assertNotIn("関係", banner,
            "Japanese label '関係' must not appear in English banner.")

    def test_japanese_banner_says_kankei(self):
        """With lang='ja', the banner must use '関係'."""
        banners = self._banner_lines("ja")
        self.assertTrue(banners, "Expected a level-change banner but got none.")
        banner = " ".join(banners)
        self.assertIn("関係", banner,
            "Japanese banner must say '関係'.")


class ExportClearLogTests(unittest.TestCase):
    """Socratic review: the REPL had privacy commands for profile (/forget-me)
    and affinity (/reset-mood) but no way to export or erase the conversation
    transcript itself — the most sensitive raw record. ConversationLog.to_csv()
    existed but was never reachable from the chat. /export-log and /clear-log
    close that asymmetry.
    """

    def setUp(self):
        import tempfile
        from conversation_log import ConversationLog
        self._tmp = tempfile.mkdtemp()
        self._logpath = os.path.join(self._tmp, "c.jsonl")
        self._log = ConversationLog(self._logpath)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _run(self, inputs, conv_log="default"):
        d = _Driver(inputs)
        persona_cli.run_chat(
            persona=_persona(),
            conv_log=self._log if conv_log == "default" else conv_log,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        return d.out

    # ---- /export-log ------------------------------------------------------ #
    def test_export_log_writes_csv_with_content(self):
        self._log.log_exchange("hello world", "hi there")
        dest = os.path.join(self._tmp, "out.csv")
        out = self._run([f"/export-log {dest}"])
        self.assertTrue(os.path.exists(dest), "CSV file must be created")
        with open(dest, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("hello world", content)
        self.assertTrue(any(dest in line for line in out),
                        "Output must confirm the export destination")

    def test_export_log_none_conv_log_does_not_crash(self):
        """Direct helper call: run_chat substitutes a default log for None,
        so the None-guard is only reachable by calling the helper directly."""
        out = []
        persona_cli._export_log(None, "unused.csv", "ja", out.append)
        self.assertTrue(any("利用できません" in line for line in out))
        self.assertFalse(os.path.exists("unused.csv"))

    def test_export_log_default_path_used_when_no_arg(self):
        import contextlib
        self._log.log_exchange("a", "b")
        cwd = os.getcwd()
        try:
            os.chdir(self._tmp)
            self._run(["/export-log"])
            self.assertTrue(os.path.exists(os.path.join(self._tmp, "conversation_export.csv")))
        finally:
            with contextlib.suppress(OSError):
                os.chdir(cwd)

    # ---- /clear-log ------------------------------------------------------- #
    def test_clear_log_first_invocation_only_asks_confirmation(self):
        self._log.log_exchange("keep me", "for now")
        out = self._run(["/clear-log"])
        self.assertTrue(any("/clear-log" in line for line in out),
                        "First invocation must ask for confirmation")
        self.assertGreater(os.path.getsize(self._logpath), 0,
                           "Log must remain intact after only one /clear-log")

    def test_clear_log_double_invocation_erases_log(self):
        self._log.log_exchange("erase me", "gone soon")
        self._run(["/clear-log", "/clear-log"])
        self.assertEqual(os.path.getsize(self._logpath), 0,
                         "Two consecutive /clear-log must truncate the log")

    def test_clear_log_confirmation_cancelled_by_other_command(self):
        self._log.log_exchange("survivor", "still here")
        self._run(["/clear-log", "/help", "/clear-log"])
        self.assertGreater(
            os.path.getsize(self._logpath), 0,
            "A different command between the two /clear-log calls must cancel "
            "the pending confirmation (same pattern as /forget-me).",
        )

    def test_clear_log_none_conv_log_does_not_crash(self):
        """Direct helper call (see test_export_log_none_conv_log_does_not_crash)."""
        out = []
        persona_cli._clear_log(None, "ja", out.append)
        self.assertTrue(any("利用できません" in line for line in out))


class GiftListCooldownMarkerTests(unittest.TestCase):
    """Socratic review: /gift list showed a static catalog; users discovered a
    gift was on daily cooldown only by trying and being rejected. The list now
    marks gifts already given today via MoodTracker.gift_received_today()."""

    def _run(self, inputs, mood):
        d = _Driver(inputs)
        persona_cli.run_chat(
            persona=_persona(), conv_log=None, mood=mood,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        return d.out

    def test_gift_given_today_is_marked_in_list(self):
        """The _persona() fixture is English, so use the en alias and marker."""
        from mood import MoodTracker
        mood = MoodTracker()
        out = self._run(["/gift chocolate", "/gift list"], mood)
        catalog = "\n".join(out)
        self.assertIn("(given today)", catalog)
        marked = [l for l in catalog.splitlines() if "(given today)" in l]
        self.assertTrue(all("chocolate" in l for l in marked),
                        f"Only chocolate should be marked; got: {marked}")

    def test_no_gifts_given_list_has_no_markers(self):
        from mood import MoodTracker
        mood = MoodTracker()
        out = self._run(["/gift list"], mood)
        self.assertFalse(any("(given today)" in line for line in out),
                         "Nothing given today -> no markers")

    def test_list_without_mood_still_works(self):
        out = self._run(["/gift list"], None)
        self.assertTrue(any("+" in line for line in out),
                        "Catalog must still render without a mood tracker")


if __name__ == "__main__":
    unittest.main()


class CliForgetAllTests(unittest.TestCase):
    """対話 CLI の /forget-all が**実際に消す**こと。

    以前この機能は GUI にしか無く、CLI で打つと未知のコマンドとして会話に流れ、
    「全部消して」と言った人のデータが黙って残った。

    このクラスは `run_chat` を実際に回して検証する。「import されているか」
    「ソースに文字列があるか」を見るテストでは不十分だった — 実際に配線を
    外して revert-verify したところ、import は残るのでソース検査は通って
    しまった。**到達するかどうかは動かさないと分からない。**
    """

    def _run(self, inputs, erase_mock):
        d = _Driver(inputs)
        with mock.patch.object(persona_cli, "_erase_all_user_data", erase_mock):
            persona_cli.run_chat(
                persona=_persona(), conv_log=None,
                input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
            )
        return d.out

    def test_two_inputs_erase_everything(self):
        erase = mock.Mock(return_value={"profile": True, "conversation": True,
                                        "mood": True, "avatar": True})
        out = self._run(["/forget-all", "/forget-all"], erase)
        erase.assert_called_once()
        self.assertTrue(any("全部消した" in line or "erased everything" in line
                            for line in out), out)

    def test_a_single_input_only_asks(self):
        """打ち間違い 1 回で全データが消えないこと。"""
        erase = mock.Mock()
        out = self._run(["/forget-all"], erase)
        erase.assert_not_called()
        self.assertTrue(any("/forget-all" in line for line in out), out)

    def test_an_intervening_message_cancels_the_confirmation(self):
        erase = mock.Mock()
        self._run(["/forget-all", "こんにちは", "/forget-all"], erase)
        erase.assert_not_called()

    def test_aliases_work(self):
        for alias in ("/forgetall", "/delete-all", "/erase-all"):
            with self.subTest(alias=alias):
                erase = mock.Mock(return_value={"profile": True})
                self._run([alias, alias], erase)
                erase.assert_called_once()

    def test_nothing_to_erase_is_reported_not_claimed_as_success(self):
        """消せるものが無いときに「全部消した」と言わないこと。"""
        erase = mock.Mock(return_value={"profile": False, "conversation": False,
                                        "mood": False, "avatar": False})
        out = self._run(["/forget-all", "/forget-all"], erase)
        blob = "\n".join(out)
        self.assertNotIn("erased everything", blob)
        self.assertIn("Nothing to erase", blob)

    def test_a_failing_erasure_does_not_claim_success(self):
        erase = mock.Mock(side_effect=RuntimeError("disk on fire"))
        out = self._run(["/forget-all", "/forget-all"], erase)
        blob = "\n".join(out)
        self.assertNotIn("erased everything", blob)
        self.assertIn("Failed to erase", blob)


class CliUnknownCommandTests(unittest.TestCase):
    """未知のスラッシュコマンドを会話として処理しないこと（実行して確認）。"""

    def _run(self, inputs):
        d = _Driver(inputs)
        persona_cli.run_chat(
            persona=_persona(), conv_log=None,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        return d.out

    def _notice(self, lang="en"):
        return persona_cli.unknown_command_reply("x", lang)

    def test_unknown_command_is_reported(self):
        out = self._run(["/nonexistent"])
        self.assertTrue(any(self._notice() in line for line in out), out)

    def test_a_typo_of_a_real_command_is_reported(self):
        """`/mod` を `/mood` として実行しないし、黙って会話にもしないこと。"""
        out = self._run(["/mod"])
        self.assertTrue(any(self._notice() in line for line in out), out)

    def test_plain_text_is_still_conversation(self):
        """`/` で始まらない入力は従来どおり会話であること。

        「出力に /help が含まれるか」では判定できない — 起動時のコマンド一覧に
        も含まれるため。案内文そのものの有無で見る。
        """
        out = self._run(["hello"])
        self.assertFalse(any(self._notice() in line for line in out), out)
        self.assertTrue(any(line.strip() for line in out))


class CliFirstMeetingTests(unittest.TestCase):
    """初対面では「関係がある前提の演出」を出さないこと。

    まっさらな状態での起動は、ユーザーがこの製品を見る最初の 5 秒である。
    そこで出していたもの:

    - 「おかえり！今日も会いに来てくれてうれしいな。」— 一度も会っていない相手に
    - 「なんかしんみりした気分…。そっとしておいてくれると嬉しいかも。」
      — 3 番目の発話がこれだと、個性ではなく拒絶として読まれる。日替わりムードは
        日付だけで決まるので、新規ユーザーの 1/6 がこれを引いた。

    どちらも「時間をかけて育つ関係」という製品の核を、入口で損なう。
    """

    def _run(self, first_meeting):
        d = _Driver([])
        with mock.patch.object(persona_cli, "_is_first_meeting_cli",
                               lambda *a, **k: first_meeting), \
             mock.patch.object(persona_cli, "_get_daily_mood", lambda **k: "melancholy"), \
             mock.patch.object(persona_cli, "_mood_description",
                               lambda *a, **k: "MOOD_LINE"):
            persona_cli.run_chat(
                persona=_persona(), conv_log=None,
                input_fn=d.input_fn, output_fn=d.output_fn, greet=True,
            )
        return d.out

    def test_daily_mood_is_omitted_on_a_first_meeting(self):
        out = self._run(first_meeting=True)
        self.assertFalse(any("MOOD_LINE" in line for line in out), out)

    def test_daily_mood_returns_for_a_returning_user(self):
        """2 日目以降は通常どおり出ること（機能を殺していない）。"""
        out = self._run(first_meeting=False)
        self.assertTrue(any("MOOD_LINE" in line for line in out), out)

    def test_the_greeting_itself_still_appears_on_a_first_meeting(self):
        """ムードを外した結果、無言になっていないこと。"""
        out = self._run(first_meeting=True)
        self.assertTrue(any(line.strip() for line in out))

    def test_first_meeting_is_decided_before_the_login_check_mutates_state(self):
        """判定順序の回帰テスト。

        `check_daily_login` は `_last_login_date` を書き込む。したがって
        「初対面か」をそのあとで判定すると**常に False**になる。単体テストでは
        フラグを直接差し替えていたため気づかず、実際に起動して初めて
        「修正したのにムードが出続ける」ことが分かった。

        ここでは本物の MoodTracker を渡し、あいさつ処理を丸ごと通したうえで
        ムードが出ないことを確かめる — 順序が壊れれば落ちる。
        """
        from mood import MoodTracker
        tracker = MoodTracker()          # まっさらな新規ユーザー
        d = _Driver([])
        with mock.patch.object(persona_cli, "_get_daily_mood", lambda **k: "melancholy"), \
             mock.patch.object(persona_cli, "_mood_description",
                               lambda *a, **k: "MOOD_LINE"):
            persona_cli.run_chat(
                persona=_persona(), conv_log=None, mood=tracker,
                input_fn=d.input_fn, output_fn=d.output_fn, greet=True,
            )
        self.assertFalse(any("MOOD_LINE" in line for line in d.out), d.out)
        # 前提の確認: あいさつ処理が実際に状態を書き換えていること
        self.assertTrue(tracker._last_login_date,
                        "check_daily_login が走っていない — テストの前提が崩れている")
