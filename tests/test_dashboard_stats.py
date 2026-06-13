"""
Tests for dashboard._conversation_stats() — the Flask-independent analytics
helper that parses a JSONL event log to produce per-day / per-hour statistics.

Also tests that backup_dir listing includes .zip files (regression for the
.png/.gz-only filter bug) and that backup filenames use the .zip extension.
"""
import json
import os
import sys
import tempfile
import time
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import dashboard  # noqa: E402


class ConversationStatsEmptyTests(unittest.TestCase):
    def test_nonexistent_log(self):
        s = dashboard._conversation_stats("/nonexistent/path.jsonl")
        self.assertEqual(s["total_user"], 0)
        self.assertEqual(s["total_avatar"], 0)
        self.assertIsNone(s["peak_hour"])
        self.assertEqual(s["per_day"], {})

    def test_empty_log(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            f.write("")
            path = f.name
        try:
            s = dashboard._conversation_stats(path)
            self.assertEqual(s["total_user"], 0)
        finally:
            os.unlink(path)


class ConversationStatsTests(unittest.TestCase):
    def _write_events(self, events):
        f = tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False, encoding="utf-8")
        for ev in events:
            f.write(json.dumps(ev) + "\n")
        f.close()
        return f.name

    def _ts(self, date_str, hour=12):
        """Return a Unix timestamp for the given YYYY-MM-DD and hour."""
        import datetime
        dt = datetime.datetime.strptime(f"{date_str} {hour:02d}:00:00", "%Y-%m-%d %H:%M:%S")
        return dt.timestamp()

    def test_counts_user_and_avatar(self):
        events = [
            {"event_type": "user_comment", "timestamp": self._ts("2024-01-01"), "details": {"text": "hi"}},
            {"event_type": "avatar_reply",  "timestamp": self._ts("2024-01-01"), "details": {"text": "hello"}},
            {"event_type": "user_comment", "timestamp": self._ts("2024-01-01"), "details": {"text": "bye"}},
        ]
        path = self._write_events(events)
        try:
            s = dashboard._conversation_stats(path)
            self.assertEqual(s["total_user"], 2)
            self.assertEqual(s["total_avatar"], 1)
        finally:
            os.unlink(path)

    def test_per_day_accumulates(self):
        events = [
            {"event_type": "user_comment", "timestamp": self._ts("2024-01-01"), "details": {}},
            {"event_type": "user_comment", "timestamp": self._ts("2024-01-01"), "details": {}},
            {"event_type": "user_comment", "timestamp": self._ts("2024-01-02"), "details": {}},
        ]
        path = self._write_events(events)
        try:
            s = dashboard._conversation_stats(path)
            self.assertEqual(s["per_day"]["2024-01-01"], 2)
            self.assertEqual(s["per_day"]["2024-01-02"], 1)
        finally:
            os.unlink(path)

    def test_per_day_sorted(self):
        events = [
            {"event_type": "user_comment", "timestamp": self._ts("2024-01-03"), "details": {}},
            {"event_type": "user_comment", "timestamp": self._ts("2024-01-01"), "details": {}},
        ]
        path = self._write_events(events)
        try:
            s = dashboard._conversation_stats(path)
            keys = list(s["per_day"].keys())
            self.assertEqual(keys, sorted(keys))
        finally:
            os.unlink(path)

    def test_peak_hour_correct(self):
        events = [
            {"event_type": "user_comment", "timestamp": self._ts("2024-01-01", hour=9), "details": {}},
            {"event_type": "user_comment", "timestamp": self._ts("2024-01-01", hour=9), "details": {}},
            {"event_type": "user_comment", "timestamp": self._ts("2024-01-01", hour=14), "details": {}},
        ]
        path = self._write_events(events)
        try:
            s = dashboard._conversation_stats(path)
            self.assertEqual(s["peak_hour"], 9)
        finally:
            os.unlink(path)

    def test_per_hour_has_24_entries(self):
        path = self._write_events([
            {"event_type": "user_comment", "timestamp": self._ts("2024-01-01", hour=0), "details": {}},
        ])
        try:
            s = dashboard._conversation_stats(path)
            self.assertEqual(len(s["per_hour"]), 24)
        finally:
            os.unlink(path)

    def test_ignores_unrecognised_event_types(self):
        events = [
            {"event_type": "speak", "timestamp": self._ts("2024-01-01"), "details": {}},
            {"event_type": "user_comment", "timestamp": self._ts("2024-01-01"), "details": {}},
        ]
        path = self._write_events(events)
        try:
            s = dashboard._conversation_stats(path)
            self.assertEqual(s["total_user"], 1)
            self.assertEqual(s["total_avatar"], 0)
        finally:
            os.unlink(path)

    def test_skips_malformed_lines(self):
        f = tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False, encoding="utf-8")
        f.write("not json\n")
        f.write(json.dumps({"event_type": "user_comment", "timestamp": self._ts("2024-01-01"), "details": {}}) + "\n")
        f.close()
        try:
            s = dashboard._conversation_stats(f.name)
            self.assertEqual(s["total_user"], 1)
        finally:
            os.unlink(f.name)

    def test_user_event_type_alias(self):
        """'user' as well as 'user_comment' should count as user messages."""
        events = [
            {"event_type": "user", "timestamp": self._ts("2024-01-01"), "details": {}},
        ]
        path = self._write_events(events)
        try:
            s = dashboard._conversation_stats(path)
            self.assertEqual(s["total_user"], 1)
        finally:
            os.unlink(path)

    def test_avatar_event_type_alias(self):
        """'avatar' as well as 'avatar_reply' should count as avatar messages."""
        events = [
            {"event_type": "avatar", "timestamp": self._ts("2024-01-01"), "details": {}},
        ]
        path = self._write_events(events)
        try:
            s = dashboard._conversation_stats(path)
            self.assertEqual(s["total_avatar"], 1)
        finally:
            os.unlink(path)


class BackupListZipTests(unittest.TestCase):
    """Regression: backups route must list .zip files, not just .png/.gz."""

    def test_zip_extension_in_filter(self):
        """dashboard.backups() route source must filter .zip files."""
        import inspect
        src = inspect.getsource(dashboard.backups)
        self.assertIn(".zip", src,
                      "backups() route must include .zip in the file extension filter")

    def test_backup_sync_uses_zip_extension(self):
        """The /sync route must create backup files with .zip extension, not .gz."""
        import inspect
        src = inspect.getsource(dashboard.sync)
        self.assertIn(".zip", src)
        self.assertNotIn("backup_{ts}.gz", src,
                         "/sync route must not create .gz files — use .zip instead")

    def test_safe_backup_path_allows_zip(self):
        """_safe_backup_path must not reject .zip filenames."""
        p = dashboard._safe_backup_path("backup_20240101_120000.zip")
        self.assertIsNotNone(p)


class SyncBackupContentsTests(unittest.TestCase):
    """_build_sync_backup must capture config/ RECURSIVELY (incl. plugins/)
    plus the conversation log. Regression: the old route only archived
    top-level config/ files, silently dropping config/plugins/*.json."""

    def setUp(self):
        import zipfile
        self._tmp = tempfile.mkdtemp()
        self._cfg = os.path.join(self._tmp, "config")
        os.makedirs(os.path.join(self._cfg, "plugins"))
        # top-level config file
        with open(os.path.join(self._cfg, "persona.json"), "w") as f:
            f.write("{}")
        # nested plugin config (the previously-dropped case)
        with open(os.path.join(self._cfg, "plugins", "break_reminder.json"), "w") as f:
            f.write('{"enabled": true}')
        # conversation log living outside config/
        self._log = os.path.join(self._tmp, "avatar_event_log.jsonl")
        with open(self._log, "w") as f:
            f.write('{"event_type":"user_comment","timestamp":0}\n')
        self._zip = os.path.join(self._tmp, "backup.zip")
        self._zipfile = zipfile

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _names(self):
        dashboard._build_sync_backup(self._zip, self._cfg, self._log)
        with self._zipfile.ZipFile(self._zip) as zf:
            return set(zf.namelist())

    def test_includes_top_level_config(self):
        self.assertIn("config/persona.json", self._names())

    def test_includes_nested_plugin_config(self):
        # The whole point of the fix.
        self.assertIn("config/plugins/break_reminder.json", self._names())

    def test_includes_conversation_log(self):
        self.assertIn("avatar_event_log.jsonl", self._names())

    def test_returns_written_arcnames(self):
        written = dashboard._build_sync_backup(self._zip, self._cfg, self._log)
        self.assertIn("config/plugins/break_reminder.json", written)

    def test_missing_log_is_skipped_gracefully(self):
        written = dashboard._build_sync_backup(
            self._zip, self._cfg, os.path.join(self._tmp, "nope.jsonl")
        )
        self.assertNotIn("nope.jsonl", written)
        self.assertIn("config/persona.json", written)


if __name__ == "__main__":
    unittest.main()
