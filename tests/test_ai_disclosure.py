"""
Tests for main/ai_disclosure.py — "you are talking to an AI" disclosure.

Satin's affinity system, confession event and 「大好きだよ」 lines are exactly the
kind of simulated emotional relationship that the 2025-26 companion-chatbot
statutes target, and the product previously disclosed its nature nowhere:

- New York's AI Companion Models Law (in force 2025-11-05) requires a notice at
  the start of each session and at least every three hours of continuing
  interaction, saying the AI is a computer program that cannot feel as a human.
- California SB 243 (in force 2026-01-01) requires a clear and conspicuous
  notice when a reasonable person could be misled, plus a three-hour reminder
  for users known to be minors.

Satin never asks for an age (privacy first), so it cannot know whether a user
is a minor — the three-hour reminder therefore applies to everyone and has no
off switch. These tests pin that behaviour down at the module level and at both
call sites (3D GUI and headless CLI).

Stdlib-only; no GUI/network. Run: python -m unittest tests.test_ai_disclosure -v
"""
import os
import queue
import sys
import tempfile
import unittest
from unittest import mock

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import ai_disclosure as ad  # noqa: E402
import avatar_3d_autonomous_tts as _gui  # noqa: E402
import persona as _persona_mod  # noqa: E402
import persona_cli  # noqa: E402
import mood as _mood_mod  # noqa: E402
import user_profile as _profile_mod  # noqa: E402
from conversation_log import ConversationLog  # noqa: E402
from persona import Persona  # noqa: E402

_THREE_HOURS = 3 * 60 * 60


class TestNotices(unittest.TestCase):
    def test_interval_is_three_hours(self):
        self.assertEqual(ad.DISCLOSURE_INTERVAL_SECONDS, _THREE_HOURS)

    def test_session_notice_says_ai_and_not_human(self):
        ja = ad.session_notice("ja")
        self.assertIn("AI", ja)
        self.assertIn("人間ではありません", ja)
        en = ad.session_notice("en")
        self.assertIn("AI", en)
        self.assertIn("not a human", en)

    def test_session_notice_denies_having_real_feelings(self):
        """NY's wording: a computer program that cannot feel as a human does."""
        self.assertIn("感情", ad.session_notice("ja"))
        self.assertIn("feelings", ad.session_notice("en"))

    def test_periodic_notice_says_ai_and_not_human(self):
        for lang in ("ja", "en"):
            notice = ad.periodic_notice(lang)
            self.assertIn("AI", notice)
        self.assertIn("人間ではありません", ad.periodic_notice("ja"))
        self.assertIn("not a human", ad.periodic_notice("en"))

    def test_notices_are_short(self):
        """A notice nobody reads is not conspicuous. Keep it to one line."""
        for fn in (ad.session_notice, ad.periodic_notice):
            for lang in ("ja", "en"):
                self.assertEqual(len(fn(lang).splitlines()), 1, (fn, lang))

    def test_unknown_language_falls_back_to_english(self):
        self.assertEqual(ad.session_notice("fr"), ad.session_notice("en"))
        self.assertEqual(ad.periodic_notice(None), ad.periodic_notice("en"))

    def test_en_variants_resolve_to_english(self):
        self.assertEqual(ad.session_notice("en-US"), ad.session_notice("en"))
        self.assertEqual(ad.session_notice("ja-JP"), ad.session_notice("ja"))


class TestIsDue(unittest.TestCase):
    def test_never_shown_is_due(self):
        self.assertTrue(ad.is_due(None))

    def test_just_shown_is_not_due(self):
        now = 1_000_000.0
        self.assertFalse(ad.is_due(now, now=now))

    def test_two_hours_is_not_due(self):
        now = 1_000_000.0
        self.assertFalse(ad.is_due(now - 2 * 60 * 60, now=now))

    def test_exactly_three_hours_is_due(self):
        now = 1_000_000.0
        self.assertTrue(ad.is_due(now - _THREE_HOURS, now=now))

    def test_beyond_three_hours_is_due(self):
        now = 1_000_000.0
        self.assertTrue(ad.is_due(now - _THREE_HOURS - 1, now=now))

    def test_clock_going_backwards_errs_towards_disclosing(self):
        """NTP correction or suspend/resume can move the clock back. Showing
        the notice too often is safe; skipping it is not."""
        now = 1_000_000.0
        self.assertTrue(ad.is_due(now + 60, now=now))

    def test_next_due_at(self):
        self.assertEqual(ad.next_due_at(None), 0.0)
        self.assertEqual(ad.next_due_at(100.0), 100.0 + _THREE_HOURS)


_PERSONA = Persona.from_dict({
    "name": "Mimi",
    "default_lang": "ja",
    "responses": {"ja": {
        "rules": [{"keywords": ["こんにちは"], "replies": ["やあ！"]}],
        "fallback": ["なるほど。"],
    }},
}, lang="ja")


class TestGuiWiring(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.log = ConversationLog(os.path.join(self._tmp, "c.jsonl"))
        self._patchers = [
            mock.patch.object(_gui, "get_conversation_log", lambda: self.log),
            mock.patch.object(_gui, "get_mood_tracker", None),
            mock.patch.object(_gui, "_get_user_profile_gui", lambda: None),
            mock.patch.object(_gui.AutonomousBehaviorMixin, "persona",
                              property(lambda s: _PERSONA)),
        ]
        for p in self._patchers:
            p.start()

    def tearDown(self):
        for p in self._patchers:
            p.stop()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)
        _persona_mod.reset_persona()
        _mood_mod.reset_mood_tracker()
        _profile_mod.reset_user_profile()

    def _viewer(self):
        v = object.__new__(_gui.AutonomousAvatarViewer)
        v.comment_text = ""
        v.talk_text = ""
        v.mode = "idle"
        v.ticks = 0
        v.tts_queue = queue.Queue()
        v.pending_fact_key = None
        return v

    def test_session_start_shows_the_notice(self):
        w = object.__new__(_gui.MainWindow)
        w._lang = "ja"
        w.viewer = self._viewer()
        self.assertTrue(w._show_ai_disclosure())
        self.assertIn("人間ではありません", w.viewer.comment_text)

    def test_session_start_stamps_the_clock(self):
        """So the very next message does not repeat the notice."""
        w = object.__new__(_gui.MainWindow)
        w._lang = "ja"
        w.viewer = self._viewer()
        w._show_ai_disclosure()
        self.assertIsNotNone(w.viewer._last_ai_disclosure_ts)
        w.viewer.speak_comment("こんにちは")
        self.assertEqual(w.viewer.comment_text, "やあ！")

    def test_first_message_without_a_session_stamp_starts_the_clock_quietly(self):
        """speak_comment owns the interval, not the session-start notice —
        an unstamped viewer means the session just began."""
        v = self._viewer()
        v.speak_comment("こんにちは")
        self.assertEqual(v.comment_text, "やあ！")
        self.assertIsNotNone(v._last_ai_disclosure_ts)

    def test_reminder_after_three_hours(self):
        v = self._viewer()
        v._last_ai_disclosure_ts = 1.0  # long past
        v.speak_comment("こんにちは")
        self.assertIn(ad.periodic_notice("ja"), v.comment_text)
        self.assertIn("やあ！", v.comment_text)

    def test_reminder_not_repeated_within_the_interval(self):
        v = self._viewer()
        v._last_ai_disclosure_ts = 1.0
        v.speak_comment("こんにちは")
        v.comment_text = ""
        v.speak_comment("こんにちは")
        self.assertNotIn(ad.periodic_notice("ja"), v.comment_text)

    def test_help_command_states_it_is_an_ai(self):
        v = self._viewer()
        v._cmd_help_gui("ja")
        self.assertIn("人間ではありません", v.comment_text)


class _Driver:
    def __init__(self, inputs):
        self._inputs = list(inputs)
        self.out = []

    def input_fn(self, prompt=""):
        if not self._inputs:
            raise EOFError
        return self._inputs.pop(0)

    def output_fn(self, text):
        self.out.append(text)


class TestCliWiring(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.log = ConversationLog(os.path.join(self._tmp, "c.jsonl"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)
        _persona_mod.reset_persona()
        _mood_mod.reset_mood_tracker()
        _profile_mod.reset_user_profile()

    def _run(self, inputs, **kw):
        d = _Driver(inputs)
        persona_cli.run_chat(
            persona=_PERSONA, conv_log=self.log,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=False, **kw,
        )
        return d.out

    def test_session_start_shows_the_notice(self):
        out = self._run([])
        self.assertTrue(any("人間ではありません" in line for line in out), out)

    def test_notice_shown_even_with_greeting_enabled(self):
        d = _Driver([])
        persona_cli.run_chat(
            persona=_PERSONA, conv_log=self.log,
            input_fn=d.input_fn, output_fn=d.output_fn, greet=True,
        )
        self.assertTrue(any("人間ではありません" in line for line in d.out), d.out)

    def test_notice_not_repeated_on_every_turn(self):
        out = self._run(["こんにちは", "こんにちは", "こんにちは"])
        hits = [line for line in out if ad.periodic_notice("ja") in line]
        self.assertEqual(hits, [], out)

    def test_reminder_after_three_hours(self):
        """Freeze the clock forward past the interval on the second turn."""
        real_time = persona_cli._time.time
        calls = {"n": 0}

        def fake_time():
            calls["n"] += 1
            # first call stamps the session; later calls are 4 hours ahead
            return real_time() + (0 if calls["n"] == 1 else 4 * 60 * 60)

        with mock.patch.object(persona_cli._time, "time", fake_time):
            out = self._run(["こんにちは"])
        self.assertTrue(any(ad.periodic_notice("ja") in line for line in out), out)

    def test_help_text_states_it_is_an_ai(self):
        self.assertIn("人間ではありません", persona_cli._help_text("ja"))
        self.assertIn("not a human", persona_cli._help_text("en"))

    def test_help_text_can_omit_the_disclosure_tail(self):
        """起動時は法定開示が直後に続くので、/help 側の常設タグは外せること。"""
        self.assertNotIn("人間ではありません",
                         persona_cli._help_text("ja", with_disclosure=False))
        self.assertNotIn("not a human",
                         persona_cli._help_text("en", with_disclosure=False))
        # 外したのは開示だけで、コマンド一覧そのものは残っていること
        self.assertIn("/quit", persona_cli._help_text("ja", with_disclosure=False))

    def test_session_start_prints_the_disclosure_exactly_once(self):
        """起動直後に同じ開示文が 2 回続かないこと。

        /help の常設タグと法定のセッション開始開示は別々の理由で存在するが、
        起動時は隣り合って出るため、両方そのまま出すと同じ文が 2 行続いて
        「表示バグ」に見える。読み飛ばされる開示は開示として機能しない。
        """
        out = self._run([])
        notice = ad.session_notice("ja")
        hits = [line for line in out if notice in line]
        self.assertEqual(len(hits), 1, f"開示が {len(hits)} 回出ています: {out}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
