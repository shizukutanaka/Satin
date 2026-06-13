"""
Headless wiring test for avatar_3d_autonomous_tts.AutonomousAvatarViewer.speak_comment.

Qt is absent in CI. We build the viewer via object.__new__ (bypassing the
Qt-dependent __init__) and set only the attributes speak_comment touches, then
assert the avatar now REPLIES (persona.respond) instead of echoing the input,
while preserving the legacy echo behavior when no persona / no reply is available.

This mirrors the object.__new__ approach used in test_avatar_event_timeline_viewer.py.
"""
import os
import queue
import sys
import unittest
from unittest import mock

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import avatar_3d_autonomous_tts as _mod  # noqa: E402
import persona as _persona_mod  # noqa: E402
from persona import Persona  # noqa: E402
import mood as _mood_mod  # noqa: E402


def _make_viewer(tts_queue=None):
    """Construct the viewer without running Qt's __init__."""
    v = object.__new__(_mod.AutonomousAvatarViewer)
    v.comment_text = ""
    v.mode = "idle"
    v.ticks = 0
    v.tts_queue = tts_queue
    v.talk_text = ""
    return v


_RESPONSE_PERSONA = Persona.from_dict({
    "responses": {
        "en": {
            "rules": [{"keywords": ["hello"], "replies": ["REPLY_HELLO"]}],
            "fallback": ["REPLY_FB"],
        },
    },
    "default_lang": "en",
}, lang="en")


class SpeakCommentTests(unittest.TestCase):
    def setUp(self):
        # 会話ログと好感度を無効化して CWD にファイルを作らない
        self._log_patcher = mock.patch.object(_mod, "get_conversation_log", None)
        self._log_patcher.start()
        self._mood_patcher = mock.patch.object(_mod, "get_mood_tracker", None)
        self._mood_patcher.start()

    def tearDown(self):
        self._log_patcher.stop()
        self._mood_patcher.stop()
        _persona_mod.reset_persona()
        _mood_mod.reset_mood_tracker()

    def test_matching_keyword_replies_not_echoes(self):
        """A keyword hit makes the avatar speak the reply, not the user's words."""
        with mock.patch.object(_mod.AutonomousBehaviorMixin, "persona",
                               property(lambda self: _RESPONSE_PERSONA)):
            q = queue.Queue()
            v = _make_viewer(q)
            v.speak_comment("hello")
            self.assertEqual(v.comment_text, "REPLY_HELLO")
            self.assertEqual(q.get_nowait(), "REPLY_HELLO")

    def test_no_match_uses_fallback_reply(self):
        with mock.patch.object(_mod.AutonomousBehaviorMixin, "persona",
                               property(lambda self: _RESPONSE_PERSONA)):
            q = queue.Queue()
            v = _make_viewer(q)
            v.speak_comment("quantum physics")
            self.assertEqual(v.comment_text, "REPLY_FB")
            self.assertEqual(q.get_nowait(), "REPLY_FB")

    def test_persona_none_echoes_literal(self):
        """When persona is unavailable, legacy echo behavior is preserved."""
        with mock.patch.object(_mod.AutonomousBehaviorMixin, "persona",
                               property(lambda self: None)):
            q = queue.Queue()
            v = _make_viewer(q)
            v.speak_comment("just echo me")
            self.assertEqual(v.comment_text, "just echo me")
            self.assertEqual(q.get_nowait(), "just echo me")

    def test_empty_reply_falls_back_to_echo(self):
        """If respond() returns '' (e.g. empty input), echo the comment."""
        empty_persona = Persona.from_dict(
            {"responses": {"en": {"rules": [], "fallback": []}}}, lang="en")
        with mock.patch.object(_mod.AutonomousBehaviorMixin, "persona",
                               property(lambda self: empty_persona)):
            q = queue.Queue()
            v = _make_viewer(q)
            v.speak_comment("anything")  # no rules, no fallback → respond '' → echo
            self.assertEqual(v.comment_text, "anything")
            self.assertEqual(q.get_nowait(), "anything")

    def test_respond_exception_falls_back_to_echo(self):
        """A persona whose respond() raises must not break TTS — echo instead."""
        class _Boom:
            def respond(self, text, lang=None):
                raise RuntimeError("boom")
        with mock.patch.object(_mod.AutonomousBehaviorMixin, "persona",
                               property(lambda self: _Boom())):
            q = queue.Queue()
            v = _make_viewer(q)
            v.speak_comment("hi")
            self.assertEqual(v.comment_text, "hi")
            self.assertEqual(q.get_nowait(), "hi")

    def test_mode_and_ticks_set(self):
        with mock.patch.object(_mod.AutonomousBehaviorMixin, "persona",
                               property(lambda self: _RESPONSE_PERSONA)):
            v = _make_viewer(queue.Queue())
            v.mode = "run"
            v.ticks = 99
            v.speak_comment("hello")
            self.assertEqual(v.mode, "comment")
            self.assertEqual(v.ticks, 0)

    def test_no_tts_queue_does_not_crash(self):
        with mock.patch.object(_mod.AutonomousBehaviorMixin, "persona",
                               property(lambda self: _RESPONSE_PERSONA)):
            v = _make_viewer(None)
            v.speak_comment("hello")  # must not raise
            self.assertEqual(v.comment_text, "REPLY_HELLO")


class SpeakCommentMoodTests(unittest.TestCase):
    """speak_comment calls mood.register(comment) so GUI chat builds affinity."""

    def setUp(self):
        self._log_patcher = mock.patch.object(_mod, "get_conversation_log", None)
        self._log_patcher.start()
        _mood_mod.reset_mood_tracker()

    def tearDown(self):
        self._log_patcher.stop()
        _mood_mod.reset_mood_tracker()
        _persona_mod.reset_persona()

    def _viewer_with_persona(self):
        v = _make_viewer(queue.Queue())
        # persona that always replies so the test is stable
        patcher = mock.patch.object(
            _mod.AutonomousBehaviorMixin, "persona",
            property(lambda self: _RESPONSE_PERSONA),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        return v

    def test_positive_comment_raises_affinity(self):
        import tempfile, os
        tmp = tempfile.mkdtemp()
        mood_path = os.path.join(tmp, "mood.json")
        tracker = _mood_mod.MoodTracker(affinity=50)

        def _fake_get_mood_tracker():
            return tracker

        with mock.patch.object(_mod, "get_mood_tracker", _fake_get_mood_tracker):
            v = self._viewer_with_persona()
            v.speak_comment("thank you so much")

        self.assertGreater(tracker.affinity, 50)
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    def test_mood_register_failure_does_not_crash(self):
        class _BoomMood:
            def register(self, text):
                raise RuntimeError("db locked")

        def _bad_tracker():
            return _BoomMood()

        with mock.patch.object(_mod, "get_mood_tracker", _bad_tracker):
            v = self._viewer_with_persona()
            v.speak_comment("hello")  # must not raise
            self.assertEqual(v.comment_text, "REPLY_HELLO")

    def test_mood_not_called_when_get_mood_tracker_is_none(self):
        with mock.patch.object(_mod, "get_mood_tracker", None):
            v = self._viewer_with_persona()
            v.speak_comment("hello")  # must not raise
            self.assertEqual(v.comment_text, "REPLY_HELLO")

    def test_mood_saved_after_register(self):
        """speak_comment persists affinity to disk after each interaction."""
        import tempfile, os
        tmp = tempfile.mkdtemp()
        mood_path = os.path.join(tmp, "mood.json")
        tracker = _mood_mod.MoodTracker(affinity=50, interactions=1,
                                        last_interaction_time=1.0)

        with mock.patch.object(_mod, "get_mood_tracker", lambda: tracker):
            with mock.patch.object(_mod, "_default_mood_path", lambda: mood_path):
                v = self._viewer_with_persona()
                v.speak_comment("thank you")

        self.assertTrue(os.path.exists(mood_path), "mood.json should be written after interact")
        import json, shutil
        with open(mood_path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertGreater(data["affinity"], 50)
        shutil.rmtree(tmp, ignore_errors=True)

    def test_mood_save_failure_does_not_crash(self):
        """If save() fails (e.g. disk full), TTS must still complete."""
        class _SaveBoomTracker:
            level = "neutral"
            interactions = 1

            def register(self, text):
                pass

            def save(self, path):
                raise OSError("disk full")

        with mock.patch.object(_mod, "get_mood_tracker", lambda: _SaveBoomTracker()):
            with mock.patch.object(_mod, "_default_mood_path", lambda: "/tmp/mood.json"):
                v = self._viewer_with_persona()
                v.speak_comment("hello")  # must not raise
                self.assertEqual(v.comment_text, "REPLY_HELLO")


if __name__ == "__main__":
    unittest.main()
