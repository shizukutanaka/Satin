"""
Unit tests for autonomous_behavior.AutonomousBehaviorMixin — the run/rest/talk
state machine extracted from the three autonomous avatar viewers.

The mixin operates on plain attributes, so it is testable without Qt/numpy.
"""
import os
import sys
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

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


if __name__ == "__main__":
    unittest.main()
