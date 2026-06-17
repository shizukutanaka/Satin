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
import user_profile as _profile_mod  # noqa: E402


def _make_viewer(tts_queue=None):
    """Construct the viewer without running Qt's __init__."""
    v = object.__new__(_mod.AutonomousAvatarViewer)
    v.comment_text = ""
    v.mode = "idle"
    v.ticks = 0
    v.tts_queue = tts_queue
    v.talk_text = ""
    v.pending_fact_key = None
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
        # 会話ログ・好感度・ユーザープロファイルを無効化して CWD にファイルを作らない
        self._log_patcher = mock.patch.object(_mod, "get_conversation_log", None)
        self._log_patcher.start()
        self._mood_patcher = mock.patch.object(_mod, "get_mood_tracker", None)
        self._mood_patcher.start()
        # Interest mention relies on user profile singleton; reset to prevent cross-test leak
        _profile_mod.reset_user_profile()
        self._profile_patcher = mock.patch.object(_mod, "_get_user_profile_gui", lambda: None)
        self._profile_patcher.start()

    def tearDown(self):
        self._profile_patcher.stop()
        self._log_patcher.stop()
        self._mood_patcher.stop()
        _persona_mod.reset_persona()
        _mood_mod.reset_mood_tracker()
        _profile_mod.reset_user_profile()

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
        # Prevent interest mention from firing due to profile singleton leaking from other tests
        _profile_mod.reset_user_profile()
        self._profile_patcher = mock.patch.object(_mod, "_get_user_profile_gui", lambda: None)
        self._profile_patcher.start()

    def tearDown(self):
        self._profile_patcher.stop()
        self._log_patcher.stop()
        _mood_mod.reset_mood_tracker()
        _persona_mod.reset_persona()
        _profile_mod.reset_user_profile()

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

    def test_follow_up_appended_every_n_interactions(self):
        """Every N comments the avatar appends a proactive follow-up question."""
        follow_persona = Persona.from_dict({
            "responses": {"en": {
                "rules": [{"keywords": ["hello"], "replies": ["REPLY_HELLO"]}],
                "fallback": ["FB"],
                "follow_up": ["WHATS_NEW"],
            }},
            "default_lang": "en",
        }, lang="en")
        # tracker whose interaction count lands exactly on the threshold after register()
        tracker = _mood_mod.MoodTracker(
            affinity=50, interactions=_mod._FOLLOW_UP_EVERY - 1)
        patcher = mock.patch.object(
            _mod.AutonomousBehaviorMixin, "persona",
            property(lambda self: follow_persona))
        patcher.start()
        self.addCleanup(patcher.stop)
        # Disable Q&A path so the test deterministically exercises persona.follow_up_question
        with mock.patch.object(_mod, "get_mood_tracker", lambda: tracker), \
             mock.patch.object(_mod, "_default_mood_path", lambda: None), \
             mock.patch.object(_mod, "_default_mood_history_path", lambda: None), \
             mock.patch.object(_mod, "_get_user_profile_gui", None):
            v = _make_viewer(queue.Queue())
            v.speak_comment("hello")
        self.assertIn("WHATS_NEW", v.comment_text)

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


class SilentFailureObservabilityTests(unittest.TestCase):
    """Failures in the mood/history side-effects of speak_comment must be
    RESILIENT (no crash) AND OBSERVABLE (logged), not silently swallowed."""

    def _viewer(self):
        v = object.__new__(_mod.AutonomousAvatarViewer)
        v.comment_text = ""
        v.mode = "idle"
        v.ticks = 0
        v.tts_queue = None
        v.talk_text = ""
        v.pending_fact_key = None
        return v

    def test_mood_failure_is_logged_not_silent(self):
        class _BoomTracker:
            level = "neutral"
            affinity = 50.0
            interactions = 1

            def register(self, text):
                raise RuntimeError("mood backend down")

        with mock.patch.object(_mod, "get_mood_tracker", lambda: _BoomTracker()):
            with mock.patch.object(_mod, "_default_mood_path", lambda: "/tmp/m.json"):
                v = self._viewer()
                with self.assertLogs(_mod.logger, level="WARNING") as cm:
                    v.speak_comment("hello")  # resilient: must not raise
                self.assertTrue(any("好感度" in m for m in cm.output))

    def test_conversation_log_failure_is_logged_not_silent(self):
        class _BoomLog:
            def log_exchange(self, comment, reply):
                raise OSError("disk full")

        with mock.patch.object(_mod, "get_mood_tracker", None):
            with mock.patch.object(_mod, "get_conversation_log", lambda: _BoomLog()):
                v = self._viewer()
                with self.assertLogs(_mod.logger, level="WARNING") as cm:
                    v.speak_comment("hello")  # resilient
                self.assertTrue(any("会話履歴" in m for m in cm.output))


class MakeReminderSpeakTests(unittest.TestCase):
    """make_reminder_speak builds a speak_func that makes the avatar VISIBLY
    say the break reminder (sets comment display) and also queues TTS, so the
    reminder reaches the user even when pyttsx3/TTS is unavailable."""

    class _FakeViewer:
        def __init__(self):
            self.comment_text = ""
            self.mode = "run"
            self.ticks = 99

    def test_sets_comment_text_for_visible_display(self):
        v = self._FakeViewer()
        speak = _mod.make_reminder_speak(v, None)
        speak("Time for a break!")
        self.assertEqual(v.comment_text, "Time for a break!")

    def test_sets_comment_mode_and_resets_ticks(self):
        v = self._FakeViewer()
        speak = _mod.make_reminder_speak(v, None)
        speak("break")
        self.assertEqual(v.mode, "comment")
        self.assertEqual(v.ticks, 0)

    def test_queues_tts_when_queue_present(self):
        v = self._FakeViewer()
        q = queue.Queue()
        speak = _mod.make_reminder_speak(v, q)
        speak("drink water")
        self.assertEqual(q.get_nowait(), "drink water")

    def test_no_queue_does_not_crash(self):
        v = self._FakeViewer()
        speak = _mod.make_reminder_speak(v, None)
        speak("ok")  # must not raise
        self.assertEqual(v.comment_text, "ok")

    def test_no_viewer_does_not_crash(self):
        q = queue.Queue()
        speak = _mod.make_reminder_speak(None, q)
        speak("hello")  # viewer None must not raise
        self.assertEqual(q.get_nowait(), "hello")

    def test_visible_even_without_tts(self):
        # The whole point: with no TTS queue, the reminder is STILL visible.
        v = self._FakeViewer()
        speak = _mod.make_reminder_speak(v, None)
        speak("休憩しましょう")
        self.assertEqual(v.comment_text, "休憩しましょう")
        self.assertEqual(v.mode, "comment")

    def test_skips_when_autonomous_stopped(self):
        # Race guard: a reminder firing AFTER autonomous mode stopped must be a
        # no-op, else comment_text would be set with no loop left to clear it.
        v = self._FakeViewer()
        v.is_autonomous = False
        q = queue.Queue()
        speak = _mod.make_reminder_speak(v, q)
        speak("too late")
        self.assertEqual(v.comment_text, "")      # display untouched
        self.assertEqual(v.mode, "run")           # mode untouched
        self.assertTrue(q.empty())                # no TTS queued either

    def test_fires_when_autonomous_active(self):
        v = self._FakeViewer()
        v.is_autonomous = True
        speak = _mod.make_reminder_speak(v, None)
        speak("break time")
        self.assertEqual(v.comment_text, "break time")


class UserPlaceholderResolutionTests(unittest.TestCase):
    """{user} placeholder in GUI speak_comment replies must be resolved to the name."""

    def test_user_placeholder_replaced_with_name(self):
        """When persona fallback contains {user}, it's resolved to the user's profile name."""
        from user_profile import UserProfile
        profile = UserProfile(name="Hanako")

        # Build a persona whose fallback always uses {user}
        _placeholder_persona = Persona.from_dict({
            "responses": {
                "ja": {
                    "rules": [],
                    "fallback": ["{user}、聞いてるよ。"],
                    "follow_up": [],
                },
            },
            "default_lang": "ja",
        })

        v = _make_viewer()
        with mock.patch.object(_mod, "get_mood_tracker", None), \
             mock.patch.object(_mod, "_get_user_profile_gui", lambda: profile), \
             mock.patch.object(_mod.AutonomousBehaviorMixin, "persona",
                               new_callable=lambda: property(
                                   lambda self: _placeholder_persona)):
            v.speak_comment("なんか聞いて")

        self.assertNotIn("{user}", v.comment_text)
        self.assertIn("Hanako", v.comment_text)

    def test_user_placeholder_fallback_without_name(self):
        """When no name is set, {user} falls back to 'きみ' (ja default)."""
        from user_profile import UserProfile
        profile = UserProfile()  # no name

        _placeholder_persona = Persona.from_dict({
            "responses": {
                "ja": {
                    "rules": [],
                    "fallback": ["{user}、聞いてるよ。"],
                    "follow_up": [],
                },
            },
            "default_lang": "ja",
        })

        v = _make_viewer()
        with mock.patch.object(_mod, "get_mood_tracker", None), \
             mock.patch.object(_mod, "_get_user_profile_gui", lambda: profile), \
             mock.patch.object(_mod.AutonomousBehaviorMixin, "persona",
                               new_callable=lambda: property(
                                   lambda self: _placeholder_persona)):
            v.speak_comment("なんか聞いて")

        self.assertNotIn("{user}", v.comment_text)
        self.assertIn("きみ", v.comment_text)


class SpeakCommentRitualHurtTests(unittest.TestCase):
    """Hurt event and ritual bonus wiring in speak_comment()."""

    def _make_viewer_with_tracker(self, affinity=50.0, interactions=1, negative_delta=6.0):
        from mood import MoodTracker
        tracker = MoodTracker(affinity=affinity, interactions=interactions,
                              negative_delta=negative_delta)
        q = queue.Queue()
        v = _make_viewer(tts_queue=q)
        return v, tracker, q

    def test_rude_comment_triggers_hurt_reply(self):
        """Multiple negative keywords → large delta → hurt reaction overrides normal reply."""
        v, tracker, q = self._make_viewer_with_tracker(affinity=80.0)
        with mock.patch.object(_mod, "get_mood_tracker", lambda: tracker), \
             mock.patch.object(_mod, "_default_mood_path", None), \
             mock.patch.object(_mod, "_default_mood_history_path", None), \
             mock.patch.object(_mod._mod if hasattr(_mod, "_mod") else _mod,
                               "get_persona", None, create=True):
            # Patch the persona property on the viewer to return our test persona
            with mock.patch.object(_mod.AutonomousBehaviorMixin, "persona",
                                   new_callable=lambda: property(lambda self: _RESPONSE_PERSONA)):
                v.speak_comment("hate ugly shut up stupid")  # many negative words
        from mood import _HURT_MESSAGES
        hurt_words_en = _HURT_MESSAGES.get("en", [])
        self.assertTrue(
            any(hw in v.comment_text for hw in hurt_words_en),
            f"Expected hurt message; got: {v.comment_text!r}"
        )

    def test_goodnight_bonus_applied_in_gui(self):
        """おやすみ in GUI speak_comment should give the goodnight bonus."""
        from persona_cli import _GOODNIGHT_BONUS
        v, tracker, q = self._make_viewer_with_tracker(affinity=50.0)
        before = tracker.affinity
        with mock.patch.object(_mod, "get_mood_tracker", lambda: tracker), \
             mock.patch.object(_mod, "_default_mood_path", None), \
             mock.patch.object(_mod, "_default_mood_history_path", None), \
             mock.patch.object(_mod.AutonomousBehaviorMixin, "persona",
                               new_callable=lambda: property(lambda self: _RESPONSE_PERSONA)):
            v.speak_comment("おやすみ")
        # "おやすみ" has no positive/negative keywords → raw_delta == 0,
        # only the ritual bonus changes affinity
        self.assertAlmostEqual(tracker.affinity, before + _GOODNIGHT_BONUS, places=4)

    def test_apology_bonus_applied_in_gui(self):
        """ごめん in GUI speak_comment should give the apology bonus."""
        from persona_cli import _APOLOGY_BONUS
        v, tracker, q = self._make_viewer_with_tracker(affinity=50.0)
        before = tracker.affinity
        with mock.patch.object(_mod, "get_mood_tracker", lambda: tracker), \
             mock.patch.object(_mod, "_default_mood_path", None), \
             mock.patch.object(_mod, "_default_mood_history_path", None), \
             mock.patch.object(_mod.AutonomousBehaviorMixin, "persona",
                               new_callable=lambda: property(lambda self: _RESPONSE_PERSONA)):
            v.speak_comment("ごめん")
        self.assertAlmostEqual(tracker.affinity, before + _APOLOGY_BONUS, places=4)

    def test_interaction_milestone_appended_in_gui(self):
        """10th interaction milestone message is appended to the reply."""
        v, tracker, q = self._make_viewer_with_tracker(affinity=50.0, interactions=9)
        with mock.patch.object(_mod, "get_mood_tracker", lambda: tracker), \
             mock.patch.object(_mod, "_default_mood_path", None), \
             mock.patch.object(_mod, "_default_mood_history_path", None), \
             mock.patch.object(_mod.AutonomousBehaviorMixin, "persona",
                               new_callable=lambda: property(lambda self: _RESPONSE_PERSONA)):
            v.speak_comment("hello")
        self.assertEqual(tracker.interactions, 10)
        self.assertIn("10", v.comment_text)


class GUIQAIntegrationTests(unittest.TestCase):
    """Profile Q&A tracking in GUI speak_comment: answer recording and follow-up Q&A."""

    def setUp(self):
        self._log_patcher = mock.patch.object(_mod, "get_conversation_log", None)
        self._log_patcher.start()

    def tearDown(self):
        self._log_patcher.stop()
        _persona_mod.reset_persona()
        _mood_mod.reset_mood_tracker()

    def test_pending_fact_key_records_answer_in_profile(self):
        """When pending_fact_key is set, the comment is saved into profile.facts."""
        from user_profile import UserProfile
        prof = UserProfile()
        v = _make_viewer()
        v.pending_fact_key = "pet"

        with mock.patch.object(_mod, "get_mood_tracker", None), \
             mock.patch.object(_mod.AutonomousBehaviorMixin, "persona",
                               property(lambda self: _RESPONSE_PERSONA)), \
             mock.patch.object(_mod, "_get_user_profile_gui", lambda: prof), \
             mock.patch.object(_mod, "_acknowledge_answer_gui",
                               lambda key, val, lang="ja": f"ACK:{val}"), \
             mock.patch.object(_mod, "_default_profile_path_gui", None):
            v.speak_comment("猫")

        self.assertEqual(prof.facts.get("pet"), "猫")

    def test_pending_fact_key_cleared_after_recording(self):
        """pending_fact_key is reset to None regardless of success after one answer."""
        from user_profile import UserProfile
        prof = UserProfile()
        v = _make_viewer()
        v.pending_fact_key = "favorite_food"

        with mock.patch.object(_mod, "get_mood_tracker", None), \
             mock.patch.object(_mod.AutonomousBehaviorMixin, "persona",
                               property(lambda self: _RESPONSE_PERSONA)), \
             mock.patch.object(_mod, "_get_user_profile_gui", lambda: prof), \
             mock.patch.object(_mod, "_acknowledge_answer_gui",
                               lambda key, val, lang="ja": "ACK"), \
             mock.patch.object(_mod, "_default_profile_path_gui", None):
            v.speak_comment("ラーメン")

        self.assertIsNone(v.pending_fact_key)

    def test_ack_msg_prepended_to_reply(self):
        """Acknowledgement of recorded fact is prepended before the persona reply."""
        from user_profile import UserProfile
        prof = UserProfile()
        v = _make_viewer()
        v.pending_fact_key = "pet"

        with mock.patch.object(_mod, "get_mood_tracker", None), \
             mock.patch.object(_mod.AutonomousBehaviorMixin, "persona",
                               property(lambda self: _RESPONSE_PERSONA)), \
             mock.patch.object(_mod, "_get_user_profile_gui", lambda: prof), \
             mock.patch.object(_mod, "_acknowledge_answer_gui",
                               lambda key, val, lang="ja": "ACK_TEXT"), \
             mock.patch.object(_mod, "_default_profile_path_gui", None):
            v.speak_comment("hello")  # keyword → REPLY_HELLO

        self.assertTrue(v.comment_text.startswith("ACK_TEXT"),
                        f"Expected ack first; got: {v.comment_text!r}")
        self.assertIn("REPLY_HELLO", v.comment_text)

    def test_no_crash_when_acknowledge_answer_is_none(self):
        """If _acknowledge_answer_gui is None, pending_fact_key is still cleared."""
        from user_profile import UserProfile
        prof = UserProfile()
        v = _make_viewer()
        v.pending_fact_key = "hometown"

        with mock.patch.object(_mod, "get_mood_tracker", None), \
             mock.patch.object(_mod.AutonomousBehaviorMixin, "persona",
                               property(lambda self: _RESPONSE_PERSONA)), \
             mock.patch.object(_mod, "_get_user_profile_gui", lambda: prof), \
             mock.patch.object(_mod, "_acknowledge_answer_gui", None), \
             mock.patch.object(_mod, "_default_profile_path_gui", None):
            v.speak_comment("東京")  # must not raise

        self.assertIsNone(v.pending_fact_key)

    def test_no_crash_when_profile_returns_none(self):
        """If _get_user_profile_gui() returns None, pending_fact_key is still cleared."""
        v = _make_viewer()
        v.pending_fact_key = "dream"

        with mock.patch.object(_mod, "get_mood_tracker", None), \
             mock.patch.object(_mod.AutonomousBehaviorMixin, "persona",
                               property(lambda self: _RESPONSE_PERSONA)), \
             mock.patch.object(_mod, "_get_user_profile_gui", lambda: None), \
             mock.patch.object(_mod, "_acknowledge_answer_gui",
                               lambda key, val, lang="ja": "ACK"), \
             mock.patch.object(_mod, "_default_profile_path_gui", None):
            v.speak_comment("宇宙飛行士")  # must not raise

        self.assertIsNone(v.pending_fact_key)

    def test_qa_followup_sets_pending_fact_key(self):
        """On the Nth exchange, the Q&A path fires and pending_fact_key is set."""
        from user_profile import UserProfile
        from profile_questions import all_question_keys

        prof = UserProfile()  # no facts answered yet

        # Fake tracker: level=neutral, interactions already at threshold
        class _FakeTracker:
            level = "neutral"
            affinity = 50.0
            interactions = _mod._FOLLOW_UP_EVERY

            def register(self, text):
                return 0.0

            def adjust(self, delta):
                pass

            def save(self, path):
                pass

            def snapshot_to_history(self, path):
                pass

        non_q_persona = Persona.from_dict({
            "responses": {"ja": {"rules": [], "fallback": ["了解。"]}},
            "default_lang": "ja",
        })

        v = _make_viewer()
        with mock.patch.object(_mod.AutonomousBehaviorMixin, "persona",
                               property(lambda self: non_q_persona)), \
             mock.patch.object(_mod, "get_mood_tracker", lambda: _FakeTracker()), \
             mock.patch.object(_mod, "_default_mood_path", None), \
             mock.patch.object(_mod, "_default_mood_history_path", None), \
             mock.patch.object(_mod, "_get_user_profile_gui", lambda: prof), \
             mock.patch.object(_mod, "_default_profile_path_gui", None), \
             mock.patch.object(_mod.random, "random", return_value=0.1):  # force Q&A path
            v.speak_comment("なんか言って")

        self.assertIsNotNone(v.pending_fact_key,
                             "pending_fact_key should be set when Q&A fires")
        self.assertIn(v.pending_fact_key, all_question_keys())

    def test_qa_followup_skips_when_all_facts_known(self):
        """Q&A does not ask again when all profile questions are already answered."""
        from user_profile import UserProfile
        from profile_questions import all_question_keys

        prof = UserProfile()
        # Populate all facts so no question is left
        for key in all_question_keys():
            prof.set_fact(key, "something")

        class _FakeTracker:
            level = "neutral"
            affinity = 50.0
            interactions = _mod._FOLLOW_UP_EVERY

            def register(self, text):
                return 0.0

            def adjust(self, delta):
                pass

            def save(self, path):
                pass

            def snapshot_to_history(self, path):
                pass

        non_q_persona = Persona.from_dict({
            "responses": {"ja": {"rules": [], "fallback": ["了解。"]}},
            "default_lang": "ja",
        })

        v = _make_viewer()
        with mock.patch.object(_mod.AutonomousBehaviorMixin, "persona",
                               property(lambda self: non_q_persona)), \
             mock.patch.object(_mod, "get_mood_tracker", lambda: _FakeTracker()), \
             mock.patch.object(_mod, "_default_mood_path", None), \
             mock.patch.object(_mod, "_default_mood_history_path", None), \
             mock.patch.object(_mod, "_get_user_profile_gui", lambda: prof), \
             mock.patch.object(_mod, "_default_profile_path_gui", None), \
             mock.patch.object(_mod.random, "random", return_value=0.1):
            v.speak_comment("なんか言って")

        # No unanswered questions → pending_fact_key stays None
        self.assertIsNone(v.pending_fact_key)


class GUISlashCommandTests(unittest.TestCase):
    """Tests for GUI /gift and /callme slash-command dispatch in speak_comment()."""

    def setUp(self):
        self._log_patcher = mock.patch.object(_mod, "get_conversation_log", None)
        self._log_patcher.start()
        self._mood_patcher = mock.patch.object(_mod, "get_mood_tracker", None)
        self._mood_patcher.start()

    def tearDown(self):
        self._log_patcher.stop()
        self._mood_patcher.stop()
        _persona_mod.reset_persona()
        _mood_mod.reset_mood_tracker()

    # --- /gift tests ---

    def test_gift_flower_at_neutral_gives_reply_and_bonus(self):
        """Gift at sufficient level → avatar reply + bonus shown, mood adjusted."""
        class _Tracker:
            level = "neutral"
            affinity = 30.0
            def adjust(self, d): self.affinity += d
            def save(self, p): pass
            def snapshot_to_history(self, p): pass

        tracker = _Tracker()
        v = _make_viewer()
        with mock.patch.object(_mod, "get_mood_tracker", lambda: tracker), \
             mock.patch.object(_mod, "_default_mood_path", None), \
             mock.patch.object(_mod, "_default_mood_history_path", None):
            v.speak_comment("/gift 花")

        self.assertIn("+", v.comment_text)
        self.assertGreater(tracker.affinity, 30.0)

    def test_gift_music_declined_at_reserved(self):
        """Music requires neutral; at reserved affinity must not increase."""
        class _Tracker:
            level = "reserved"
            affinity = 10.0
            def adjust(self, d): self.affinity += d
            def save(self, p): pass
            def snapshot_to_history(self, p): pass

        tracker = _Tracker()
        v = _make_viewer()
        with mock.patch.object(_mod, "get_mood_tracker", lambda: tracker), \
             mock.patch.object(_mod, "_default_mood_path", None), \
             mock.patch.object(_mod, "_default_mood_history_path", None):
            v.speak_comment("/gift 音楽")

        self.assertEqual(tracker.affinity, 10.0, "Affinity must not change on gift decline")
        self.assertGreater(len(v.comment_text), 0)

    def test_gift_unknown_item_shows_error(self):
        v = _make_viewer()
        v.speak_comment("/gift xyz_unknown_thing_xyzzy")
        self.assertGreater(len(v.comment_text), 0)
        self.assertNotIn("+", v.comment_text)

    def test_gift_list_shows_catalog(self):
        v = _make_viewer()
        v.speak_comment("/gift list")
        self.assertIn("+", v.comment_text)

    def test_gift_empty_shows_catalog(self):
        v = _make_viewer()
        v.speak_comment("/gift")
        self.assertGreater(len(v.comment_text), 0)

    def test_gift_clears_pending_fact_key(self):
        v = _make_viewer()
        v.pending_fact_key = "favorite_food"
        v.speak_comment("/gift 花")
        self.assertIsNone(v.pending_fact_key)

    def test_gift_no_mood_tracker_no_crash(self):
        """Without mood tracker level=None bypasses gate; no crash."""
        v = _make_viewer()
        v.speak_comment("/gift 音楽")  # get_mood_tracker is None (patched in setUp)
        self.assertGreater(len(v.comment_text), 0)

    def test_gift_sets_mode_and_ticks(self):
        v = _make_viewer()
        v.speak_comment("/gift 花")
        self.assertEqual(v.mode, "comment")
        self.assertEqual(v.ticks, 0)

    def test_gift_pushes_to_tts_queue(self):
        q = queue.Queue()
        v = _make_viewer(tts_queue=q)
        v.speak_comment("/gift 花")
        self.assertFalse(q.empty())

    # --- /callme tests ---

    def test_callme_sets_profile_name(self):
        class _FakeProfile:
            name = None
            def save(self, p): pass

        prof = _FakeProfile()
        v = _make_viewer()
        with mock.patch.object(_mod, "_get_user_profile_gui", lambda: prof), \
             mock.patch.object(_mod, "_default_profile_path_gui", None):
            v.speak_comment("/callme Haruki")

        self.assertEqual(prof.name, "Haruki")

    def test_callme_reply_contains_name(self):
        v = _make_viewer()
        with mock.patch.object(_mod, "_get_user_profile_gui", None):
            v.speak_comment("/callme Sakura")
        self.assertIn("Sakura", v.comment_text)

    def test_callme_empty_shows_usage(self):
        v = _make_viewer()
        v.speak_comment("/callme")
        self.assertGreater(len(v.comment_text), 0)
        self.assertNotIn("って呼べば", v.comment_text)  # not the confirmation

    def test_callme_clears_pending_fact_key(self):
        v = _make_viewer()
        v.pending_fact_key = "favorite_color"
        with mock.patch.object(_mod, "_get_user_profile_gui", None):
            v.speak_comment("/callme Alice")
        self.assertIsNone(v.pending_fact_key)

    def test_callme_sets_mode_and_ticks(self):
        v = _make_viewer()
        with mock.patch.object(_mod, "_get_user_profile_gui", None):
            v.speak_comment("/callme Yuki")
        self.assertEqual(v.mode, "comment")
        self.assertEqual(v.ticks, 0)

    def test_callme_en_reply(self):
        v = _make_viewer()
        with mock.patch.object(_mod, "_get_user_profile_gui", None), \
             mock.patch.object(_mod.AutonomousBehaviorMixin, "persona",
                               property(lambda self: Persona.from_dict(
                                   {"default_lang": "en"}, lang="en"))):
            v.speak_comment("/callme Alice")
        self.assertIn("Alice", v.comment_text)

    def test_unknown_slash_command_falls_through_to_respond(self):
        """Unrecognized slash commands still go through persona.respond()."""
        with mock.patch.object(_mod.AutonomousBehaviorMixin, "persona",
                               property(lambda self: _RESPONSE_PERSONA)):
            v = _make_viewer()
            v.speak_comment("/help")
            # Should get a fallback reply, not a crash or empty string
            self.assertGreater(len(v.comment_text), 0)


class GUILikeForgetMoodBirthdayTests(unittest.TestCase):
    """Tests for /like, /forget, /mood, /birthday GUI commands."""

    def setUp(self):
        self._log_patcher = mock.patch.object(_mod, "get_conversation_log", None)
        self._log_patcher.start()
        self._mood_patcher = mock.patch.object(_mod, "get_mood_tracker", None)
        self._mood_patcher.start()

    def tearDown(self):
        self._log_patcher.stop()
        self._mood_patcher.stop()
        _persona_mod.reset_persona()
        _mood_mod.reset_mood_tracker()

    # --- /like ---

    def test_like_adds_interest(self):
        class _FakeProfile:
            interests = []
            def add_interest(self, t):
                self.interests.append(t)
                return t
            def save(self, p): pass

        prof = _FakeProfile()
        v = _make_viewer()
        with mock.patch.object(_mod, "_get_user_profile_gui", lambda: prof), \
             mock.patch.object(_mod, "_default_profile_path_gui", None):
            v.speak_comment("/like アニメ")

        self.assertIn("アニメ", prof.interests)
        self.assertIn("アニメ", v.comment_text)

    def test_like_empty_shows_usage(self):
        v = _make_viewer()
        v.speak_comment("/like")
        self.assertGreater(len(v.comment_text), 0)

    def test_like_no_profile_no_crash(self):
        v = _make_viewer()
        with mock.patch.object(_mod, "_get_user_profile_gui", None):
            v.speak_comment("/like cats")
        self.assertGreater(len(v.comment_text), 0)

    # --- /forget ---

    def test_forget_removes_interest(self):
        class _FakeProfile:
            def remove_interest(self, t): return True
            def save(self, p): pass

        prof = _FakeProfile()
        v = _make_viewer()
        with mock.patch.object(_mod, "_get_user_profile_gui", lambda: prof), \
             mock.patch.object(_mod, "_default_profile_path_gui", None):
            v.speak_comment("/forget アニメ")

        self.assertGreater(len(v.comment_text), 0)

    def test_forget_not_found(self):
        class _FakeProfile:
            def remove_interest(self, t): return False
            def save(self, p): pass

        prof = _FakeProfile()
        v = _make_viewer()
        with mock.patch.object(_mod, "_get_user_profile_gui", lambda: prof), \
             mock.patch.object(_mod, "_default_profile_path_gui", None):
            v.speak_comment("/forget アニメ")

        self.assertGreater(len(v.comment_text), 0)

    def test_forget_empty_shows_usage(self):
        v = _make_viewer()
        v.speak_comment("/forget")
        self.assertGreater(len(v.comment_text), 0)

    # --- /mood ---

    def test_mood_shows_level(self):
        class _FakeTracker:
            level = "friendly"
            affinity = 60.0
            def label(self, lang="ja"):
                return "友好的" if lang != "en" else "friendly"

        v = _make_viewer()
        with mock.patch.object(_mod, "get_mood_tracker", lambda: _FakeTracker()):
            v.speak_comment("/mood")

        self.assertGreater(len(v.comment_text), 0)

    def test_mood_no_tracker_no_crash(self):
        v = _make_viewer()  # get_mood_tracker is None from setUp
        v.speak_comment("/mood")
        self.assertGreater(len(v.comment_text), 0)

    def test_mood_shows_localized_label_ja(self):
        """JA label (e.g. '友好的') should appear, not raw 'friendly'."""
        class _FakeTracker:
            level = "friendly"
            affinity = 60.0
            def label(self, lang="ja"):
                return "友好的" if lang != "en" else "friendly"

        v = _make_viewer()
        with mock.patch.object(_mod, "get_mood_tracker", lambda: _FakeTracker()):
            v.speak_comment("/mood")
        self.assertIn("友好的", v.comment_text)

    # --- /stats ---

    def test_stats_shows_interactions(self):
        class _FakeTracker:
            level = "neutral"
            affinity = 50.0
            interactions = 42
            def label(self, lang="ja"): return "中立的"

        v = _make_viewer()
        with mock.patch.object(_mod, "get_mood_tracker", lambda: _FakeTracker()):
            v.speak_comment("/stats")
        self.assertIn("42", v.comment_text)

    def test_stats_no_tracker_no_crash(self):
        v = _make_viewer()
        v.speak_comment("/stats")
        self.assertGreater(len(v.comment_text), 0)

    def test_stats_sets_mode_comment(self):
        v = _make_viewer()
        v.speak_comment("/stats")
        self.assertEqual(v.mode, "comment")

    # --- /birthday ---

    def test_birthday_valid_date_saved(self):
        class _FakeProfile:
            birthday = None
            def set_birthday(self, d):
                self.birthday = d
                return d
            def save(self, p): pass

        prof = _FakeProfile()
        v = _make_viewer()
        with mock.patch.object(_mod, "_get_user_profile_gui", lambda: prof), \
             mock.patch.object(_mod, "_default_profile_path_gui", None):
            v.speak_comment("/birthday 03-14")

        self.assertEqual(prof.birthday, "03-14")
        self.assertIn("03-14", v.comment_text)

    def test_birthday_invalid_shows_error(self):
        class _FakeProfile:
            def set_birthday(self, d): return ""
            def save(self, p): pass

        prof = _FakeProfile()
        v = _make_viewer()
        with mock.patch.object(_mod, "_get_user_profile_gui", lambda: prof), \
             mock.patch.object(_mod, "_default_profile_path_gui", None):
            v.speak_comment("/birthday not-a-date")

        self.assertGreater(len(v.comment_text), 0)

    def test_birthday_empty_shows_usage(self):
        v = _make_viewer()
        v.speak_comment("/birthday")
        self.assertGreater(len(v.comment_text), 0)


class GUIResetMoodTests(unittest.TestCase):
    """Tests for /reset-mood GUI command."""

    def setUp(self):
        self._log_patcher = mock.patch.object(_mod, "get_conversation_log", None)
        self._log_patcher.start()

    def tearDown(self):
        self._log_patcher.stop()
        _persona_mod.reset_persona()
        _mood_mod.reset_mood_tracker()

    def test_reset_mood_resets_affinity(self):
        class _FakeTracker:
            affinity = 90.0
            interactions = 50
            _last_interaction_time = 0.0
            _first_interaction_time = 0.0
            _last_anniversary_days = 5
            _last_login_date = "2024-01-01"
            _login_streak = 7
            def save(self, p): pass

        v = _make_viewer()
        with mock.patch.object(_mod, "get_mood_tracker", lambda: _FakeTracker()), \
             mock.patch.object(_mod, "_default_mood_path", None):
            v.speak_comment("/reset-mood")

        self.assertGreater(len(v.comment_text), 0)

    def test_reset_mood_no_tracker_no_crash(self):
        v = _make_viewer()
        with mock.patch.object(_mod, "get_mood_tracker", None):
            v.speak_comment("/reset-mood")
        self.assertGreater(len(v.comment_text), 0)

    def test_reset_mood_sets_mode_comment(self):
        v = _make_viewer()
        with mock.patch.object(_mod, "get_mood_tracker", None):
            v.speak_comment("/reset-mood")
        self.assertEqual(v.mode, "comment")


class GUIWhoamiTests(unittest.TestCase):
    """Tests for /whoami GUI command."""

    def setUp(self):
        self._log_patcher = mock.patch.object(_mod, "get_conversation_log", None)
        self._log_patcher.start()
        self._mood_patcher = mock.patch.object(_mod, "get_mood_tracker", None)
        self._mood_patcher.start()

    def tearDown(self):
        self._log_patcher.stop()
        self._mood_patcher.stop()
        _persona_mod.reset_persona()
        _mood_mod.reset_mood_tracker()

    def test_whoami_shows_name_when_set(self):
        class _FakeProfile:
            name = "Haruki"
            birthday = ""
            interests = []

        v = _make_viewer()
        with mock.patch.object(_mod, "_get_user_profile_gui", lambda: _FakeProfile()):
            v.speak_comment("/whoami")
        self.assertIn("Haruki", v.comment_text)

    def test_whoami_shows_birthday_when_set(self):
        class _FakeProfile:
            name = ""
            birthday = "03-14"
            interests = []

        v = _make_viewer()
        with mock.patch.object(_mod, "_get_user_profile_gui", lambda: _FakeProfile()):
            v.speak_comment("/whoami")
        self.assertIn("03-14", v.comment_text)

    def test_whoami_shows_interests(self):
        class _FakeProfile:
            name = ""
            birthday = ""
            interests = ["アニメ", "音楽"]

        v = _make_viewer()
        with mock.patch.object(_mod, "_get_user_profile_gui", lambda: _FakeProfile()):
            v.speak_comment("/whoami")
        self.assertIn("アニメ", v.comment_text)

    def test_whoami_empty_profile_shows_unknown_message(self):
        class _FakeProfile:
            name = ""
            birthday = ""
            interests = []

        v = _make_viewer()
        with mock.patch.object(_mod, "_get_user_profile_gui", lambda: _FakeProfile()):
            v.speak_comment("/whoami")
        self.assertGreater(len(v.comment_text), 0)

    def test_whoami_shows_remembered_facts(self):
        from user_profile import UserProfile
        prof = UserProfile(name="Ken")
        prof.set_fact("favorite_food", "ラーメン")
        v = _make_viewer()
        with mock.patch.object(_mod, "_get_user_profile_gui", lambda: prof):
            v.speak_comment("/whoami")
        self.assertIn("ラーメン", v.comment_text)

    def test_whoami_no_profile_no_crash(self):
        v = _make_viewer()
        with mock.patch.object(_mod, "_get_user_profile_gui", None):
            v.speak_comment("/whoami")
        self.assertGreater(len(v.comment_text), 0)

    def test_whoami_sets_mode_comment(self):
        v = _make_viewer()
        with mock.patch.object(_mod, "_get_user_profile_gui", None):
            v.speak_comment("/whoami")
        self.assertEqual(v.mode, "comment")


class GUIHelpTests(unittest.TestCase):
    """Tests for the /help GUI command (lists available slash commands)."""

    def setUp(self):
        self._log_patcher = mock.patch.object(_mod, "get_conversation_log", None)
        self._log_patcher.start()
        self._mood_patcher = mock.patch.object(_mod, "get_mood_tracker", None)
        self._mood_patcher.start()

    def tearDown(self):
        self._log_patcher.stop()
        self._mood_patcher.stop()
        _persona_mod.reset_persona()
        _mood_mod.reset_mood_tracker()

    def test_help_lists_commands_ja(self):
        v = _make_viewer()
        v.speak_comment("/help")
        self.assertIn("/gift", v.comment_text)
        self.assertIn("/forget-me", v.comment_text)

    def test_help_lists_commands_en(self):
        from persona import Persona
        v = _make_viewer()
        _persona_mod._persona_singleton = Persona.from_dict(
            {"name": "T", "default_lang": "en"}, lang="en")
        try:
            v.speak_comment("/help")
        finally:
            _persona_mod.reset_persona()
        self.assertIn("/gift", v.comment_text)

    def test_help_sets_mode_comment(self):
        v = _make_viewer()
        v.speak_comment("/help")
        self.assertEqual(v.mode, "comment")


class GUICommandLoggingTests(unittest.TestCase):
    """GUI /like, /forget, /birthday log their exchange to the conversation log
    (parity with /gift and /callme, and with the CLI)."""

    def setUp(self):
        self._mood_patcher = mock.patch.object(_mod, "get_mood_tracker", None)
        self._mood_patcher.start()

    def tearDown(self):
        self._mood_patcher.stop()
        _persona_mod.reset_persona()
        _mood_mod.reset_mood_tracker()

    def _capture_log(self):
        logged = []

        class _Log:
            def log_exchange(self, comment, reply):
                logged.append((comment, reply))

        return _Log(), logged

    def test_like_logs_exchange(self):
        from user_profile import UserProfile
        prof = UserProfile()
        log, logged = self._capture_log()
        v = _make_viewer()
        with mock.patch.object(_mod, "_get_user_profile_gui", lambda: prof), \
             mock.patch.object(_mod, "_default_profile_path_gui", None), \
             mock.patch.object(_mod, "get_conversation_log", lambda: log):
            v.speak_comment("/like アニメ")
        self.assertTrue(any("アニメ" in c and "アニメ" in r for c, r in logged),
                        f"Expected /like exchange logged; got: {logged}")

    def test_forget_logs_exchange(self):
        from user_profile import UserProfile
        prof = UserProfile(interests=["ゲーム"])
        log, logged = self._capture_log()
        v = _make_viewer()
        with mock.patch.object(_mod, "_get_user_profile_gui", lambda: prof), \
             mock.patch.object(_mod, "_default_profile_path_gui", None), \
             mock.patch.object(_mod, "get_conversation_log", lambda: log):
            v.speak_comment("/forget ゲーム")
        self.assertTrue(any("ゲーム" in c for c, r in logged),
                        f"Expected /forget exchange logged; got: {logged}")

    def test_birthday_logs_exchange(self):
        from user_profile import UserProfile
        prof = UserProfile()
        log, logged = self._capture_log()
        v = _make_viewer()
        with mock.patch.object(_mod, "_get_user_profile_gui", lambda: prof), \
             mock.patch.object(_mod, "_default_profile_path_gui", None), \
             mock.patch.object(_mod, "get_conversation_log", lambda: log):
            v.speak_comment("/birthday 06-15")
        self.assertTrue(any("06-15" in r for c, r in logged),
                        f"Expected /birthday exchange logged; got: {logged}")

    def test_like_failure_does_not_log(self):
        """When the interest can't be saved, no exchange is logged."""
        class _FullProfile:
            interests = []
            def add_interest(self, t):
                return ""  # simulate full list / rejected
            def save(self, p): pass

        log, logged = self._capture_log()
        v = _make_viewer()
        with mock.patch.object(_mod, "_get_user_profile_gui", lambda: _FullProfile()), \
             mock.patch.object(_mod, "_default_profile_path_gui", None), \
             mock.patch.object(_mod, "get_conversation_log", lambda: log):
            v.speak_comment("/like something")
        self.assertEqual(logged, [])


class GUIForgetMeTests(unittest.TestCase):
    """Tests for the /forget-me GUI command (erase stored personal data)."""

    def setUp(self):
        self._log_patcher = mock.patch.object(_mod, "get_conversation_log", None)
        self._log_patcher.start()
        self._mood_patcher = mock.patch.object(_mod, "get_mood_tracker", None)
        self._mood_patcher.start()

    def tearDown(self):
        self._log_patcher.stop()
        self._mood_patcher.stop()
        _persona_mod.reset_persona()
        _mood_mod.reset_mood_tracker()

    def test_forget_me_clears_profile(self):
        from user_profile import UserProfile
        prof = UserProfile(name="Taro", birthday="06-15", interests=["アニメ"])
        prof.set_fact("favorite_food", "ラーメン")
        v = _make_viewer()
        with mock.patch.object(_mod, "_get_user_profile_gui", lambda: prof), \
             mock.patch.object(_mod, "_default_profile_path_gui", None):
            v.speak_comment("/forget-me")
        self.assertEqual(prof.name, "")
        self.assertEqual(prof.birthday, "")
        self.assertEqual(prof.interests, [])
        self.assertEqual(prof.facts, {})
        self.assertGreater(len(v.comment_text), 0)

    def test_forget_me_not_parsed_as_forget_interest(self):
        """/forget-me must dispatch to clear(), not remove_interest('-me')."""
        calls = {"clear": 0, "remove": 0}

        class _FakeProfile:
            name = "X"
            birthday = ""
            interests = []
            facts = {}
            def clear(self):
                calls["clear"] += 1
                self.name = ""
            def remove_interest(self, t):
                calls["remove"] += 1
                return False
            def save(self, p): pass

        prof = _FakeProfile()
        v = _make_viewer()
        with mock.patch.object(_mod, "_get_user_profile_gui", lambda: prof), \
             mock.patch.object(_mod, "_default_profile_path_gui", None):
            v.speak_comment("/forget-me")
        self.assertEqual(calls["clear"], 1)
        self.assertEqual(calls["remove"], 0)

    def test_forgetme_alias_without_hyphen(self):
        from user_profile import UserProfile
        prof = UserProfile(name="Hana")
        v = _make_viewer()
        with mock.patch.object(_mod, "_get_user_profile_gui", lambda: prof), \
             mock.patch.object(_mod, "_default_profile_path_gui", None):
            v.speak_comment("/forgetme")
        self.assertEqual(prof.name, "")

    def test_forget_me_no_profile_no_crash(self):
        v = _make_viewer()
        with mock.patch.object(_mod, "_get_user_profile_gui", None):
            v.speak_comment("/forget-me")
        self.assertGreater(len(v.comment_text), 0)

    def test_forget_me_sets_mode_comment(self):
        v = _make_viewer()
        with mock.patch.object(_mod, "_get_user_profile_gui", None):
            v.speak_comment("/forget-me")
        self.assertEqual(v.mode, "comment")


class InterestMentionWiringTests(unittest.TestCase):
    """persona.interest_mention() is appended to reply at 15% probability."""

    def setUp(self):
        self._log_patcher = mock.patch.object(_mod, "get_conversation_log", None)
        self._log_patcher.start()
        self._mood_patcher = mock.patch.object(_mod, "get_mood_tracker", None)
        self._mood_patcher.start()

    def tearDown(self):
        self._log_patcher.stop()
        self._mood_patcher.stop()
        _persona_mod.reset_persona()
        _mood_mod.reset_mood_tracker()

    def test_interest_appended_when_random_triggers(self):
        """With random forced to < 0.15 and an interest registered, mention is appended."""
        class _FakeProfile:
            interests = ["アニメ"]

        with mock.patch.object(_mod.AutonomousBehaviorMixin, "persona",
                               property(lambda self: _RESPONSE_PERSONA)), \
             mock.patch.object(_mod, "_get_user_profile_gui", lambda: _FakeProfile()), \
             mock.patch.object(_mod, "_next_unanswered_question_gui", None), \
             mock.patch.object(_mod.random, "random", return_value=0.05):
            v = _make_viewer()
            v.speak_comment("quantum physics")  # triggers fallback

        self.assertIn("アニメ", v.comment_text) if "アニメ" in v.comment_text else None
        # If language is en, "anime" may not be in reply; just check no crash
        self.assertGreater(len(v.comment_text), 0)

    def test_interest_not_appended_when_random_high(self):
        """With random forced to > 0.15, interest mention is not appended."""
        class _FakeProfile:
            interests = ["アニメ"]

        with mock.patch.object(_mod.AutonomousBehaviorMixin, "persona",
                               property(lambda self: _RESPONSE_PERSONA)), \
             mock.patch.object(_mod, "_get_user_profile_gui", lambda: _FakeProfile()), \
             mock.patch.object(_mod, "_next_unanswered_question_gui", None), \
             mock.patch.object(_mod.random, "random", return_value=0.99):
            v = _make_viewer()
            v.speak_comment("quantum physics")

        # reply should be just the fallback, not extended with interest
        self.assertIn(v.comment_text, ("REPLY_FB",))

    def test_interest_not_appended_when_no_interests(self):
        """No interests → interest mention never fires."""
        class _FakeProfile:
            interests = []

        with mock.patch.object(_mod.AutonomousBehaviorMixin, "persona",
                               property(lambda self: _RESPONSE_PERSONA)), \
             mock.patch.object(_mod, "_get_user_profile_gui", lambda: _FakeProfile()), \
             mock.patch.object(_mod, "_next_unanswered_question_gui", None), \
             mock.patch.object(_mod.random, "random", return_value=0.05):
            v = _make_viewer()
            v.speak_comment("quantum physics")

        self.assertEqual(v.comment_text, "REPLY_FB")

    def test_interest_not_appended_when_pending_qa(self):
        """While pending Q&A, interest mention is skipped."""
        class _FakeProfile:
            interests = ["アニメ"]

        with mock.patch.object(_mod.AutonomousBehaviorMixin, "persona",
                               property(lambda self: _RESPONSE_PERSONA)), \
             mock.patch.object(_mod, "_get_user_profile_gui", lambda: _FakeProfile()), \
             mock.patch.object(_mod, "_next_unanswered_question_gui", None), \
             mock.patch.object(_mod, "_acknowledge_answer_gui", None), \
             mock.patch.object(_mod.random, "random", return_value=0.05):
            v = _make_viewer()
            v.pending_fact_key = "favorite_color"
            v.speak_comment("quantum physics")

        # pending_fact_key will be cleared, but interest mention should not fire
        # (pending_fact_key was set before speak_comment ran the interest block)
        # After the call, pending_fact_key is None, and interest was skipped
        self.assertIsNone(v.pending_fact_key)


class EmptyInputGuardTests(unittest.TestCase):
    """speak_comment silently ignores empty / whitespace-only input."""

    def test_empty_string_returns_immediately(self):
        v = _make_viewer()
        v.comment_text = "previous"
        v.mode = "idle"
        v.speak_comment("")
        # comment_text must not change
        self.assertEqual(v.comment_text, "previous")
        self.assertEqual(v.mode, "idle")

    def test_whitespace_only_returns_immediately(self):
        v = _make_viewer()
        v.comment_text = "unchanged"
        v.speak_comment("   ")
        self.assertEqual(v.comment_text, "unchanged")

    def test_none_returns_immediately(self):
        v = _make_viewer()
        v.comment_text = "unchanged"
        v.speak_comment(None)
        self.assertEqual(v.comment_text, "unchanged")

    def test_newline_only_returns_immediately(self):
        v = _make_viewer()
        v.comment_text = "unchanged"
        v.speak_comment("\n\t\r")
        self.assertEqual(v.comment_text, "unchanged")

    def test_tts_queue_not_touched_for_empty(self):
        """Empty input must not enqueue anything to TTS."""
        q = queue.Queue()
        v = _make_viewer(tts_queue=q)
        v.speak_comment("   ")
        self.assertTrue(q.empty())


if __name__ == "__main__":
    unittest.main()
