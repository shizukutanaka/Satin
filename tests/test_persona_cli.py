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


class MainEntryTests(unittest.TestCase):
    def test_main_no_greet_with_immediate_eof(self):
        # Patch input to raise EOF immediately; main() should return 0.
        import builtins
        orig = builtins.input
        builtins.input = lambda *a, **k: (_ for _ in ()).throw(EOFError())
        try:
            rc = persona_cli.main(["--no-greet", "--lang", "en"])
        finally:
            builtins.input = orig
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
