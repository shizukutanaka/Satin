"""
Unit tests for manage_satin — the batch management CLI.

Covers: validate_configs (success/error/empty), mood subcommands,
log subcommands, backup list, and the argparse main() dispatcher.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import manage_satin


# --------------------------------------------------------------------------- #
# validate_configs
# --------------------------------------------------------------------------- #
class ValidateConfigsTests(unittest.TestCase):
    def _write(self, d: str, name: str, content: str) -> str:
        path = os.path.join(d, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def test_valid_json_returns_no_errors(self):
        with tempfile.TemporaryDirectory() as d:
            self._write(d, "a.json", '{"key": "value"}')
            errors = manage_satin.validate_configs(d)
        self.assertEqual(errors, [])

    def test_invalid_json_returns_error(self):
        with tempfile.TemporaryDirectory() as d:
            self._write(d, "bad.json", "{not valid json")
            errors = manage_satin.validate_configs(d)
        self.assertEqual(len(errors), 1)
        self.assertIn("bad.json", errors[0])

    def test_empty_dir_returns_no_errors(self):
        with tempfile.TemporaryDirectory() as d:
            errors = manage_satin.validate_configs(d)
        self.assertEqual(errors, [])

    def test_multiple_files_all_valid(self):
        with tempfile.TemporaryDirectory() as d:
            for i in range(3):
                self._write(d, f"cfg{i}.json", f'{{"n": {i}}}')
            errors = manage_satin.validate_configs(d)
        self.assertEqual(errors, [])

    def test_mixed_valid_and_invalid(self):
        with tempfile.TemporaryDirectory() as d:
            self._write(d, "good.json", '{}')
            self._write(d, "bad.json", 'oops')
            errors = manage_satin.validate_configs(d)
        self.assertEqual(len(errors), 1)


# --------------------------------------------------------------------------- #
# mood subcommands
# --------------------------------------------------------------------------- #
class MoodShowTests(unittest.TestCase):
    def test_show_prints_score(self):
        import mood as _mood
        _mood.reset_mood_tracker()
        tmp = tempfile.mkdtemp()
        try:
            mood_path = os.path.join(tmp, "mood.json")
            with mock.patch.object(_mood, "_default_mood_path", lambda: mood_path):
                out = []
                with mock.patch("builtins.print", side_effect=lambda *a, **k: out.append(" ".join(str(x) for x in a))):
                    manage_satin.cmd_mood_show()
            self.assertTrue(any("好感度スコア" in line for line in out))
            self.assertTrue(any("/100" in line for line in out))
        finally:
            _mood.reset_mood_tracker()
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


class MoodResetTests(unittest.TestCase):
    def test_reset_sets_neutral(self):
        import mood as _mood
        _mood.reset_mood_tracker()
        tracker = _mood.get_mood_tracker()
        tracker.affinity = 90
        tracker.interactions = 5
        tmp = tempfile.mkdtemp()
        try:
            mood_path = os.path.join(tmp, "mood.json")
            with mock.patch.object(_mood, "_default_mood_path", lambda: mood_path):
                out = []
                with mock.patch("builtins.print", side_effect=lambda *a, **k: out.append(" ".join(str(x) for x in a))):
                    manage_satin.cmd_mood_reset()
            # After reset the tracker is wiped; re-get gives neutral
            _mood.reset_mood_tracker()
            fresh = _mood.MoodTracker.from_dict(json.loads(open(mood_path).read()))
            self.assertEqual(fresh.affinity, _mood.AFFINITY_START)
            self.assertEqual(fresh.interactions, 0)
            self.assertTrue(any("ニュートラル" in line for line in out))
        finally:
            _mood.reset_mood_tracker()
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


class MoodExportTests(unittest.TestCase):
    def test_export_writes_json(self):
        import mood as _mood
        _mood.reset_mood_tracker()
        tracker = _mood.get_mood_tracker()
        tracker.affinity = 75
        tmp = tempfile.mkdtemp()
        try:
            dest = os.path.join(tmp, "export.json")
            manage_satin.cmd_mood_export(dest)
            self.assertTrue(os.path.exists(dest))
            data = json.loads(open(dest).read())
            self.assertIn("affinity", data)
        finally:
            _mood.reset_mood_tracker()
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------- #
# log subcommands
# --------------------------------------------------------------------------- #
class LogShowTests(unittest.TestCase):
    def setUp(self):
        from conversation_log import ConversationLog, reset_conversation_log
        reset_conversation_log()
        self._tmp = tempfile.mkdtemp()
        self._log = ConversationLog(os.path.join(self._tmp, "c.jsonl"))

    def tearDown(self):
        from conversation_log import reset_conversation_log
        reset_conversation_log()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_show_prints_history(self):
        from conversation_log import get_conversation_log
        import conversation_log as _cl
        with mock.patch.object(_cl, "_conversation_log", self._log, create=True):
            self._log.log_exchange("hello", "hi")
            out = []
            with mock.patch("builtins.print", side_effect=lambda *a, **k: out.append(" ".join(str(x) for x in a))):
                manage_satin.cmd_log_show(n=10)
            self.assertTrue(any("hello" in line or "hi" in line for line in out))

    def test_show_empty_log(self):
        import conversation_log as _cl
        with mock.patch.object(_cl, "_conversation_log", self._log, create=True):
            out = []
            with mock.patch("builtins.print", side_effect=lambda *a, **k: out.append(" ".join(str(x) for x in a))):
                manage_satin.cmd_log_show(n=10)
            self.assertTrue(any("空" in line for line in out))


class LogExportTests(unittest.TestCase):
    def setUp(self):
        from conversation_log import ConversationLog, reset_conversation_log
        reset_conversation_log()
        self._tmp = tempfile.mkdtemp()
        self._log = ConversationLog(os.path.join(self._tmp, "c.jsonl"))

    def tearDown(self):
        from conversation_log import reset_conversation_log
        reset_conversation_log()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_export_writes_json(self):
        import conversation_log as _cl
        with mock.patch.object(_cl, "_conversation_log", self._log, create=True):
            self._log.log_exchange("test", "reply")
            dest = os.path.join(self._tmp, "export.json")
            manage_satin.cmd_log_export(dest)
            data = json.loads(open(dest).read())
            self.assertIsInstance(data, list)
            self.assertGreater(len(data), 0)


# --------------------------------------------------------------------------- #
# backup list
# --------------------------------------------------------------------------- #
class BackupListTests(unittest.TestCase):
    def test_missing_dir_prints_message(self):
        out = []
        with mock.patch("builtins.print", side_effect=lambda *a, **k: out.append(" ".join(str(x) for x in a))):
            manage_satin.cmd_backup_list("/nonexistent_dir_xyz_42")
        self.assertTrue(any("見つかりません" in line for line in out))

    def test_lists_gz_and_json_files(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "snapshot.gz"), "w").close()
            open(os.path.join(d, "report.json"), "w").close()
            open(os.path.join(d, "ignored.txt"), "w").close()
            out = []
            with mock.patch("builtins.print", side_effect=lambda *a, **k: out.append(" ".join(str(x) for x in a))):
                manage_satin.cmd_backup_list(d)
            combined = "\n".join(out)
            self.assertIn("snapshot.gz", combined)
            self.assertIn("report.json", combined)
            self.assertNotIn("ignored.txt", combined)


# --------------------------------------------------------------------------- #
# main() dispatcher
# --------------------------------------------------------------------------- #
class MainDispatcherTests(unittest.TestCase):
    def test_no_args_prints_help_and_returns_0(self):
        rc = manage_satin.main([])
        self.assertEqual(rc, 0)

    def test_validate_ok_returns_0(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "ok.json"), "w") as f:
                f.write("{}")
            rc = manage_satin.main(["validate", "--config-dir", d])
        self.assertEqual(rc, 0)

    def test_validate_bad_returns_1(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "bad.json"), "w") as f:
                f.write("not json")
            rc = manage_satin.main(["validate", "--config-dir", d])
        self.assertEqual(rc, 1)

    def test_mood_no_subcommand_returns_1(self):
        rc = manage_satin.main(["mood"])
        self.assertEqual(rc, 1)

    def test_log_no_subcommand_returns_1(self):
        rc = manage_satin.main(["log"])
        self.assertEqual(rc, 1)

    def test_backup_no_subcommand_returns_1(self):
        rc = manage_satin.main(["backup"])
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
