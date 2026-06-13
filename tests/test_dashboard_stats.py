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


if __name__ == "__main__":
    unittest.main()
