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
        self.assertTrue(any(line.startswith("You: hello") for line in d.out))
        self.assertTrue(any(line.startswith("Avatar: HI") for line in d.out))

    def test_history_empty_message(self):
        d = _Driver(["/history"])
        persona_cli.run_chat(
            persona=_persona(), conv_log=self.log,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False,
        )
        self.assertTrue(any("まだ会話履歴" in line for line in d.out))


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


if __name__ == "__main__":
    unittest.main()
