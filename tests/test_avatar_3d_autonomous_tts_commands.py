"""
Unit tests for the GUI slash commands added to AutonomousAvatarViewer:
/forget-fact, /export-log, /clear-log.

Socratic-review finding: these three commands existed in the headless CLI
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
from unittest import mock

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import avatar_3d_autonomous_tts as _mod  # noqa: E402


def _fake_viewer(**overrides):
    v = object.__new__(_mod.AutonomousAvatarViewer)
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

    def log_exchange(self, user_text, reply):
        self.exchanges.append((user_text, reply))

    def to_csv(self, avatar_label="Avatar", include_archives=True):
        lines = ["speaker,text"]
        for user_text, reply in self.exchanges:
            lines.append(f"You,{user_text}")
            lines.append(f"{avatar_label},{reply}")
        return "\n".join(lines) + "\n"


class ForgetFactGuiTests(unittest.TestCase):
    def test_removes_matching_fact_by_partial_value(self):
        v = _fake_viewer()
        prof = _FakeProfile(facts={"hobby": "登山"})
        with mock.patch.object(_mod, "_get_user_profile_gui", return_value=prof), \
             mock.patch.object(_mod, "_default_profile_path_gui", return_value="/tmp/p.json"):
            v._cmd_forget_fact_gui("登山", "ja")
        self.assertNotIn("hobby", prof.facts)
        self.assertIn("わかった", v.comment_text)

    def test_no_match_leaves_facts_untouched(self):
        v = _fake_viewer()
        prof = _FakeProfile(facts={"hobby": "登山"})
        with mock.patch.object(_mod, "_get_user_profile_gui", return_value=prof), \
             mock.patch.object(_mod, "_default_profile_path_gui", return_value="/tmp/p.json"):
            v._cmd_forget_fact_gui("存在しない話", "ja")
        self.assertIn("hobby", prof.facts)
        self.assertIn("存在しない話", v.comment_text)

    def test_empty_arg_shows_usage_without_deleting(self):
        v = _fake_viewer()
        prof = _FakeProfile(facts={"hobby": "登山"})
        with mock.patch.object(_mod, "_get_user_profile_gui", return_value=prof):
            v._cmd_forget_fact_gui("", "ja")
        self.assertIn("hobby", prof.facts)
        self.assertIn("/forget-fact", v.comment_text)

    def test_english_reply(self):
        v = _fake_viewer()
        prof = _FakeProfile(facts={"food": "ramen and udon"})
        with mock.patch.object(_mod, "_get_user_profile_gui", return_value=prof), \
             mock.patch.object(_mod, "_default_profile_path_gui", return_value="/tmp/p.json"):
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
             mock.patch.object(_mod, "_default_profile_path_gui", return_value="/tmp/p.json"):
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
             mock.patch.object(_mod, "_default_profile_path_gui", return_value="/tmp/p.json"):
            v._handle_slash_command_gui("forget-fact 登山", "ja", None)
        # If /forget (interests) had swallowed this, facts would be untouched
        # and the reply would talk about a missing interest instead.
        self.assertNotIn("hobby", prof.facts)


if __name__ == "__main__":
    unittest.main()
