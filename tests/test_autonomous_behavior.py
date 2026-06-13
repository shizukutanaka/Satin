"""
Unit tests for autonomous_behavior.AutonomousBehaviorMixin — the run/rest/talk
state machine extracted from the three autonomous avatar viewers.

The mixin operates on plain attributes, so it is testable without Qt/numpy.
"""
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

    def tearDown(self):
        self._patcher.stop()
        self._mood_patcher.stop()

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
                               lambda: _FakeTracker()):
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

    def test_mood_tracker_failure_does_not_break_start(self):
        """If the mood tracker raises, start_autonomous still completes safely."""
        def _boom():
            raise RuntimeError("db locked")

        with mock.patch.object(autonomous_behavior, "get_persona", None):
            with mock.patch.object(autonomous_behavior, "_get_mood_tracker", _boom):
                d = _StartStopDummy()
                d.start_autonomous()  # must not raise

        self.assertTrue(d.is_autonomous)


if __name__ == "__main__":
    unittest.main()
