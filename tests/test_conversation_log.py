"""
Unit tests for conversation_log.ConversationLog — the conversation history
recorder that wires user comments and avatar replies into the existing
avatar event log (JSONL) toolchain.
"""
import json
import os
import queue
import sys
import tempfile
import unittest
from unittest import mock

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import conversation_log as _cl  # noqa: E402
from conversation_log import (  # noqa: E402
    ConversationLog,
    EVENT_AVATAR_REPLY,
    EVENT_USER_COMMENT,
    get_conversation_log,
    reset_conversation_log,
)


class _TmpLogBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.logfile = os.path.join(self._tmp, "events.jsonl")
        self.log = ConversationLog(self.logfile)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _read_lines(self):
        if not os.path.exists(self.logfile):
            return []
        with open(self.logfile, encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]


class LoggingTests(_TmpLogBase):
    def test_log_user_comment_writes_event(self):
        self.log.log_user_comment("こんにちは")
        events = self._read_lines()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], EVENT_USER_COMMENT)
        self.assertEqual(events[0]["details"]["text"], "こんにちは")
        self.assertIn("timestamp", events[0])

    def test_log_avatar_reply_records_target(self):
        self.log.log_avatar_reply("やっほー", to="こんにちは")
        events = self._read_lines()
        self.assertEqual(events[0]["event_type"], EVENT_AVATAR_REPLY)
        self.assertEqual(events[0]["details"]["text"], "やっほー")
        self.assertEqual(events[0]["details"]["to"], "こんにちは")

    def test_log_exchange_writes_both(self):
        self.log.log_exchange("hello", "Hi there!")
        events = self._read_lines()
        self.assertEqual([e["event_type"] for e in events],
                         [EVENT_USER_COMMENT, EVENT_AVATAR_REPLY])

    def test_log_exchange_skips_echo_reply(self):
        """Echo (reply == comment) must not be double-recorded as a reply."""
        self.log.log_exchange("echo me", "echo me")
        events = self._read_lines()
        self.assertEqual([e["event_type"] for e in events], [EVENT_USER_COMMENT])

    def test_empty_text_not_recorded(self):
        self.log.log_user_comment("")
        self.log.log_avatar_reply("")
        self.assertEqual(self._read_lines(), [])


class RecentTests(_TmpLogBase):
    def test_recent_returns_oldest_first(self):
        self.log.log_exchange("q1", "a1")
        self.log.log_exchange("q2", "a2")
        recent = self.log.recent(10)
        texts = [(e["event_type"], e["details"]["text"]) for e in recent]
        self.assertEqual(texts, [
            (EVENT_USER_COMMENT, "q1"), (EVENT_AVATAR_REPLY, "a1"),
            (EVENT_USER_COMMENT, "q2"), (EVENT_AVATAR_REPLY, "a2"),
        ])

    def test_recent_limits_to_n(self):
        for i in range(10):
            self.log.log_user_comment(f"c{i}")
        recent = self.log.recent(3)
        self.assertEqual([e["details"]["text"] for e in recent], ["c7", "c8", "c9"])

    def test_recent_filters_non_conversation_events(self):
        # Write a non-conversation event directly (e.g. a move event)
        self.log._logger.log_event("move", x=1.0)
        self.log.log_user_comment("hi")
        recent = self.log.recent(10)
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]["event_type"], EVENT_USER_COMMENT)

    def test_recent_missing_file_returns_empty(self):
        log = ConversationLog(os.path.join(self._tmp, "nope.jsonl"))
        self.assertEqual(log.recent(), [])

    def test_recent_skips_corrupt_lines(self):
        with open(self.logfile, "w", encoding="utf-8") as f:
            f.write("not json\n")
            f.write(json.dumps({"timestamp": 1, "event_type": EVENT_USER_COMMENT,
                                "details": {"text": "ok"}}) + "\n")
        self.assertEqual(len(self.log.recent()), 1)

    def test_recent_texts_format(self):
        self.log.log_exchange("hello", "Hi!")
        self.assertEqual(self.log.recent_texts(), ["You: hello", "Avatar: Hi!"])


class SingletonTests(unittest.TestCase):
    def tearDown(self):
        reset_conversation_log()

    def test_singleton_shared(self):
        reset_conversation_log()
        a = get_conversation_log()
        b = get_conversation_log()
        self.assertIs(a, b)

    def test_reset_creates_new(self):
        a = get_conversation_log()
        reset_conversation_log()
        self.assertIsNot(a, get_conversation_log())


class SpeakCommentWiringTests(unittest.TestCase):
    """speak_comment must record the exchange into the conversation log."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.logfile = os.path.join(self._tmp, "events.jsonl")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)
        reset_conversation_log()

    def test_speak_comment_logs_exchange(self):
        import avatar_3d_autonomous_tts as _mod
        from persona import Persona

        test_log = ConversationLog(self.logfile)
        respond_persona = Persona.from_dict({
            "responses": {"en": {"rules": [
                {"keywords": ["hello"], "replies": ["REPLY"]}], "fallback": []}},
            "default_lang": "en",
        }, lang="en")

        with mock.patch.object(_mod, "get_conversation_log", lambda: test_log), \
             mock.patch.object(_mod.AutonomousBehaviorMixin, "persona",
                               property(lambda self: respond_persona)):
            v = object.__new__(_mod.AutonomousAvatarViewer)
            v.comment_text = ""
            v.mode = "idle"
            v.ticks = 0
            v.tts_queue = queue.Queue()
            v.speak_comment("hello")

        recorded = test_log.recent()
        self.assertEqual([e["event_type"] for e in recorded],
                         [EVENT_USER_COMMENT, EVENT_AVATAR_REPLY])
        self.assertEqual(recorded[0]["details"]["text"], "hello")
        self.assertEqual(recorded[1]["details"]["text"], "REPLY")

    def test_speak_comment_survives_log_failure(self):
        """A broken conversation log must not break TTS/display."""
        import avatar_3d_autonomous_tts as _mod

        def _boom():
            raise RuntimeError("log unavailable")

        with mock.patch.object(_mod, "get_conversation_log", _boom), \
             mock.patch.object(_mod.AutonomousBehaviorMixin, "persona",
                               property(lambda self: None)):
            v = object.__new__(_mod.AutonomousAvatarViewer)
            v.comment_text = ""
            v.mode = "idle"
            v.ticks = 0
            v.tts_queue = queue.Queue()
            v.speak_comment("hi")  # must not raise
            self.assertEqual(v.comment_text, "hi")


if __name__ == "__main__":
    unittest.main()
