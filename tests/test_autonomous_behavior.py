"""
Unit tests for autonomous_behavior.AutonomousBehaviorMixin — the run/rest/talk
state machine extracted from the three autonomous avatar viewers.

The mixin operates on plain attributes, so it is testable without Qt/numpy.
"""
import contextlib
import os
import sys
import unittest
from unittest import mock

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import autonomous_behavior  # noqa: E402
from autonomous_behavior import AutonomousBehaviorMixin  # noqa: E402


class _Dummy(AutonomousBehaviorMixin):
    def __init__(self):
        self.position = [0.0, 0.0]
        self.direction = 0.0
        self.mode = 'run'
        self.ticks = 0
        self.talk_text = ''
        self.talks = ['hello', 'world']


class _TalkHookDummy(_Dummy):
    def __init__(self):
        super().__init__()
        self.spoken = []

    def _on_talk_start(self, text):
        self.spoken.append(text)


class _RunExtraDummy(_Dummy):
    def __init__(self):
        super().__init__()
        self.extra_calls = 0

    def _autonomous_run_extra(self):
        self.extra_calls += 1


def _step_until_mode(obj, mode, max_steps=500):
    for _ in range(max_steps):
        obj._advance_autonomous_state()
        if obj.mode == mode:
            return True
    return False


class StateMachineTests(unittest.TestCase):
    """State-machine mechanics — isolated from persona config so the
    fallback self.talks / REST_TEXTS path is exercised deterministically."""

    def setUp(self):
        self._patcher = mock.patch.object(autonomous_behavior, "get_persona", None)
        self._patcher.start()
        self._mood_patcher = mock.patch.object(autonomous_behavior, "_get_mood_tracker", None)
        self._mood_patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._mood_patcher.stop()

    def test_run_transitions_to_rest(self):
        d = _Dummy()
        self.assertTrue(_step_until_mode(d, 'rest'))
        self.assertEqual(d.ticks, 0, "ticks must reset on transition")

    def test_full_cycle_run_rest_talk_run(self):
        d = _Dummy()
        self.assertTrue(_step_until_mode(d, 'rest'))
        self.assertTrue(_step_until_mode(d, 'talk'))
        self.assertTrue(_step_until_mode(d, 'run'))
        self.assertEqual(d.talk_text, '', "talk_text must clear when returning to run")

    def test_rest_sets_rest_text_on_first_tick(self):
        d = _Dummy()
        self.assertTrue(_step_until_mode(d, 'rest'))
        d._advance_autonomous_state()  # first tick of rest
        self.assertIn(d.talk_text, AutonomousBehaviorMixin.REST_TEXTS)

    def test_talk_picks_from_talks_and_fires_hook(self):
        d = _TalkHookDummy()
        self.assertTrue(_step_until_mode(d, 'talk'))
        d._advance_autonomous_state()  # first tick of talk
        self.assertIn(d.talk_text, d.talks)
        self.assertEqual(d.spoken, [d.talk_text])

    def test_run_extra_hook_called_each_run_tick(self):
        d = _RunExtraDummy()
        d._advance_autonomous_state()
        d._advance_autonomous_state()
        self.assertEqual(d.extra_calls, 2)

    def test_direction_reset_flag(self):
        class _Resetting(_Dummy):
            reset_direction_on_run = True

        d = _Resetting()
        d.direction = 12345.0  # sentinel that random.uniform(0,360) cannot return
        self.assertTrue(_step_until_mode(d, 'rest'))
        d.direction = 12345.0
        self.assertTrue(_step_until_mode(d, 'talk'))
        d.direction = 12345.0
        self.assertTrue(_step_until_mode(d, 'run'))
        self.assertNotEqual(d.direction, 12345.0, "direction must reset on talk→run")

    def test_no_direction_reset_by_default(self):
        d = _Dummy()
        self.assertTrue(_step_until_mode(d, 'rest'))
        self.assertTrue(_step_until_mode(d, 'talk'))
        d.direction = 12345.0
        self.assertTrue(_step_until_mode(d, 'run'))
        self.assertEqual(d.direction, 12345.0)

    def test_unknown_mode_is_noop_except_ticks(self):
        d = _Dummy()
        d.mode = 'comment'
        d._advance_autonomous_state()
        self.assertEqual(d.mode, 'comment')
        self.assertEqual(d.ticks, 1)


class _StartStopDummy(_Dummy):
    def __init__(self):
        super().__init__()
        self.is_autonomous = False
        self.updated = 0

    def update(self):
        self.updated += 1


class _ExtraFieldDummy(_StartStopDummy):
    EXTRA_TEXT_FIELDS = ('comment_text',)

    def __init__(self):
        super().__init__()
        self.comment_text = 'leftover'


class StartStopTests(unittest.TestCase):
    """start/stop mechanics — persona disabled so start does not inject a greeting."""

    def setUp(self):
        self._patcher = mock.patch.object(autonomous_behavior, "get_persona", None)
        self._patcher.start()
        self._mood_patcher = mock.patch.object(autonomous_behavior, "_get_mood_tracker", None)
        self._mood_patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._mood_patcher.stop()

    def test_start_enters_run_mode(self):
        d = _StartStopDummy()
        d.talk_text = 'stale'
        d.ticks = 99
        d.start_autonomous()
        self.assertTrue(d.is_autonomous)
        self.assertEqual(d.mode, 'run')
        self.assertEqual(d.ticks, 0)
        self.assertEqual(d.talk_text, '')
        self.assertTrue(0 <= d.direction <= 360)

    def test_stop_returns_to_idle_and_calls_update(self):
        d = _StartStopDummy()
        d.start_autonomous()
        d.talk_text = 'talking'
        d.stop_autonomous()
        self.assertFalse(d.is_autonomous)
        self.assertEqual(d.mode, 'idle')
        self.assertEqual(d.talk_text, '')
        self.assertEqual(d.updated, 1)

    def test_extra_text_fields_reset_on_start(self):
        d = _ExtraFieldDummy()
        d.start_autonomous()
        self.assertEqual(d.comment_text, '')

    def test_extra_text_fields_reset_on_stop(self):
        d = _ExtraFieldDummy()
        d.comment_text = 'speaking'
        d.stop_autonomous()
        self.assertEqual(d.comment_text, '')


class _FakePersona:
    """Deterministic stand-in for persona.Persona."""
    def greeting(self, *a, **kw):
        return 'GREETING'
    def talk(self, *a, **kw):
        return 'PERSONA_TALK'
    def rest(self, *a, **kw):
        return 'PERSONA_REST'


class PersonaIntegrationTests(unittest.TestCase):
    """When a persona is available it drives the avatar's lines (overriding the
    hardcoded self.talks / REST_TEXTS), and start injects a time-aware greeting."""

    def setUp(self):
        self._patcher = mock.patch.object(
            autonomous_behavior, "get_persona", lambda *a, **k: _FakePersona()
        )
        self._patcher.start()
        self._mood_patcher = mock.patch.object(autonomous_behavior, "_get_mood_tracker", None)
        self._mood_patcher.start()
        # Suppress yesterday_greeting and summary_greeting so tests don't append summary text
        self._summary_patcher = mock.patch.object(
            autonomous_behavior, "_yesterday_greeting", lambda **kw: ""
        )
        self._summary_patcher.start()
        self._today_summary_patcher = mock.patch.object(
            autonomous_behavior, "_summary_greeting", lambda **kw: ""
        )
        self._today_summary_patcher.start()
        # Suppress date-dependent special-day greetings so equality tests are
        # deterministic regardless of the calendar date the suite runs on.
        self._season_patcher = mock.patch.object(
            autonomous_behavior, "_seasonal_greeting", lambda **kw: ""
        )
        self._season_patcher.start()
        self._bday_patcher = mock.patch.object(
            autonomous_behavior, "_birthday_greeting", lambda *a, **k: ""
        )
        self._bday_patcher.start()
        self._daily_mood_patcher = mock.patch.object(
            autonomous_behavior, "_get_daily_mood", lambda **kw: "calm"
        )
        self._daily_mood_patcher.start()
        self._daily_desc_patcher = mock.patch.object(
            autonomous_behavior, "_mood_description", lambda *a, **kw: ""
        )
        self._daily_desc_patcher.start()
        # Suppress wellbeing so exact-string equality assertions are deterministic
        self._wb_patcher = mock.patch.object(
            autonomous_behavior, "_wellbeing_reflection", lambda *a, **kw: ""
        )
        self._wb_patcher.start()
        # Suppress usage guardrail (same reason: it appends to the greeting).
        self._ug_patcher = mock.patch.object(
            autonomous_behavior, "_usage_reflection", lambda *a, **kw: ""
        )
        self._ug_patcher.start()

    def tearDown(self):
        self._ug_patcher.stop()
        self._patcher.stop()
        self._mood_patcher.stop()
        self._summary_patcher.stop()
        self._today_summary_patcher.stop()
        self._season_patcher.stop()
        self._bday_patcher.stop()
        self._daily_mood_patcher.stop()
        self._daily_desc_patcher.stop()
        self._wb_patcher.stop()

    def test_start_sets_greeting_from_persona(self):
        d = _StartStopDummy()
        d.start_autonomous()
        self.assertEqual(d.talk_text, 'GREETING')

    def test_start_greeting_fires_talk_hook(self):
        d = _TalkHookDummy()
        d.is_autonomous = False
        d.start_autonomous()
        self.assertEqual(d.spoken, ['GREETING'])

    def test_talk_uses_persona_over_talks(self):
        d = _Dummy()  # self.talks = ['hello', 'world']
        self.assertTrue(_step_until_mode(d, 'talk'))
        d._advance_autonomous_state()  # first tick of talk
        self.assertEqual(d.talk_text, 'PERSONA_TALK')

    def test_rest_uses_persona_over_rest_texts(self):
        d = _Dummy()
        self.assertTrue(_step_until_mode(d, 'rest'))
        d._advance_autonomous_state()  # first tick of rest
        self.assertEqual(d.talk_text, 'PERSONA_REST')

    def test_pick_talk_text_passes_mood_level_to_persona(self):
        """_pick_talk_text() forwards mood level to persona.talk(level=)."""
        captured = {}

        class _LevelCapture(_FakePersona):
            def talk(self, *a, **kw):
                captured['level'] = kw.get('level')
                return 'TALK'

        class _FakeTracker:
            level = "close"

        with mock.patch.object(autonomous_behavior, "get_persona",
                               lambda *a, **k: _LevelCapture()), \
             mock.patch.object(autonomous_behavior, "_get_mood_tracker",
                               lambda: _FakeTracker()), \
             mock.patch.object(autonomous_behavior, "_get_user_profile",
                               lambda: None):
            d = _Dummy()
            text = d._pick_talk_text()

        self.assertEqual(captured.get('level'), 'close')
        self.assertEqual(text, 'TALK')

    def test_empty_persona_line_falls_back_to_talks(self):
        class _Empty(_FakePersona):
            def talk(self, *a, **kw):
                return ''
        with mock.patch.object(autonomous_behavior, "get_persona", lambda *a, **k: _Empty()):
            d = _Dummy()
            self.assertTrue(_step_until_mode(d, 'talk'))
            d._advance_autonomous_state()
            self.assertIn(d.talk_text, d.talks)


class MoodGreetingIntegrationTests(unittest.TestCase):
    """start_autonomous passes mood level to persona.greeting() and calls auto_decay()."""

    def _fake_persona_level_capture(self):
        """Persona that records the level kwarg passed to greeting()."""
        captured = []

        class _LevelCapture:
            name = "Test"

            def greeting(self, lang=None, now=None, level=None):
                captured.append(level)
                return f"GREETING_{level}"

            def talk(self, *a, **kw):
                return "TALK"

            def rest(self, *a, **kw):
                return "REST"

        return _LevelCapture(), captured

    def test_start_passes_mood_level_to_greeting(self):
        """When mood tracker is present, its level is forwarded to greeting()."""
        fake_persona, captured_levels = self._fake_persona_level_capture()

        class _FakeTracker:
            level = "close"
            interactions = 5
            _last_interaction_time = 0.0

            def auto_decay(self):
                pass

        with mock.patch.object(autonomous_behavior, "get_persona",
                               lambda *a, **k: fake_persona):
            with mock.patch.object(autonomous_behavior, "_get_mood_tracker",
                                   lambda: _FakeTracker()):
                with mock.patch.object(autonomous_behavior, "_yesterday_greeting",
                                       lambda **kw: ""):
                    with mock.patch.object(autonomous_behavior, "_summary_greeting",
                                           lambda **kw: ""):
                        with mock.patch.object(autonomous_behavior, "_mood_description",
                                               lambda *a, **kw: ""):
                            with mock.patch.object(autonomous_behavior, "_check_daily_login",
                                                   lambda *a, **kw: ""):
                                with mock.patch.object(autonomous_behavior,
                                                       "_wellbeing_reflection",
                                                       lambda *a, **kw: ""):
                                    with mock.patch.object(autonomous_behavior,
                                                           "_usage_reflection",
                                                           lambda *a, **kw: ""):
                                        d = _StartStopDummy()
                                        d.start_autonomous()

        self.assertEqual(captured_levels, ["close"])
        self.assertEqual(d.talk_text, "GREETING_close")

    def test_start_calls_auto_decay(self):
        """auto_decay() is called on the tracker when start_autonomous() runs."""
        decay_calls = []

        class _FakeTracker:
            level = "neutral"
            interactions = 3
            _last_interaction_time = 0.0

            def auto_decay(self):
                decay_calls.append(True)

        with mock.patch.object(autonomous_behavior, "get_persona", None):
            with mock.patch.object(autonomous_behavior, "_get_mood_tracker",
                                   lambda: _FakeTracker()):
                d = _StartStopDummy()
                d.start_autonomous()

        self.assertEqual(decay_calls, [True])

    def test_absence_message_appended_to_greeting_after_long_absence(self):
        """When user has been absent >24h, absence_message is appended to the startup greeting."""
        import time

        class _AbsentTracker:
            level = "neutral"
            interactions = 5
            _last_interaction_time = time.time() - 48 * 3600  # 2 days ago

            def auto_decay(self):
                pass

            def snapshot_to_history(self, path):
                pass

        captured = []

        class _GreetingDummy(_StartStopDummy):
            def _on_talk_start(self, text):
                captured.append(text)

        with mock.patch.object(autonomous_behavior, "get_persona",
                               lambda: _FakePersona()):
            with mock.patch.object(autonomous_behavior, "_get_mood_tracker",
                                   lambda: _AbsentTracker()):
                with mock.patch.object(autonomous_behavior, "_mood_history_path", None):
                    with mock.patch.object(autonomous_behavior, "_yesterday_greeting",
                                           lambda **kw: ""):
                        d = _GreetingDummy()
                        d.start_autonomous()

        self.assertTrue(len(captured) == 1)
        # Greeting should include both the persona greeting and the absence note
        greeting_text = captured[0]
        self.assertIn("GREETING", greeting_text)
        # Absence message should be present (ja: 日ぶり or "missed")
        self.assertTrue(
            any(word in greeting_text for word in ["日ぶり", "missed"]),
            f"Expected absence message in greeting, got: {greeting_text!r}"
        )

    def test_absence_message_failure_does_not_break_start(self):
        """If absence_message raises, start_autonomous still completes."""
        with mock.patch.object(autonomous_behavior, "get_persona",
                               lambda: _FakePersona()):
            with mock.patch.object(autonomous_behavior, "_get_mood_tracker",
                                   lambda: None):  # will cause AttributeError in absence_message
                with mock.patch.object(autonomous_behavior, "_absence_message",
                                       lambda tracker, lang: (_ for _ in ()).throw(RuntimeError("boom"))):
                    with mock.patch.object(autonomous_behavior, "_yesterday_greeting",
                                           lambda **kw: ""):
                        d = _StartStopDummy()
                        d.start_autonomous()  # must not raise
        self.assertTrue(d.is_autonomous)

    def test_mood_tracker_failure_does_not_break_start(self):
        """If the mood tracker raises, start_autonomous still completes safely."""
        def _boom():
            raise RuntimeError("db locked")

        with mock.patch.object(autonomous_behavior, "get_persona", None):
            with mock.patch.object(autonomous_behavior, "_get_mood_tracker", _boom):
                d = _StartStopDummy()
                d.start_autonomous()  # must not raise

        self.assertTrue(d.is_autonomous)


class SpecialDaysIntegrationTests(unittest.TestCase):
    """start_autonomous appends birthday / seasonal greetings (dating-sim flavor)."""

    def _greeting_dummy(self, captured):
        class _GreetingDummy(_StartStopDummy):
            def _on_talk_start(self, text):
                captured.append(text)
        return _GreetingDummy()

    def test_birthday_appended_and_bonus_applied(self):
        captured = []

        class _Tracker:
            level = "neutral"
            adjusted = 0.0

            def auto_decay(self):
                return 0.0

            def snapshot_to_history(self, p):
                return True

            def adjust(self, d):
                self.adjusted += d
                return d

            def save(self, p):
                return True

        tracker = _Tracker()
        with mock.patch.object(autonomous_behavior, "get_persona",
                               lambda *a, **k: _FakePersona()), \
             mock.patch.object(autonomous_behavior, "_get_mood_tracker", lambda: tracker), \
             mock.patch.object(autonomous_behavior, "_mood_history_path", None), \
             mock.patch.object(autonomous_behavior, "_mood_path", None), \
             mock.patch.object(autonomous_behavior, "_yesterday_greeting", lambda **kw: ""), \
             mock.patch.object(autonomous_behavior, "_anniversary_message", lambda *a, **k: ""), \
             mock.patch.object(autonomous_behavior, "_absence_message", lambda *a, **k: ""), \
             mock.patch.object(autonomous_behavior, "_seasonal_greeting", lambda **kw: ""), \
             mock.patch.object(autonomous_behavior, "_check_daily_login", lambda *a, **k: ""), \
             mock.patch.object(autonomous_behavior, "_get_user_profile", lambda: object()), \
             mock.patch.object(autonomous_behavior, "_profile_path", None), \
             mock.patch.object(autonomous_behavior, "_birthday_greeting",
                               lambda *a, **k: "HAPPY_BIRTHDAY"):
            d = self._greeting_dummy(captured)
            d.start_autonomous()

        self.assertTrue(any("HAPPY_BIRTHDAY" in t for t in captured))
        self.assertEqual(tracker.adjusted, autonomous_behavior._BIRTHDAY_BONUS)

    def test_seasonal_greeting_appended(self):
        captured = []
        with mock.patch.object(autonomous_behavior, "get_persona",
                               lambda *a, **k: _FakePersona()), \
             mock.patch.object(autonomous_behavior, "_get_mood_tracker", None), \
             mock.patch.object(autonomous_behavior, "_yesterday_greeting", lambda **kw: ""), \
             mock.patch.object(autonomous_behavior, "_birthday_greeting", lambda *a, **k: ""), \
             mock.patch.object(autonomous_behavior, "_seasonal_greeting",
                               lambda **kw: "MERRY_XMAS"):
            d = self._greeting_dummy(captured)
            d.start_autonomous()
        self.assertTrue(any("MERRY_XMAS" in t for t in captured))

    def test_special_day_failure_does_not_break_start(self):
        with mock.patch.object(autonomous_behavior, "get_persona",
                               lambda *a, **k: _FakePersona()), \
             mock.patch.object(autonomous_behavior, "_get_mood_tracker", None), \
             mock.patch.object(autonomous_behavior, "_yesterday_greeting", lambda **kw: ""), \
             mock.patch.object(autonomous_behavior, "_birthday_greeting", lambda *a, **k: ""), \
             mock.patch.object(autonomous_behavior, "_seasonal_greeting",
                               lambda **kw: (_ for _ in ()).throw(RuntimeError("boom"))):
            d = _StartStopDummy()
            d.start_autonomous()  # must not raise
        self.assertTrue(d.is_autonomous)

    def _start_with_daily_mood(self, captured, first_meeting):
        with mock.patch.object(autonomous_behavior, "get_persona",
                               lambda *a, **k: _FakePersona()), \
             mock.patch.object(autonomous_behavior, "_get_mood_tracker", None), \
             mock.patch.object(autonomous_behavior, "_is_first_meeting_ab",
                               lambda *a, **k: first_meeting), \
             mock.patch.object(autonomous_behavior, "_yesterday_greeting", lambda **kw: ""), \
             mock.patch.object(autonomous_behavior, "_birthday_greeting", lambda *a, **k: ""), \
             mock.patch.object(autonomous_behavior, "_seasonal_greeting", lambda **kw: ""), \
             mock.patch.object(autonomous_behavior, "_get_daily_mood", lambda **kw: "cheerful"), \
             mock.patch.object(autonomous_behavior, "_mood_description",
                               lambda *a, **kw: "DAILY_DESC"):
            d = self._greeting_dummy(captured)
            d.start_autonomous()

    def test_daily_mood_description_appended_to_greeting(self):
        captured = []
        self._start_with_daily_mood(captured, first_meeting=False)
        self.assertTrue(any("DAILY_DESC" in t for t in captured))

    def test_daily_mood_is_omitted_on_a_first_meeting(self):
        """初対面ではデイリームードを添えないこと。

        ムードの価値は「日ごとに違う」ことにあるが、初日には比べる昨日が無い。
        しかも 6 種のうち melancholy は「そっとしておいてくれると嬉しいかも」で、
        初対面の 3 番目の発話がこれになると個性ではなく拒絶として読まれる。
        日付だけで決まるので、新規ユーザーの 1/6 がそれを引く。
        """
        captured = []
        self._start_with_daily_mood(captured, first_meeting=True)
        self.assertFalse(any("DAILY_DESC" in t for t in captured), captured)
        self.assertTrue(any(t.strip() for t in captured), "挨拶まで消えている")

    def test_daily_mood_failure_does_not_break_start(self):
        with mock.patch.object(autonomous_behavior, "get_persona",
                               lambda *a, **k: _FakePersona()), \
             mock.patch.object(autonomous_behavior, "_get_mood_tracker", None), \
             mock.patch.object(autonomous_behavior, "_yesterday_greeting", lambda **kw: ""), \
             mock.patch.object(autonomous_behavior, "_birthday_greeting", lambda *a, **k: ""), \
             mock.patch.object(autonomous_behavior, "_seasonal_greeting", lambda **kw: ""), \
             mock.patch.object(autonomous_behavior, "_get_daily_mood",
                               lambda **kw: (_ for _ in ()).throw(RuntimeError("daily_boom"))):
            d = _StartStopDummy()
            d.start_autonomous()  # must not raise
        self.assertTrue(d.is_autonomous)


class InterestTalkTests(unittest.TestCase):
    """_pick_talk_text() should reference registered interests at neutral+ levels."""

    class _FakeTracker:
        def __init__(self, level="neutral"):
            self.level = level

    class _FakeProfile:
        def __init__(self, interests=None):
            self.interests = interests or []
            self.name = ""

    class _FakePersona:
        lang = "ja"

        def talk(self, *a, **kw):
            return "GENERIC_TALK"

        def rest(self, *a, **kw):
            return "GENERIC_REST"

        def greeting(self, *a, **kw):
            return "GREETING"

    def _make_dummy(self):
        d = _Dummy()
        return d

    def test_interest_talk_fires_at_neutral_with_interests(self):
        """With interests registered and neutral level, _pick_talk_text may reference one."""
        profile = self._FakeProfile(interests=["アニメ"])
        tracker = self._FakeTracker("neutral")
        with mock.patch.object(autonomous_behavior, "get_persona",
                               lambda *a, **k: self._FakePersona()), \
             mock.patch.object(autonomous_behavior, "_get_mood_tracker",
                               lambda: tracker), \
             mock.patch.object(autonomous_behavior, "_get_user_profile",
                               lambda: profile), \
             mock.patch.object(autonomous_behavior, "_get_daily_mood", None), \
             mock.patch("autonomous_behavior.random.random", return_value=0.0):
            d = self._make_dummy()
            text = d._pick_talk_text()
        self.assertIn("アニメ", text)

    def test_interest_talk_not_fired_at_distant(self):
        """Distant level should not trigger interest-based talk."""
        profile = self._FakeProfile(interests=["ゲーム"])
        tracker = self._FakeTracker("distant")
        with mock.patch.object(autonomous_behavior, "get_persona",
                               lambda *a, **k: self._FakePersona()), \
             mock.patch.object(autonomous_behavior, "_get_mood_tracker",
                               lambda: tracker), \
             mock.patch.object(autonomous_behavior, "_get_user_profile",
                               lambda: profile), \
             mock.patch.object(autonomous_behavior, "_get_daily_mood", None), \
             mock.patch("autonomous_behavior.random.random", return_value=0.0):
            d = self._make_dummy()
            text = d._pick_talk_text()
        # Should fall back to persona talk, not interest
        self.assertEqual(text, "GENERIC_TALK")
        self.assertNotIn("ゲーム", text)

    def test_interest_talk_not_fired_when_no_interests(self):
        """Empty interests list should not trigger interest talk."""
        profile = self._FakeProfile(interests=[])
        tracker = self._FakeTracker("friendly")
        with mock.patch.object(autonomous_behavior, "get_persona",
                               lambda *a, **k: self._FakePersona()), \
             mock.patch.object(autonomous_behavior, "_get_mood_tracker",
                               lambda: tracker), \
             mock.patch.object(autonomous_behavior, "_get_user_profile",
                               lambda: profile), \
             mock.patch.object(autonomous_behavior, "_get_daily_mood", None), \
             mock.patch("autonomous_behavior.random.random", return_value=0.0):
            d = self._make_dummy()
            text = d._pick_talk_text()
        self.assertEqual(text, "GENERIC_TALK")

    def test_interest_talk_not_fired_at_high_random(self):
        """High random value should skip interest talk (probability gate)."""
        profile = self._FakeProfile(interests=["音楽"])
        tracker = self._FakeTracker("close")
        with mock.patch.object(autonomous_behavior, "get_persona",
                               lambda *a, **k: self._FakePersona()), \
             mock.patch.object(autonomous_behavior, "_get_mood_tracker",
                               lambda: tracker), \
             mock.patch.object(autonomous_behavior, "_get_user_profile",
                               lambda: profile), \
             mock.patch.object(autonomous_behavior, "_get_daily_mood", None), \
             mock.patch("autonomous_behavior.random.random", return_value=0.99):
            d = self._make_dummy()
            text = d._pick_talk_text()
        self.assertEqual(text, "GENERIC_TALK")

    def test_interest_talk_en_template(self):
        """English persona uses English templates."""
        class _EnPersona(self._FakePersona):
            lang = "en"

            def talk(self, *a, **kw):
                return "EN_TALK"

        profile = self._FakeProfile(interests=["anime"])
        tracker = self._FakeTracker("friendly")
        with mock.patch.object(autonomous_behavior, "get_persona",
                               lambda *a, **k: _EnPersona()), \
             mock.patch.object(autonomous_behavior, "_get_mood_tracker",
                               lambda: tracker), \
             mock.patch.object(autonomous_behavior, "_get_user_profile",
                               lambda: profile), \
             mock.patch.object(autonomous_behavior, "_get_daily_mood", None), \
             mock.patch("autonomous_behavior.random.random", return_value=0.0):
            d = self._make_dummy()
            text = d._pick_talk_text()
        self.assertIn("anime", text)

    def test_interest_exception_falls_back_gracefully(self):
        """Exception during interest lookup must not crash pick_talk_text."""
        def _bad_profile():
            raise RuntimeError("profile boom")

        with mock.patch.object(autonomous_behavior, "get_persona",
                               lambda *a, **k: self._FakePersona()), \
             mock.patch.object(autonomous_behavior, "_get_mood_tracker",
                               lambda: self._FakeTracker("neutral")), \
             mock.patch.object(autonomous_behavior, "_get_user_profile",
                               _bad_profile), \
             mock.patch.object(autonomous_behavior, "_get_daily_mood", None):
            d = self._make_dummy()
            text = d._pick_talk_text()
        self.assertIsInstance(text, str)
        self.assertGreater(len(text), 0)


class FactRecallTalkTests(unittest.TestCase):
    """_pick_talk_text() should recall stored user facts at neutral+ levels."""

    class _FakeTracker:
        def __init__(self, level="neutral"):
            self.level = level

    class _FakeProfile:
        def __init__(self, interests=None, facts=None):
            self.interests = interests or []
            self.facts = facts if facts is not None else {}
            self.name = ""

    class _FakePersona:
        lang = "ja"

        def talk(self, *a, **kw):
            return "GENERIC_TALK"

        def rest(self, *a, **kw):
            return "GENERIC_REST"

        def greeting(self, *a, **kw):
            return "GREETING"

    def test_fact_recall_fires_at_neutral_with_facts(self):
        """With facts stored and neutral level, recall fires when probability wins."""
        profile = self._FakeProfile(facts={"favorite_food": "ラーメン"})
        tracker = self._FakeTracker("neutral")
        with mock.patch.object(autonomous_behavior, "get_persona",
                               lambda *a, **k: self._FakePersona()), \
             mock.patch.object(autonomous_behavior, "_get_mood_tracker",
                               lambda: tracker), \
             mock.patch.object(autonomous_behavior, "_get_user_profile",
                               lambda: profile), \
             mock.patch.object(autonomous_behavior, "_get_daily_mood", None), \
             mock.patch.object(autonomous_behavior, "_recall_fact",
                               lambda *a, **kw: "RECALLED"), \
             mock.patch("autonomous_behavior.random.random", return_value=0.0):
            d = _Dummy()
            text = d._pick_talk_text()
        self.assertEqual(text, "RECALLED")

    def test_fact_recall_not_fired_at_distant(self):
        """Distant level should not trigger fact recall."""
        profile = self._FakeProfile(facts={"favorite_food": "ラーメン"})
        tracker = self._FakeTracker("distant")
        with mock.patch.object(autonomous_behavior, "get_persona",
                               lambda *a, **k: self._FakePersona()), \
             mock.patch.object(autonomous_behavior, "_get_mood_tracker",
                               lambda: tracker), \
             mock.patch.object(autonomous_behavior, "_get_user_profile",
                               lambda: profile), \
             mock.patch.object(autonomous_behavior, "_get_daily_mood", None), \
             mock.patch("autonomous_behavior.random.random", return_value=0.0):
            d = _Dummy()
            text = d._pick_talk_text()
        self.assertEqual(text, "GENERIC_TALK")

    def test_fact_recall_not_fired_when_facts_empty(self):
        """Empty facts dict should not trigger recall."""
        profile = self._FakeProfile(facts={})
        tracker = self._FakeTracker("friendly")
        with mock.patch.object(autonomous_behavior, "get_persona",
                               lambda *a, **k: self._FakePersona()), \
             mock.patch.object(autonomous_behavior, "_get_mood_tracker",
                               lambda: tracker), \
             mock.patch.object(autonomous_behavior, "_get_user_profile",
                               lambda: profile), \
             mock.patch.object(autonomous_behavior, "_get_daily_mood", None), \
             mock.patch("autonomous_behavior.random.random", return_value=0.0):
            d = _Dummy()
            text = d._pick_talk_text()
        self.assertEqual(text, "GENERIC_TALK")

    def test_fact_recall_not_fired_at_high_random(self):
        """High random value should skip fact recall (probability gate)."""
        profile = self._FakeProfile(facts={"hometown": "東京"})
        tracker = self._FakeTracker("close")
        with mock.patch.object(autonomous_behavior, "get_persona",
                               lambda *a, **k: self._FakePersona()), \
             mock.patch.object(autonomous_behavior, "_get_mood_tracker",
                               lambda: tracker), \
             mock.patch.object(autonomous_behavior, "_get_user_profile",
                               lambda: profile), \
             mock.patch.object(autonomous_behavior, "_get_daily_mood", None), \
             mock.patch("autonomous_behavior.random.random", return_value=0.99):
            d = _Dummy()
            text = d._pick_talk_text()
        self.assertEqual(text, "GENERIC_TALK")

    def test_fact_recall_empty_falls_through_to_persona(self):
        """If recall_fact returns empty string, fall through to persona.talk()."""
        profile = self._FakeProfile(facts={"favorite_food": "ラーメン"})
        tracker = self._FakeTracker("neutral")
        with mock.patch.object(autonomous_behavior, "get_persona",
                               lambda *a, **k: self._FakePersona()), \
             mock.patch.object(autonomous_behavior, "_get_mood_tracker",
                               lambda: tracker), \
             mock.patch.object(autonomous_behavior, "_get_user_profile",
                               lambda: profile), \
             mock.patch.object(autonomous_behavior, "_get_daily_mood", None), \
             mock.patch.object(autonomous_behavior, "_recall_fact",
                               lambda *a, **kw: ""), \
             mock.patch("autonomous_behavior.random.random", return_value=0.0):
            d = _Dummy()
            text = d._pick_talk_text()
        self.assertEqual(text, "GENERIC_TALK")

    def test_fact_recall_exception_falls_back_gracefully(self):
        """Exception during recall must not crash _pick_talk_text."""
        def _bad_recall(*a, **kw):
            raise RuntimeError("recall boom")

        profile = self._FakeProfile(facts={"favorite_food": "ラーメン"})
        tracker = self._FakeTracker("neutral")
        with mock.patch.object(autonomous_behavior, "get_persona",
                               lambda *a, **k: self._FakePersona()), \
             mock.patch.object(autonomous_behavior, "_get_mood_tracker",
                               lambda: tracker), \
             mock.patch.object(autonomous_behavior, "_get_user_profile",
                               lambda: profile), \
             mock.patch.object(autonomous_behavior, "_get_daily_mood", None), \
             mock.patch.object(autonomous_behavior, "_recall_fact", _bad_recall), \
             mock.patch("autonomous_behavior.random.random", return_value=0.0):
            d = _Dummy()
            text = d._pick_talk_text()
        self.assertIsInstance(text, str)
        self.assertGreater(len(text), 0)

    def test_fact_recall_precedes_interest_talk(self):
        """When both facts and interests exist, recall fires first (lower threshold wins)."""
        profile = self._FakeProfile(interests=["音楽"], facts={"dream": "宇宙"})
        tracker = self._FakeTracker("friendly")
        with mock.patch.object(autonomous_behavior, "get_persona",
                               lambda *a, **k: self._FakePersona()), \
             mock.patch.object(autonomous_behavior, "_get_mood_tracker",
                               lambda: tracker), \
             mock.patch.object(autonomous_behavior, "_get_user_profile",
                               lambda: profile), \
             mock.patch.object(autonomous_behavior, "_get_daily_mood", None), \
             mock.patch.object(autonomous_behavior, "_recall_fact",
                               lambda *a, **kw: "RECALLED_DREAM"), \
             mock.patch("autonomous_behavior.random.random", return_value=0.0):
            d = _Dummy()
            text = d._pick_talk_text()
        self.assertEqual(text, "RECALLED_DREAM")

    def test_fact_recall_en_lang_passed(self):
        """English persona causes English lang to be passed to recall_fact."""
        class _EnPersona(self._FakePersona):
            lang = "en"

        received_lang = []

        def _recall_capture(prof, lang="ja"):
            received_lang.append(lang)
            return "RECALLED_EN"

        profile = self._FakeProfile(facts={"favorite_color": "blue"})
        tracker = self._FakeTracker("close")
        with mock.patch.object(autonomous_behavior, "get_persona",
                               lambda *a, **k: _EnPersona()), \
             mock.patch.object(autonomous_behavior, "_get_mood_tracker",
                               lambda: tracker), \
             mock.patch.object(autonomous_behavior, "_get_user_profile",
                               lambda: profile), \
             mock.patch.object(autonomous_behavior, "_get_daily_mood", None), \
             mock.patch.object(autonomous_behavior, "_recall_fact", _recall_capture), \
             mock.patch("autonomous_behavior.random.random", return_value=0.0):
            d = _Dummy()
            text = d._pick_talk_text()
        self.assertEqual(text, "RECALLED_EN")
        self.assertEqual(received_lang, ["en"])


class SummaryGreetingTests(unittest.TestCase):
    """summary_greeting() is appended to startup greeting during afternoon hours (12-22h)."""

    def _fake_persona(self):
        class _FP:
            lang = "ja"
            def greeting(self, *a, **kw): return "GREETING"
            def talk(self, *a, **kw): return "TALK"
            def rest(self, *a, **kw): return "REST"
        return _FP()

    def test_summary_greeting_appended_at_afternoon(self):
        """summary_greeting() is called and appended during 12-22h."""
        captured = []

        class _GDummy(_StartStopDummy):
            def _on_talk_start(self, text):
                captured.append(text)

        class _FakeDatetime:
            @staticmethod
            def now():
                class _T:
                    hour = 15
                return _T()

        with mock.patch.object(autonomous_behavior, "get_persona",
                               lambda *a, **k: self._fake_persona()), \
             mock.patch.object(autonomous_behavior, "_get_mood_tracker", None), \
             mock.patch.object(autonomous_behavior, "_yesterday_greeting", lambda **kw: ""), \
             mock.patch.object(autonomous_behavior, "_summary_greeting", lambda **kw: "SUMMARY_TODAY"), \
             mock.patch.object(autonomous_behavior, "_seasonal_greeting", lambda **kw: ""), \
             mock.patch.object(autonomous_behavior, "_birthday_greeting", lambda *a, **kw: ""), \
             mock.patch.object(autonomous_behavior, "_get_daily_mood", lambda **kw: "calm"), \
             mock.patch.object(autonomous_behavior, "_mood_description", lambda *a, **kw: ""), \
             mock.patch("datetime.datetime", _FakeDatetime):
            d = _GDummy()
            d.start_autonomous()

        self.assertTrue(any("SUMMARY_TODAY" in t for t in captured))

    def test_summary_greeting_not_appended_in_morning(self):
        """summary_greeting() is NOT called during 0-12h (morning/night)."""
        captured = []

        class _GDummy(_StartStopDummy):
            def _on_talk_start(self, text):
                captured.append(text)

        class _FakeDatetime:
            @staticmethod
            def now():
                class _T:
                    hour = 8
                return _T()

        with mock.patch.object(autonomous_behavior, "get_persona",
                               lambda *a, **k: self._fake_persona()), \
             mock.patch.object(autonomous_behavior, "_get_mood_tracker", None), \
             mock.patch.object(autonomous_behavior, "_yesterday_greeting", lambda **kw: ""), \
             mock.patch.object(autonomous_behavior, "_summary_greeting", lambda **kw: "SUMMARY_TODAY"), \
             mock.patch.object(autonomous_behavior, "_seasonal_greeting", lambda **kw: ""), \
             mock.patch.object(autonomous_behavior, "_birthday_greeting", lambda *a, **kw: ""), \
             mock.patch.object(autonomous_behavior, "_get_daily_mood", lambda **kw: "calm"), \
             mock.patch.object(autonomous_behavior, "_mood_description", lambda *a, **kw: ""), \
             mock.patch("datetime.datetime", _FakeDatetime):
            d = _GDummy()
            d.start_autonomous()

        self.assertFalse(any("SUMMARY_TODAY" in t for t in captured))

    def test_summary_greeting_failure_does_not_break_start(self):
        """If summary_greeting raises, start_autonomous still completes."""
        def _boom(**kw):
            raise RuntimeError("summary boom")

        with mock.patch.object(autonomous_behavior, "get_persona",
                               lambda *a, **k: self._fake_persona()), \
             mock.patch.object(autonomous_behavior, "_get_mood_tracker", None), \
             mock.patch.object(autonomous_behavior, "_yesterday_greeting", lambda **kw: ""), \
             mock.patch.object(autonomous_behavior, "_summary_greeting", _boom), \
             mock.patch.object(autonomous_behavior, "_seasonal_greeting", lambda **kw: ""), \
             mock.patch.object(autonomous_behavior, "_birthday_greeting", lambda *a, **kw: ""), \
             mock.patch.object(autonomous_behavior, "_get_daily_mood", lambda **kw: "calm"), \
             mock.patch.object(autonomous_behavior, "_mood_description", lambda *a, **kw: ""):
            d = _StartStopDummy()
            d.start_autonomous()  # must not raise

        self.assertTrue(d.is_autonomous)


class WellbeingGreetingTests(unittest.TestCase):
    """start_autonomous appends a wellbeing check-in when the user's mood trend is
    clear (low or high), and stays silent when trend is neutral."""

    def _fake_persona(self):
        class _FP:
            lang = "ja"
            def greeting(self, *a, **kw): return "GREETING"
            def talk(self, *a, **kw): return "TALK"
            def rest(self, *a, **kw): return "REST"
        return _FP()

    def _greeting_dummy(self, captured):
        class _GDummy(_StartStopDummy):
            def _on_talk_start(self, text):
                captured.append(text)
        return _GDummy()

    def _common_patches(self):
        """Context-manager patches shared by all tests in this class."""
        return [
            mock.patch.object(autonomous_behavior, "get_persona",
                              lambda *a, **k: self._fake_persona()),
            mock.patch.object(autonomous_behavior, "_get_mood_tracker", None),
            mock.patch.object(autonomous_behavior, "_yesterday_greeting", lambda **kw: ""),
            mock.patch.object(autonomous_behavior, "_summary_greeting", lambda **kw: ""),
            mock.patch.object(autonomous_behavior, "_seasonal_greeting", lambda **kw: ""),
            mock.patch.object(autonomous_behavior, "_birthday_greeting", lambda *a, **kw: ""),
            mock.patch.object(autonomous_behavior, "_get_daily_mood", None),
            mock.patch.object(autonomous_behavior, "_mood_description", lambda *a, **kw: ""),
            # Suppress the usage guardrail by default so these tests isolate
            # the wellbeing-reflection append; a test that wants it can
            # re-patch _usage_reflection.
            mock.patch.object(autonomous_behavior, "_usage_reflection", lambda *a, **kw: ""),
        ]

    def test_low_trend_appended_to_greeting(self):
        """When wellbeing_reflection returns a message (low trend), it is appended."""
        captured = []
        patches = self._common_patches() + [
            mock.patch.object(autonomous_behavior, "_wellbeing_reflection",
                              lambda *a, **kw: "無理しないでね。"),
        ]
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            d = self._greeting_dummy(captured)
            d.start_autonomous()

        self.assertEqual(len(captured), 1)
        self.assertIn("GREETING", captured[0])
        self.assertIn("無理しないでね。", captured[0])

    def test_high_trend_appended_to_greeting(self):
        """When wellbeing_reflection returns a positive message, it is appended."""
        captured = []
        patches = self._common_patches() + [
            mock.patch.object(autonomous_behavior, "_wellbeing_reflection",
                              lambda *a, **kw: "最近すごく楽しそう！"),
        ]
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            d = self._greeting_dummy(captured)
            d.start_autonomous()

        self.assertIn("最近すごく楽しそう！", captured[0])

    def test_neutral_trend_not_appended(self):
        """When wellbeing_reflection returns '' (neutral), greeting is unchanged."""
        captured = []
        patches = self._common_patches() + [
            mock.patch.object(autonomous_behavior, "_wellbeing_reflection",
                              lambda *a, **kw: ""),
        ]
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            d = self._greeting_dummy(captured)
            d.start_autonomous()

        self.assertEqual(captured, ["GREETING"])

    def test_wellbeing_reflection_none_does_not_crash(self):
        """If _wellbeing_reflection is None (import failed), start still completes."""
        patches = self._common_patches() + [
            mock.patch.object(autonomous_behavior, "_wellbeing_reflection", None),
        ]
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            d = _StartStopDummy()
            d.start_autonomous()

        self.assertTrue(d.is_autonomous)
        self.assertIn("GREETING", d.talk_text)

    def test_wellbeing_reflection_exception_does_not_crash(self):
        """If _wellbeing_reflection raises, start_autonomous still completes."""
        def _boom(*a, **kw):
            raise RuntimeError("wellbeing boom")

        patches = self._common_patches() + [
            mock.patch.object(autonomous_behavior, "_wellbeing_reflection", _boom),
        ]
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            d = _StartStopDummy()
            d.start_autonomous()

        self.assertTrue(d.is_autonomous)


class UsageGuardrailGreetingTests(unittest.TestCase):
    """The emotional-dependence usage guardrail (usage_guardrails) appends a
    gentle nudge to the greeting when a concern is detected, but at most once
    per day (cooldown), and never crashes the greeting path."""

    def _fake_persona(self):
        return _FakePersona()

    def _greeting_dummy(self, captured):
        class _GDummy(_StartStopDummy):
            def _on_talk_start(self, text):
                captured.append(text)
        return _GDummy()

    def _base_patches(self):
        # Suppress every OTHER appended source so we isolate the usage nudge,
        # and force wellbeing to "" so only the guardrail can append.
        return [
            mock.patch.object(autonomous_behavior, "get_persona",
                              lambda *a, **k: self._fake_persona()),
            mock.patch.object(autonomous_behavior, "_get_mood_tracker", None),
            mock.patch.object(autonomous_behavior, "_yesterday_greeting", lambda **kw: ""),
            mock.patch.object(autonomous_behavior, "_summary_greeting", lambda **kw: ""),
            mock.patch.object(autonomous_behavior, "_seasonal_greeting", lambda **kw: ""),
            mock.patch.object(autonomous_behavior, "_birthday_greeting", lambda *a, **kw: ""),
            mock.patch.object(autonomous_behavior, "_get_daily_mood", None),
            mock.patch.object(autonomous_behavior, "_mood_description", lambda *a, **kw: ""),
            mock.patch.object(autonomous_behavior, "_wellbeing_reflection", lambda *a, **kw: ""),
        ]

    def test_nudge_appended_when_concern_detected(self):
        captured = []
        patches = self._base_patches() + [
            mock.patch.object(autonomous_behavior, "_usage_reflection",
                              lambda *a, **kw: "そろそろ休んでね。"),
        ]
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            d = self._greeting_dummy(captured)
            d.start_autonomous()

        self.assertEqual(len(captured), 1)
        self.assertIn("そろそろ休んでね。", captured[0])

    def test_nudge_not_appended_when_silent(self):
        captured = []
        patches = self._base_patches() + [
            mock.patch.object(autonomous_behavior, "_usage_reflection", lambda *a, **kw: ""),
        ]
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            d = self._greeting_dummy(captured)
            d.start_autonomous()

        self.assertEqual(captured, ["GREETING"])

    def test_nudge_fires_at_most_once_per_day(self):
        """Second greeting on the same day must NOT repeat the nudge (cooldown)."""
        call_count = {"n": 0}

        def _always_nudge(*a, **kw):
            call_count["n"] += 1
            return "そろそろ休んでね。"

        captured = []
        patches = self._base_patches() + [
            mock.patch.object(autonomous_behavior, "_usage_reflection", _always_nudge),
        ]
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            d = self._greeting_dummy(captured)
            d.start_autonomous()   # first greeting: nudge fires
            d.start_autonomous()   # same day: cooldown suppresses it

        nudged = [c for c in captured if "そろそろ休んでね。" in c]
        self.assertEqual(len(nudged), 1,
                         "usage nudge must appear at most once per calendar day")

    def test_guardrail_exception_does_not_crash(self):
        def _boom(*a, **kw):
            raise RuntimeError("guardrail boom")

        patches = self._base_patches() + [
            mock.patch.object(autonomous_behavior, "_usage_reflection", _boom),
        ]
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            d = _StartStopDummy()
            d.start_autonomous()

        self.assertTrue(d.is_autonomous)
        self.assertIn("GREETING", d.talk_text)


if __name__ == "__main__":
    unittest.main()
