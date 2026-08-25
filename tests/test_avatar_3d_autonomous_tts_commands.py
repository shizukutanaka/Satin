"""
Unit tests for the GUI slash commands added to AutonomousAvatarViewer:
/forget-fact, /export-log, /clear-log, /history, /search, /recap, /feeling.

Socratic-review finding: these commands existed in the headless CLI
(persona_cli.py) but were completely unreachable from the actual 3D avatar
GUI (avatar_3d_autonomous_tts.py) — the product's default interface. This
file verifies the GUI-side wiring added to close that gap.

Qt/OpenGL are absent in CI, so instances are built via object.__new__ to
bypass the QOpenGLWidget-dependent __init__, following the pattern already
used in tests/test_avatar_event_timeline_viewer.py and
tests/test_avatar_3d_autonomous_or_camera.py.
"""
import os
import sys
import unittest

from conftest import make_qt_stub  # noqa: E402
from unittest import mock

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import avatar_3d_autonomous_tts as _mod  # noqa: E402


def _fake_viewer(**overrides):
    v = make_qt_stub(_mod.AutonomousAvatarViewer)
    defaults = dict(
        tts_queue=None,
        comment_text="",
        mode="idle",
        ticks=0,
        pending_fact_key=None,
        _clear_log_pending=False,
    )
    defaults.update(overrides)
    for k, val in defaults.items():
        setattr(v, k, val)
    return v


class _FakeProfile:
    def __init__(self, facts=None):
        self.facts = dict(facts or {})
        self.saved_to = None

    def remove_fact(self, key):
        if key in self.facts:
            del self.facts[key]
            return True
        return False

    def save(self, path):
        self.saved_to = path
        return True


class _FakeConvLog:
    def __init__(self, logfile):
        self.logfile = logfile
        self.exchanges = []
        self._events = []  # raw event dicts for recent()/search()

    def log_exchange(self, user_text, reply):
        self.exchanges.append((user_text, reply))
        self._events.append({"event_type": "user_comment",
                             "details": {"text": user_text}, "timestamp": 0})
        self._events.append({"event_type": "avatar_reply",
                             "details": {"text": reply}, "timestamp": 0})

    def to_csv(self, avatar_label="Avatar", include_archives=True):
        lines = ["speaker,text"]
        for user_text, reply in self.exchanges:
            lines.append(f"You,{user_text}")
            lines.append(f"{avatar_label},{reply}")
        return "\n".join(lines) + "\n"

    def recent_texts(self, n=10):
        return [f"{ev['event_type']}: {ev['details']['text']}" for ev in self._events[-n:]]

    def recent(self, n=20):
        return list(self._events[-n:])

    def search(self, query, include_archives=True):
        return [ev for ev in self._events if query.lower() in ev["details"]["text"].lower()]

    def search_relevant(self, query, n=5, include_archives=True):
        # 部分一致より緩い「関連度」検索の代用: クエリのいずれかの語を含む
        # イベントを返す（実際の BM25 ランキングは本体側でテスト済み）。
        if not query or not query.strip():
            return []
        terms = query.lower().split()
        hits = [ev for ev in self._events
                if any(t in ev["details"]["text"].lower() for t in terms)]
        return hits[:n] if n and n > 0 else hits


class ForgetFactGuiTests(unittest.TestCase):
    """Regression: these tests didn't mock get_conversation_log (unlike every
    sibling GUI-command test class in this file), so _cmd_forget_fact_gui's
    trailing get_conversation_log().log_exchange(...) call hit the REAL
    process-wide singleton and wrote real "/forget-fact ..." conversation
    entries into the actual conversation_log.DEFAULT_LOGFILE file on every
    test run — polluting real user/app data with test fixtures."""

    def test_removes_matching_fact_by_partial_value(self):
        v = _fake_viewer()
        prof = _FakeProfile(facts={"hobby": "登山"})
        conv_log = _FakeConvLog("/tmp/c.jsonl")
        with mock.patch.object(_mod, "_get_user_profile_gui", return_value=prof), \
             mock.patch.object(_mod, "_default_profile_path_gui", return_value="/tmp/p.json"), \
             mock.patch.object(_mod, "get_conversation_log", return_value=conv_log):
            v._cmd_forget_fact_gui("登山", "ja")
        self.assertNotIn("hobby", prof.facts)
        self.assertIn("わかった", v.comment_text)

    def test_no_match_leaves_facts_untouched(self):
        v = _fake_viewer()
        prof = _FakeProfile(facts={"hobby": "登山"})
        conv_log = _FakeConvLog("/tmp/c.jsonl")
        with mock.patch.object(_mod, "_get_user_profile_gui", return_value=prof), \
             mock.patch.object(_mod, "_default_profile_path_gui", return_value="/tmp/p.json"), \
             mock.patch.object(_mod, "get_conversation_log", return_value=conv_log):
            v._cmd_forget_fact_gui("存在しない話", "ja")
        self.assertIn("hobby", prof.facts)
        self.assertIn("存在しない話", v.comment_text)

    def test_empty_arg_shows_usage_without_deleting(self):
        v = _fake_viewer()
        prof = _FakeProfile(facts={"hobby": "登山"})
        conv_log = _FakeConvLog("/tmp/c.jsonl")
        with mock.patch.object(_mod, "_get_user_profile_gui", return_value=prof), \
             mock.patch.object(_mod, "get_conversation_log", return_value=conv_log):
            v._cmd_forget_fact_gui("", "ja")
        self.assertIn("hobby", prof.facts)
        self.assertIn("/forget-fact", v.comment_text)

    def test_english_reply(self):
        v = _fake_viewer()
        prof = _FakeProfile(facts={"food": "ramen and udon"})
        conv_log = _FakeConvLog("/tmp/c.jsonl")
        with mock.patch.object(_mod, "_get_user_profile_gui", return_value=prof), \
             mock.patch.object(_mod, "_default_profile_path_gui", return_value="/tmp/p.json"), \
             mock.patch.object(_mod, "get_conversation_log", return_value=conv_log):
            v._cmd_forget_fact_gui("udon", "en")
        self.assertNotIn("food", prof.facts)
        self.assertIn("forgotten", v.comment_text)


class ExportLogGuiTests(unittest.TestCase):
    def test_writes_csv_with_conversation_content(self):
        import tempfile
        tmp = tempfile.mkdtemp()
        dest = os.path.join(tmp, "out.csv")
        conv_log = _FakeConvLog(os.path.join(tmp, "c.jsonl"))
        conv_log.log_exchange("hello there", "hi friend")
        v = _fake_viewer()
        with mock.patch.object(_mod, "get_conversation_log", return_value=conv_log):
            v._cmd_export_log_gui(dest, "ja")
        self.assertTrue(os.path.exists(dest))
        with open(dest, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("hello there", content)
        self.assertIn(dest, v.comment_text)

    def test_default_path_used_when_empty(self):
        import tempfile, contextlib
        tmp = tempfile.mkdtemp()
        conv_log = _FakeConvLog(os.path.join(tmp, "c.jsonl"))
        v = _fake_viewer()
        cwd = os.getcwd()
        try:
            os.chdir(tmp)
            with mock.patch.object(_mod, "get_conversation_log", return_value=conv_log):
                v._cmd_export_log_gui("", "ja")
            self.assertTrue(os.path.exists(os.path.join(tmp, "conversation_export.csv")))
        finally:
            with contextlib.suppress(OSError):
                os.chdir(cwd)

    def test_no_conversation_log_does_not_crash(self):
        v = _fake_viewer()
        with mock.patch.object(_mod, "get_conversation_log", None):
            v._cmd_export_log_gui("x.csv", "ja")
        self.assertIn("利用できません", v.comment_text)


class ClearLogGuiTests(unittest.TestCase):
    def test_first_call_only_asks_confirmation(self):
        import tempfile
        tmp = tempfile.mkdtemp()
        logpath = os.path.join(tmp, "c.jsonl")
        with open(logpath, "w", encoding="utf-8") as f:
            f.write('{"a":1}\n')
        conv_log = _FakeConvLog(logpath)
        v = _fake_viewer()
        with mock.patch.object(_mod, "get_conversation_log", return_value=conv_log):
            v._cmd_clear_log_gui("ja")
        self.assertTrue(v._clear_log_pending)
        self.assertGreater(os.path.getsize(logpath), 0)
        self.assertIn("/clear-log", v.comment_text)

    def test_second_call_clears_the_log(self):
        import tempfile
        tmp = tempfile.mkdtemp()
        logpath = os.path.join(tmp, "c.jsonl")
        with open(logpath, "w", encoding="utf-8") as f:
            f.write('{"a":1}\n')
        conv_log = _FakeConvLog(logpath)
        v = _fake_viewer()
        with mock.patch.object(_mod, "get_conversation_log", return_value=conv_log):
            v._cmd_clear_log_gui("ja")   # ask
            v._cmd_clear_log_gui("ja")   # confirm
        self.assertFalse(v._clear_log_pending)
        self.assertEqual(os.path.getsize(logpath), 0)

    def test_speak_comment_resets_pending_on_other_slash_command(self):
        """A different slash command in between must cancel the pending confirm."""
        import tempfile
        tmp = tempfile.mkdtemp()
        logpath = os.path.join(tmp, "c.jsonl")
        with open(logpath, "w", encoding="utf-8") as f:
            f.write('{"a":1}\n')
        conv_log = _FakeConvLog(logpath)
        v = _fake_viewer()
        with mock.patch.object(_mod, "get_conversation_log", return_value=conv_log), \
             mock.patch.object(_mod, "get_mood_tracker", None):
            v.speak_comment("/clear-log")
            self.assertTrue(v._clear_log_pending)
            v.speak_comment("/help")
            self.assertFalse(v._clear_log_pending,
                             "A different slash command must cancel the pending confirm.")
            v.speak_comment("/clear-log")  # this is now a fresh ask, not a confirm
        self.assertGreater(os.path.getsize(logpath), 0,
                           "Log must survive: the second /clear-log was a fresh ask.")

    def test_speak_comment_resets_pending_on_plain_text(self):
        """Non-slash text in between must also cancel the pending confirm."""
        import tempfile
        tmp = tempfile.mkdtemp()
        logpath = os.path.join(tmp, "c.jsonl")
        with open(logpath, "w", encoding="utf-8") as f:
            f.write('{"a":1}\n')
        conv_log = _FakeConvLog(logpath)
        v = _fake_viewer()
        with mock.patch.object(_mod, "get_conversation_log", return_value=conv_log), \
             mock.patch.object(_mod, "get_mood_tracker", None):
            v.speak_comment("/clear-log")
            self.assertTrue(v._clear_log_pending)
            v.speak_comment("just chatting")
            self.assertFalse(v._clear_log_pending)

    def test_no_conversation_log_does_not_crash(self):
        v = _fake_viewer(_clear_log_pending=True)
        with mock.patch.object(_mod, "get_conversation_log", None):
            v._cmd_clear_log_gui("ja")
        self.assertIn("利用できません", v.comment_text)


class HelpGuiTests(unittest.TestCase):
    def test_help_lists_new_commands_ja(self):
        v = _fake_viewer()
        v._cmd_help_gui("ja")
        for cmd in ("/forget-fact", "/export-log", "/clear-log"):
            self.assertIn(cmd, v.comment_text)

    def test_help_lists_new_commands_en(self):
        v = _fake_viewer()
        v._cmd_help_gui("en")
        for cmd in ("/forget-fact", "/export-log", "/clear-log"):
            self.assertIn(cmd, v.comment_text)


class DispatchTests(unittest.TestCase):
    """Confirm the new commands are actually reachable through the dispatcher,
    not just directly callable — this is the crux of the original gap."""

    def test_forget_fact_dispatches(self):
        v = _fake_viewer()
        prof = _FakeProfile(facts={"hobby": "登山"})
        with mock.patch.object(_mod, "_get_user_profile_gui", return_value=prof), \
             mock.patch.object(_mod, "_default_profile_path_gui", return_value="/tmp/p.json"), \
             mock.patch.object(_mod, "get_conversation_log", return_value=_FakeConvLog("/tmp/c.jsonl")):
            handled = v._handle_slash_command_gui("forget-fact 登山", "ja", None)
        self.assertTrue(handled)
        self.assertNotIn("hobby", prof.facts)

    def test_export_log_dispatches(self):
        import tempfile
        tmp = tempfile.mkdtemp()
        dest = os.path.join(tmp, "out.csv")
        conv_log = _FakeConvLog(os.path.join(tmp, "c.jsonl"))
        v = _fake_viewer()
        with mock.patch.object(_mod, "get_conversation_log", return_value=conv_log):
            handled = v._handle_slash_command_gui(f"export-log {dest}", "ja", None)
        self.assertTrue(handled)
        self.assertTrue(os.path.exists(dest))

    def test_clear_log_dispatches(self):
        v = _fake_viewer()
        with mock.patch.object(_mod, "get_conversation_log", return_value=_FakeConvLog("/tmp/x.jsonl")):
            handled = v._handle_slash_command_gui("clear-log", "ja", None)
        self.assertTrue(handled)
        self.assertTrue(v._clear_log_pending)

    def test_forget_fact_not_swallowed_by_forget_prefix(self):
        """/forget-fact must dispatch to its own handler, not /forget."""
        v = _fake_viewer()
        prof = _FakeProfile(facts={"hobby": "登山"})
        with mock.patch.object(_mod, "_get_user_profile_gui", return_value=prof), \
             mock.patch.object(_mod, "_default_profile_path_gui", return_value="/tmp/p.json"), \
             mock.patch.object(_mod, "get_conversation_log", return_value=_FakeConvLog("/tmp/c.jsonl")):
            v._handle_slash_command_gui("forget-fact 登山", "ja", None)
        # If /forget (interests) had swallowed this, facts would be untouched
        # and the reply would talk about a missing interest instead.
        self.assertNotIn("hobby", prof.facts)


class HistoryGuiTests(unittest.TestCase):
    def test_shows_recent_exchanges(self):
        v = _fake_viewer()
        conv_log = _FakeConvLog("/tmp/c.jsonl")
        conv_log.log_exchange("hello", "hi there")
        with mock.patch.object(_mod, "get_conversation_log", return_value=conv_log):
            v._cmd_history_gui("ja")
        self.assertIn("hello", v.comment_text)

    def test_no_conv_log_does_not_crash(self):
        v = _fake_viewer()
        with mock.patch.object(_mod, "get_conversation_log", None):
            v._cmd_history_gui("ja")
        self.assertIn("利用できません", v.comment_text)

    def test_empty_history_shows_message(self):
        v = _fake_viewer()
        conv_log = _FakeConvLog("/tmp/c.jsonl")
        with mock.patch.object(_mod, "get_conversation_log", return_value=conv_log):
            v._cmd_history_gui("ja")
        self.assertIn("ありません", v.comment_text)


class SearchGuiTests(unittest.TestCase):
    def test_finds_matching_exchange(self):
        v = _fake_viewer()
        conv_log = _FakeConvLog("/tmp/c.jsonl")
        conv_log.log_exchange("I like ramen", "Ramen is great!")
        conv_log.log_exchange("unrelated", "ok")
        with mock.patch.object(_mod, "get_conversation_log", return_value=conv_log):
            v._cmd_search_gui("ramen", "ja")
        self.assertIn("ramen", v.comment_text.lower())

    def test_no_match_shows_message(self):
        v = _fake_viewer()
        conv_log = _FakeConvLog("/tmp/c.jsonl")
        conv_log.log_exchange("hello", "hi")
        with mock.patch.object(_mod, "get_conversation_log", return_value=conv_log):
            v._cmd_search_gui("xyzzy", "ja")
        self.assertIn("見つかりませんでした", v.comment_text)

    def test_substring_miss_falls_back_to_relevant(self):
        """完全一致が無くても、関連度検索で近い会話を提示する（研究 A4）。"""
        v = _fake_viewer()
        conv_log = _FakeConvLog("/tmp/c.jsonl")
        conv_log.log_exchange("旅行が楽しかった", "よかったね")
        # 「楽しかった旅行」は部分一致しないが、語 "旅行"/"楽しかった" で関連あり
        with mock.patch.object(_mod, "get_conversation_log", return_value=conv_log):
            v._cmd_search_gui("楽しかった 旅行", "ja")
        self.assertIn("近い会話", v.comment_text)
        self.assertIn("旅行が楽しかった", v.comment_text)

    def test_relevant_fallback_english(self):
        v = _fake_viewer()
        conv_log = _FakeConvLog("/tmp/c.jsonl")
        conv_log.log_exchange("machine learning is fun", "indeed")
        with mock.patch.object(_mod, "get_conversation_log", return_value=conv_log):
            v._cmd_search_gui("learning machine", "en")
        self.assertIn("related", v.comment_text.lower())

    def test_no_match_and_no_related_shows_not_found(self):
        v = _fake_viewer()
        conv_log = _FakeConvLog("/tmp/c.jsonl")
        conv_log.log_exchange("hello", "hi")
        with mock.patch.object(_mod, "get_conversation_log", return_value=conv_log):
            v._cmd_search_gui("quantum", "ja")
        self.assertIn("見つかりませんでした", v.comment_text)

    def test_empty_query_shows_usage(self):
        v = _fake_viewer()
        conv_log = _FakeConvLog("/tmp/c.jsonl")
        with mock.patch.object(_mod, "get_conversation_log", return_value=conv_log):
            v._cmd_search_gui("", "ja")
        self.assertIn("/search", v.comment_text)

    def test_no_conv_log_does_not_crash(self):
        v = _fake_viewer()
        with mock.patch.object(_mod, "get_conversation_log", None):
            v._cmd_search_gui("anything", "ja")
        self.assertIn("利用できません", v.comment_text)


class RecapGuiTests(unittest.TestCase):
    def test_shows_greeting_and_recent_exchanges(self):
        v = _fake_viewer()
        conv_log = _FakeConvLog("/tmp/c.jsonl")
        conv_log.log_exchange("hello", "hi there")
        with mock.patch.object(_mod, "get_conversation_log", return_value=conv_log), \
             mock.patch.object(_mod, "_summary_greeting_gui", return_value="Good to see you!"):
            v._cmd_recap_gui("ja")
        self.assertIn("Good to see you!", v.comment_text)
        self.assertIn("hello", v.comment_text)

    def test_nothing_available_shows_fallback_message(self):
        v = _fake_viewer()
        with mock.patch.object(_mod, "get_conversation_log", None), \
             mock.patch.object(_mod, "_summary_greeting_gui", None):
            v._cmd_recap_gui("ja")
        self.assertIn("まだ会話が記録されていません", v.comment_text)


class FeelingGuiTests(unittest.TestCase):
    def test_unavailable_when_wellbeing_module_missing(self):
        v = _fake_viewer()
        with mock.patch.object(_mod, "_wellbeing_summary_gui", None), \
             mock.patch.object(_mod, "_wellbeing_message_gui", None):
            v._cmd_feeling_gui("ja")
        self.assertIn("利用できません", v.comment_text)

    def test_uses_wellbeing_message_when_available(self):
        v = _fake_viewer()
        with mock.patch.object(_mod, "_wellbeing_summary_gui", return_value={"sample_size": 5}), \
             mock.patch.object(_mod, "_wellbeing_message_gui", return_value="Take it easy today."):
            v._cmd_feeling_gui("en")
        self.assertEqual(v.comment_text, "Take it easy today.")

    def test_low_sample_size_shows_neutral_message(self):
        v = _fake_viewer()
        with mock.patch.object(_mod, "_wellbeing_summary_gui", return_value={"sample_size": 1}), \
             mock.patch.object(_mod, "_wellbeing_message_gui", return_value=""):
            v._cmd_feeling_gui("ja")
        self.assertIn("もう少し", v.comment_text)


class NewCommandDispatchTests(unittest.TestCase):
    """Confirm /history, /search, /recap, /feeling are reachable through the
    dispatcher (the crux of the original gap), not just directly callable."""

    def test_history_dispatches(self):
        v = _fake_viewer()
        with mock.patch.object(_mod, "get_conversation_log", return_value=_FakeConvLog("/tmp/c.jsonl")):
            self.assertTrue(v._handle_slash_command_gui("history", "ja", None))

    def test_search_dispatches(self):
        v = _fake_viewer()
        with mock.patch.object(_mod, "get_conversation_log", return_value=_FakeConvLog("/tmp/c.jsonl")):
            self.assertTrue(v._handle_slash_command_gui("search ramen", "ja", None))

    def test_recap_dispatches(self):
        v = _fake_viewer()
        with mock.patch.object(_mod, "get_conversation_log", None), \
             mock.patch.object(_mod, "_summary_greeting_gui", None):
            self.assertTrue(v._handle_slash_command_gui("recap", "ja", None))

    def test_feeling_and_checkin_alias_dispatch(self):
        v = _fake_viewer()
        with mock.patch.object(_mod, "_wellbeing_summary_gui", None), \
             mock.patch.object(_mod, "_wellbeing_message_gui", None):
            self.assertTrue(v._handle_slash_command_gui("feeling", "ja", None))
            self.assertTrue(v._handle_slash_command_gui("checkin", "ja", None))

    def test_avatar_dispatches(self):
        v = _fake_viewer(avatar_model_vertices=None, avatar_model_path=None)
        with mock.patch.object(_mod, "_avatar_model_store", None):
            self.assertTrue(v._handle_slash_command_gui("avatar", "ja", None))

    def test_forget_all_dispatches(self):
        v = _fake_viewer(_forget_all_pending=False)
        self.assertTrue(v._handle_slash_command_gui("forget-all", "ja", None))

    def test_forget_all_aliases_dispatch(self):
        for alias in ("forgetall", "delete-all", "erase-all"):
            v = _fake_viewer(_forget_all_pending=False)
            self.assertTrue(v._handle_slash_command_gui(alias, "ja", None))

    def test_forget_all_matched_before_forget(self):
        # "forget-all" must not be swallowed by the "forget " prefix branch.
        v = _fake_viewer(_forget_all_pending=False)
        with mock.patch.object(v, "_cmd_forget_all_gui") as fa, \
             mock.patch.object(v, "_cmd_forget_gui") as fg:
            v._handle_slash_command_gui("forget-all", "ja", None)
        fa.assert_called_once()
        fg.assert_not_called()


class ForgetAllGuiTests(unittest.TestCase):
    def test_first_call_only_asks_confirmation(self):
        v = _fake_viewer(_forget_all_pending=False)
        with mock.patch.object(_mod, "_erase_all_user_data") as erase:
            v._cmd_forget_all_gui("ja")
        self.assertTrue(v._forget_all_pending)
        erase.assert_not_called()
        self.assertIn("/forget-all", v.comment_text)

    def test_second_call_erases(self):
        v = _fake_viewer(_forget_all_pending=True)
        with mock.patch.object(_mod, "_erase_all_user_data",
                               return_value={"profile": True, "conversation": True,
                                             "mood": True, "avatar": True}) as erase:
            v._cmd_forget_all_gui("ja")
        erase.assert_called_once()
        self.assertFalse(v._forget_all_pending)
        self.assertIn("全部消した", v.comment_text)

    def test_second_call_english(self):
        v = _fake_viewer(_forget_all_pending=True)
        with mock.patch.object(_mod, "_erase_all_user_data",
                               return_value={"profile": True, "conversation": False,
                                             "mood": False, "avatar": False}):
            v._cmd_forget_all_gui("en")
        self.assertIn("erased everything", v.comment_text.lower())

    def test_nothing_to_erase_message(self):
        v = _fake_viewer(_forget_all_pending=True)
        with mock.patch.object(_mod, "_erase_all_user_data",
                               return_value={"profile": False, "conversation": False,
                                             "mood": False, "avatar": False}):
            v._cmd_forget_all_gui("ja")
        self.assertIn("消すデータはありません", v.comment_text)


class MainWindowChromeI18nTests(unittest.TestCase):
    """The main GUI's chrome (autonomous-toggle button, etc.) must honor the
    persona language. Regression: labels like '自律モードON' and the input
    placeholder were hardcoded Japanese, so an English user saw Japanese
    controls despite the product's advertised multi-language support."""

    def _window(self, lang):
        w = make_qt_stub(_mod.MainWindow)
        w._lang = lang
        return w

    def test_autonomous_label_english(self):
        w = self._window("en")
        self.assertEqual(w._autonomous_label(False), "Autonomous ON")
        self.assertEqual(w._autonomous_label(True), "Autonomous OFF")

    def test_autonomous_label_japanese(self):
        w = self._window("ja")
        self.assertEqual(w._autonomous_label(False), "自律モードON")
        self.assertEqual(w._autonomous_label(True), "自律モードOFF")

    def test_autonomous_label_defaults_to_japanese_for_unknown(self):
        w = self._window("fr")
        self.assertEqual(w._autonomous_label(False), "自律モードON")

    def test_english_label_has_no_japanese(self):
        w = self._window("en")
        for is_on in (False, True):
            label = w._autonomous_label(is_on)
            self.assertTrue(label.isascii(), f"English label not ASCII: {label!r}")


class MainWindowWelcomeTests(unittest.TestCase):
    """First-launch onboarding must fire exactly once, for genuinely new
    users only. Without it the product's core value (memory, affinity,
    slash commands) is invisible at first contact."""

    def _window(self, lang="ja"):
        w = make_qt_stub(_mod.MainWindow)
        w._lang = lang
        w.viewer = mock.Mock()
        return w

    def _patches(self, interactions=0, name="", history=None):
        tracker = mock.Mock()
        tracker.interactions = interactions
        prof = mock.Mock()
        prof.name = name
        conv = mock.Mock()
        conv.recent.return_value = history or []
        return (
            mock.patch.object(_mod, "get_mood_tracker", return_value=tracker),
            mock.patch.object(_mod, "_get_user_profile_gui", return_value=prof),
            mock.patch.object(_mod, "get_conversation_log", return_value=conv),
        )

    def test_shows_welcome_for_new_user(self):
        w = self._window()
        p1, p2, p3 = self._patches()
        with p1, p2, p3:
            self.assertTrue(w._maybe_show_welcome())
        w.viewer._speak_reply.assert_called_once()
        msg = w.viewer._speak_reply.call_args[0][0]
        self.assertIn("/help", msg)

    def test_silent_for_returning_user_with_interactions(self):
        w = self._window()
        p1, p2, p3 = self._patches(interactions=7)
        with p1, p2, p3:
            self.assertFalse(w._maybe_show_welcome())
        w.viewer._speak_reply.assert_not_called()

    def test_silent_when_profile_name_known(self):
        w = self._window()
        p1, p2, p3 = self._patches(name="さくら")
        with p1, p2, p3:
            self.assertFalse(w._maybe_show_welcome())
        w.viewer._speak_reply.assert_not_called()

    def test_silent_when_history_exists(self):
        w = self._window()
        p1, p2, p3 = self._patches(history=[{"event_type": "user_comment"}])
        with p1, p2, p3:
            self.assertFalse(w._maybe_show_welcome())
        w.viewer._speak_reply.assert_not_called()

    def test_english_welcome_for_en_lang(self):
        w = self._window(lang="en")
        p1, p2, p3 = self._patches()
        with p1, p2, p3:
            w._maybe_show_welcome()
        msg = w.viewer._speak_reply.call_args[0][0]
        self.assertIn("Nice to meet you", msg)

    def test_survives_unavailable_modules(self):
        w = self._window()
        with mock.patch.object(_mod, "_is_first_run", None), \
             mock.patch.object(_mod, "_welcome_message", None):
            self.assertFalse(w._maybe_show_welcome())  # must not raise

    def test_survives_broken_stores(self):
        w = self._window()
        with mock.patch.object(_mod, "get_mood_tracker",
                               side_effect=RuntimeError("mood broken")):
            self.assertFalse(w._maybe_show_welcome())  # must not raise


class MainWindowCloseEventTests(unittest.TestCase):
    """closeEvent must fully tear down: stop+join the TTS thread and stop both
    QTimers. Regression (W-02): it previously only set tts_thread.running=False
    (no join) and left text_timer/viewer.timer running, so a timer could fire
    after the widget was destroyed and access a dead widget."""

    def _window(self):
        w = make_qt_stub(_mod.MainWindow)
        w.tts_thread = mock.Mock()
        w.text_timer = mock.Mock()
        w.viewer = mock.Mock()
        w.viewer.timer = mock.Mock()
        w.break_reminder = None
        return w

    def _close(self, w):
        event = mock.Mock()
        with mock.patch.object(_mod, "get_mood_tracker", None), \
             mock.patch.object(_mod, "_default_mood_path", None):
            w.closeEvent(event)
        return event

    def test_tts_thread_stopped_and_joined(self):
        w = self._window()
        self._close(w)
        w.tts_thread.stop.assert_called_once()
        w.tts_thread.join.assert_called_once()

    def test_both_timers_stopped(self):
        w = self._window()
        self._close(w)
        w.text_timer.stop.assert_called_once()
        w.viewer.timer.stop.assert_called_once()

    def test_event_accepted(self):
        w = self._window()
        event = self._close(w)
        event.accept.assert_called_once()

    def test_survives_missing_attributes(self):
        # A partially-constructed window (Qt init failed midway) must still
        # close without raising.
        w = make_qt_stub(_mod.MainWindow)
        w.tts_thread = None
        w.viewer = None
        w.break_reminder = None
        # no text_timer attribute at all
        event = mock.Mock()
        with mock.patch.object(_mod, "get_mood_tracker", None), \
             mock.patch.object(_mod, "_default_mood_path", None):
            w.closeEvent(event)  # must not raise
        event.accept.assert_called_once()

    def test_mood_saved_on_close(self):
        w = self._window()
        tracker = mock.Mock()
        event = mock.Mock()
        with mock.patch.object(_mod, "get_mood_tracker", return_value=tracker), \
             mock.patch.object(_mod, "_default_mood_path", return_value="/tmp/m.json"):
            w.closeEvent(event)
        tracker.save.assert_called_once_with("/tmp/m.json")



class LoadAvatarModelTests(unittest.TestCase):
    """AutonomousAvatarViewer.load_avatar_model wires the --avatar-loader
    selection into the main 3D GUI. Regression for W7: the flagship GUI used
    to always draw a placeholder sphere with no way to show a chosen model."""

    def _viewer(self):
        v = _fake_viewer(avatar_model_vertices=None, avatar_model_path=None)
        v.update = lambda: None  # headless: no real Qt widget
        return v

    def test_explicit_path_success_sets_state(self):
        v = self._viewer()
        with mock.patch.object(_mod, "_load_model_geometry",
                               return_value=([[0, 0, 0], [1, 1, 1]], None, None)):
            ok = v.load_avatar_model("/models/a.glb")
        self.assertTrue(ok)
        self.assertEqual(v.avatar_model_path, "/models/a.glb")
        self.assertIsNotNone(v.avatar_model_vertices)

    def test_load_failure_leaves_state_unchanged(self):
        v = self._viewer()
        with mock.patch.object(_mod, "_load_model_geometry", return_value=None):
            ok = v.load_avatar_model("/models/broken.glb")
        self.assertFalse(ok)
        self.assertIsNone(v.avatar_model_path)
        self.assertIsNone(v.avatar_model_vertices)

    def test_no_path_uses_store_resolution(self):
        v = self._viewer()
        fake_store = mock.Mock()
        fake_store.resolve_selected_avatar.return_value = "/models/resolved.vrm"
        with mock.patch.object(_mod, "_avatar_model_store", fake_store), \
             mock.patch.object(_mod, "_load_model_geometry",
                               return_value=([[0, 0, 0]], None, None)):
            ok = v.load_avatar_model()
        self.assertTrue(ok)
        self.assertEqual(v.avatar_model_path, "/models/resolved.vrm")

    def test_no_store_and_no_path_returns_false(self):
        v = self._viewer()
        with mock.patch.object(_mod, "_avatar_model_store", None):
            self.assertFalse(v.load_avatar_model())

    def test_store_resolves_none_returns_false(self):
        v = self._viewer()
        fake_store = mock.Mock()
        fake_store.resolve_selected_avatar.return_value = None
        with mock.patch.object(_mod, "_avatar_model_store", fake_store):
            self.assertFalse(v.load_avatar_model())


class AvatarCommandGuiTests(unittest.TestCase):
    """/avatar はその場でモデルを選ばせ、選択を即座に反映する。

    以前は「表示中のモデル名を言う」だけで、選ぶには本体を終了して
    `--avatar-loader`（tkinter の別アプリ）を起動し、選んでから**再起動**する
    必要があった。1 つの機能のために GUI ツールキットを 2 つ抱え、プロセスを
    跨いで選択を受け渡し、ユーザーに再起動を強いる形だった。本体は既に PyQt5 を
    持っているので、QFileDialog を直接開けば済む。
    """

    def _viewer(self):
        v = _fake_viewer(avatar_model_vertices=None, avatar_model_path=None)
        v.update = lambda: None
        return v

    def _with_dialog(self, chosen):
        """QFileDialog.getOpenFileName を差し替えるコンテキスト。"""
        fake = mock.Mock()
        fake.getOpenFileName.return_value = (chosen, "")
        return mock.patch.object(_mod, "QFileDialog", fake)

    def test_opens_a_picker_and_loads_the_chosen_model(self):
        v = self._viewer()
        with self._with_dialog("/m/nekomimi.glb"), \
             mock.patch.object(_mod, "_avatar_model_store", None), \
             mock.patch.object(_mod, "_load_model_geometry",
                               return_value=([[0, 0, 0]], None, None)):
            v._cmd_avatar_gui("ja")
        self.assertIn("nekomimi.glb", v.comment_text)

    def test_cancelling_the_picker_says_nothing(self):
        """キャンセルに反応して喋らないこと（黙って戻る）。"""
        v = self._viewer()
        v.comment_text = ""
        with self._with_dialog(""), \
             mock.patch.object(_mod, "_avatar_model_store", None):
            v._cmd_avatar_gui("ja")
        self.assertEqual(v.comment_text, "")

    def test_unreadable_model_reports_the_failure(self):
        v = self._viewer()
        with self._with_dialog("/m/broken.glb"), \
             mock.patch.object(_mod, "_avatar_model_store", None), \
             mock.patch.object(_mod, "_load_model_geometry", return_value=None):
            v._cmd_avatar_gui("ja")
        self.assertIn("読めなかった", v.comment_text)

    def test_selection_is_persisted_for_the_next_launch(self):
        v = self._viewer()
        store = mock.Mock()
        with self._with_dialog("/m/fresh.glb"), \
             mock.patch.object(_mod, "_avatar_model_store", store), \
             mock.patch.object(_mod, "_load_model_geometry",
                               return_value=([[0, 0, 0]], None, None)):
            v._cmd_avatar_gui("ja")
        store.save_selection.assert_called_once_with("/m/fresh.glb")

    def test_falls_back_to_reporting_when_no_dialog_is_available(self):
        """ヘッドレス等で QFileDialog が使えないときは現状を報告する。"""
        v = self._viewer()
        v.avatar_model_path = "/home/u/models/nekomimi.glb"
        with mock.patch.object(_mod, "QFileDialog", None), \
             mock.patch.object(_mod, "_avatar_model_store", None):
            v._cmd_avatar_gui("ja")
        self.assertIn("nekomimi.glb", v.comment_text)

    def test_fallback_says_nothing_is_loaded_without_pointing_at_another_mode(self):
        """未設定でも、別モードを起動して再起動しろとは言わないこと。"""
        v = self._viewer()
        with mock.patch.object(_mod, "QFileDialog", None), \
             mock.patch.object(_mod, "_avatar_model_store", None):
            v._cmd_avatar_gui("en")
        self.assertIn("No avatar", v.comment_text)
        self.assertNotIn("--avatar-loader", v.comment_text)
        self.assertNotIn("restart", v.comment_text.lower())


if __name__ == "__main__":
    unittest.main()
