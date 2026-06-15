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


class PersonaSemanticValidationTests(unittest.TestCase):
    """validate_configs performs semantic checks on persona.json."""

    def _write(self, d: str, name: str, content: str) -> str:
        path = os.path.join(d, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def test_valid_persona_no_errors(self):
        with tempfile.TemporaryDirectory() as d:
            self._write(d, "persona.json",
                        '{"name": "Satin", "default_lang": "ja", '
                        '"responses": {"ja": {"rules": ['
                        '{"keywords": ["hi"], "replies": ["yo"]}], "fallback": ["ok"]}}}')
            errors = manage_satin.validate_configs(d)
        self.assertEqual(errors, [])

    def test_rule_not_dict_is_error(self):
        with tempfile.TemporaryDirectory() as d:
            self._write(d, "persona.json",
                        '{"name": "S", "responses": {"ja": {"rules": ["notadict"]}}}')
            errors = manage_satin.validate_configs(d)
        self.assertTrue(any("rules[0]" in e for e in errors))

    def test_invalid_persona_syntax_still_caught(self):
        with tempfile.TemporaryDirectory() as d:
            self._write(d, "persona.json", "{bad json")
            errors = manage_satin.validate_configs(d)
        self.assertTrue(any("persona.json" in e for e in errors))


class MoodConfigSemanticValidationTests(unittest.TestCase):
    """validate_configs performs semantic checks on mood_config.json."""

    def _write(self, d: str, name: str, content: str) -> str:
        path = os.path.join(d, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def test_valid_mood_config_no_errors(self):
        with tempfile.TemporaryDirectory() as d:
            self._write(d, "mood_config.json",
                        '{"positive": {"ja": ["good"]}, "negative": {"ja": ["bad"]}}')
            errors = manage_satin.validate_configs(d)
        self.assertEqual(errors, [])

    def test_positive_not_dict_is_error(self):
        with tempfile.TemporaryDirectory() as d:
            self._write(d, "mood_config.json", '{"positive": ["notdict"]}')
            errors = manage_satin.validate_configs(d)
        self.assertTrue(any("positive" in e for e in errors))

    def test_words_not_list_is_error(self):
        with tempfile.TemporaryDirectory() as d:
            self._write(d, "mood_config.json", '{"negative": {"ja": "notalist"}}')
            errors = manage_satin.validate_configs(d)
        self.assertTrue(any("negative.ja" in e for e in errors))


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


class BackupRestoreTests(unittest.TestCase):
    """cmd_backup_restore must extract config/ and log files from a sync backup zip."""

    def setUp(self):
        import zipfile
        self._tmp = tempfile.mkdtemp()
        self._dest = tempfile.mkdtemp()
        self._zipfile_mod = zipfile
        # Build a minimal backup zip
        self._zip = os.path.join(self._tmp, "backup_test.zip")
        with zipfile.ZipFile(self._zip, "w") as zf:
            zf.writestr("config/persona.json", '{"name": "Satin"}')
            zf.writestr("config/plugins/break_reminder.json", '{"enabled": true}')
            zf.writestr("avatar_event_log.jsonl", '{"event_type":"user_comment"}\n')

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)
        shutil.rmtree(self._dest, ignore_errors=True)

    def test_restore_extracts_config_files(self):
        with mock.patch("builtins.input", return_value="y"):
            manage_satin.cmd_backup_restore(self._zip, self._dest)
        self.assertTrue(
            os.path.exists(os.path.join(self._dest, "config", "persona.json"))
        )
        self.assertTrue(
            os.path.exists(os.path.join(self._dest, "config", "plugins", "break_reminder.json"))
        )

    def test_restore_extracts_log_file(self):
        with mock.patch("builtins.input", return_value="y"):
            manage_satin.cmd_backup_restore(self._zip, self._dest)
        self.assertTrue(
            os.path.exists(os.path.join(self._dest, "avatar_event_log.jsonl"))
        )

    def test_cancel_does_not_extract(self):
        with mock.patch("builtins.input", return_value="n"):
            manage_satin.cmd_backup_restore(self._zip, self._dest)
        self.assertFalse(
            os.path.exists(os.path.join(self._dest, "config", "persona.json"))
        )

    def test_missing_zip_exits(self):
        with self.assertRaises(SystemExit):
            manage_satin.cmd_backup_restore(os.path.join(self._tmp, "nope.zip"), self._dest)

    def test_non_satin_zip_exits(self):
        empty_zip = os.path.join(self._tmp, "empty.zip")
        with self._zipfile_mod.ZipFile(empty_zip, "w"):
            pass  # empty zip
        with self.assertRaises(SystemExit):
            with mock.patch("builtins.input", return_value="y"):
                manage_satin.cmd_backup_restore(empty_zip, self._dest)

    def test_traversal_entries_are_skipped(self):
        """Path traversal entries (../../etc/passwd) must not be extracted."""
        malicious_zip = os.path.join(self._tmp, "malicious.zip")
        with self._zipfile_mod.ZipFile(malicious_zip, "w") as zf:
            zf.writestr("config/good.json", "{}")
            zf.writestr("../../evil.txt", "pwned")
        with mock.patch("builtins.input", return_value="y"):
            manage_satin.cmd_backup_restore(malicious_zip, self._dest)
        self.assertTrue(os.path.exists(os.path.join(self._dest, "config", "good.json")))
        # The traversal path must NOT have been written
        evil_path = os.path.normpath(os.path.join(self._dest, "../../evil.txt"))
        self.assertFalse(os.path.exists(evil_path))


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

    def test_persona_no_subcommand_returns_1(self):
        rc = manage_satin.main(["persona"])
        self.assertEqual(rc, 1)

    def test_persona_show_returns_0(self):
        rc = manage_satin.main(["persona", "show"])
        self.assertEqual(rc, 0)

    def test_summary_returns_0(self):
        rc = manage_satin.main(["summary"])
        self.assertEqual(rc, 0)

    def test_summary_yesterday_returns_0(self):
        rc = manage_satin.main(["summary", "--yesterday"])
        self.assertEqual(rc, 0)

    def test_summary_en_returns_0(self):
        rc = manage_satin.main(["summary", "--lang", "en"])
        self.assertEqual(rc, 0)


class SummaryCommandTests(unittest.TestCase):
    def test_cmd_summary_prints_date(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            manage_satin.cmd_summary(lang="ja")
        output = buf.getvalue()
        self.assertIn("サマリー", output)

    def test_cmd_summary_prints_interaction_count(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            manage_satin.cmd_summary(lang="ja")
        output = buf.getvalue()
        self.assertIn("合計やりとり", output)


class MoodImportTests(unittest.TestCase):
    def test_import_updates_tracker(self):
        import mood as _mood
        _mood.reset_mood_tracker()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                src = os.path.join(tmp, "mood_export.json")
                with open(src, "w") as f:
                    json.dump({"affinity": 80.0, "interactions": 42, "last_interaction_time": 0.0}, f)
                mood_path = os.path.join(tmp, "mood.json")
                from unittest import mock
                with mock.patch.object(_mood, "_default_mood_path", lambda: mood_path):
                    manage_satin.cmd_mood_import(src)
                tracker = _mood.get_mood_tracker()
                self.assertAlmostEqual(tracker.affinity, 80.0, places=1)
                self.assertEqual(tracker.interactions, 42)
        finally:
            _mood.reset_mood_tracker()


class LogCsvTests(unittest.TestCase):
    def test_csv_export_creates_file(self):
        from conversation_log import ConversationLog, reset_conversation_log
        reset_conversation_log()
        with tempfile.TemporaryDirectory() as tmp:
            log_path = os.path.join(tmp, "events.jsonl")
            log = ConversationLog(log_path)
            log.log_exchange("hello", "hi")
            dest = os.path.join(tmp, "conv.csv")
            from unittest import mock
            import conversation_log as _cl
            with mock.patch.object(_cl, "DEFAULT_LOGFILE", log_path), \
                 mock.patch.object(manage_satin, "_ROOT", tmp):
                manage_satin.cmd_log_csv(dest)
            self.assertTrue(os.path.exists(dest))
            content = open(dest, encoding="utf-8-sig").read()
            self.assertIn("timestamp", content)
            self.assertIn("hello", content)


class PersonaShowTests(unittest.TestCase):
    def test_persona_show_prints_name(self, capsys=None):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            manage_satin.cmd_persona_show()
        out = buf.getvalue()
        self.assertTrue(len(out) > 0)


class LogClearTests(unittest.TestCase):
    """cmd_log_clear must truncate the live log AND delete rotated .gz archives.
    Previously it used log._path (AttributeError) and ignored archives, leaving
    old private conversation data on disk after a "clear."
    """

    def setUp(self):
        import gzip
        from conversation_log import reset_conversation_log, ConversationLog
        self._gzip = gzip
        self._tmp = tempfile.mkdtemp()
        self._logfile = os.path.join(self._tmp, "events.jsonl")
        # Write some events so the file exists
        with open(self._logfile, "w", encoding="utf-8") as f:
            f.write('{"event_type":"user_comment","timestamp":1,"details":{"text":"hi"}}\n')
        # Also create a rotated gz archive
        self._gz = self._logfile + ".20260101_000000.gz"
        with gzip.open(self._gz, "wt", encoding="utf-8") as fh:
            fh.write('{"event_type":"user_comment","timestamp":0,"details":{"text":"old"}}\n')
        # Inject a fresh ConversationLog pointing at our temp file
        reset_conversation_log()
        self._log_obj = ConversationLog(self._logfile)
        self._cl_mod = sys.modules.get("conversation_log")

    def tearDown(self):
        import shutil
        from conversation_log import reset_conversation_log
        shutil.rmtree(self._tmp, ignore_errors=True)
        reset_conversation_log()

    def _run_clear(self):
        with mock.patch("builtins.input", return_value="y"), \
             mock.patch("conversation_log.get_conversation_log",
                        return_value=self._log_obj):
            manage_satin.cmd_log_clear(log_path=self._logfile)

    def test_clear_truncates_live_log(self):
        self._run_clear()
        self.assertEqual(os.path.getsize(self._logfile), 0)

    def test_clear_deletes_gz_archives(self):
        self._run_clear()
        self.assertFalse(os.path.exists(self._gz),
                         ".gz archive must be deleted by log clear")

    def test_cancel_does_not_clear(self):
        with mock.patch("builtins.input", return_value="n"), \
             mock.patch("conversation_log.get_conversation_log",
                        return_value=self._log_obj):
            manage_satin.cmd_log_clear(log_path=self._logfile)
        self.assertGreater(os.path.getsize(self._logfile), 0)
        self.assertTrue(os.path.exists(self._gz))

    def test_missing_log_prints_message(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        missing = os.path.join(self._tmp, "nope.jsonl")
        with redirect_stdout(buf), \
             mock.patch("conversation_log.get_conversation_log",
                        return_value=self._log_obj):
            manage_satin.cmd_log_clear(log_path=missing)
        self.assertIn("存在しません", buf.getvalue())


class LogSearchTests(unittest.TestCase):
    """cmd_log_search must search through live log (and archives) and display matches."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._logfile = os.path.join(self._tmp, "test.jsonl")
        import sys
        sys.path.insert(0, _MAIN)
        import conversation_log
        conversation_log.reset_conversation_log()
        from conversation_log import ConversationLog
        self._log = ConversationLog(self._logfile)
        self._log.log_user_comment("今日はいい天気ですね")
        self._log.log_user_comment("音楽が好きです")
        self._log.log_user_comment("ゲームを遊んでいます")

    def tearDown(self):
        import shutil, conversation_log
        shutil.rmtree(self._tmp, ignore_errors=True)
        conversation_log.reset_conversation_log()

    def _run_search(self, query, limit=0):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf), \
             mock.patch("conversation_log.get_conversation_log",
                        return_value=self._log):
            manage_satin.cmd_log_search(query, limit)
        return buf.getvalue()

    def test_search_finds_matching_entry(self):
        out = self._run_search("音楽")
        self.assertIn("音楽", out)
        self.assertNotIn("天気", out)

    def test_search_no_match_shows_message(self):
        out = self._run_search("存在しないキーワード123")
        self.assertIn("見つかりませんでした", out)

    def test_search_empty_query_returns_all(self):
        out = self._run_search("")
        self.assertIn("天気", out)
        self.assertIn("音楽", out)
        self.assertIn("ゲーム", out)

    def test_search_shows_timestamp_and_prefix(self):
        out = self._run_search("天気")
        # Should contain timestamp-format prefix [YYYY-MM-DD HH:MM:SS]
        import re
        self.assertRegex(out, r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]")

    def test_search_limit_restricts_results(self):
        out = self._run_search("", limit=1)
        # With limit=1, only 1 entry should be shown
        lines = [l for l in out.strip().splitlines() if l.startswith("[")]
        self.assertEqual(len(lines), 1)

    def test_search_main_dispatch(self):
        """manage_satin.main() routes 'log search <query>' to cmd_log_search."""
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf), \
             mock.patch("conversation_log.get_conversation_log",
                        return_value=self._log):
            manage_satin.main(["log", "search", "音楽"])
        self.assertIn("音楽", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
