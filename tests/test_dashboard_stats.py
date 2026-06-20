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

    def test_null_timestamp_does_not_abort_iteration(self):
        """Regression: 'timestamp': null must not abort the stats loop early.

        ev.get('timestamp', 0) returns None (not 0) when the key is present but
        null. datetime.fromtimestamp(None) raises TypeError which the original
        code did not catch, causing the outer except Exception to swallow the
        entire remaining loop.

        With the fix: the null-timestamp event is counted in total_user (the
        increment precedes the fromtimestamp call) but skips time-based stats;
        subsequent events continue to be processed.
        """
        events = [
            {"event_type": "user_comment", "timestamp": self._ts("2024-01-01"), "details": {}},
            {"event_type": "user_comment", "timestamp": None, "details": {}},  # JSON null
            {"event_type": "user_comment", "timestamp": self._ts("2024-01-02"), "details": {}},
        ]
        path = self._write_events(events)
        try:
            s = dashboard._conversation_stats(path)
            # All 3 user events counted (null-ts included; only time stats skipped).
            self.assertEqual(s["total_user"], 3,
                             "All events including null-ts must be counted; loop must not abort")
            # Both valid-ts dates must appear — proves Event 3 was processed.
            self.assertIn("2024-01-01", s["per_day"],
                          "2024-01-01 event must be in per_day")
            self.assertIn("2024-01-02", s["per_day"],
                          "2024-01-02 event must be in per_day (loop must not abort at null-ts)")
        finally:
            os.unlink(path)

    def test_string_timestamp_does_not_abort_iteration(self):
        """Regression: non-numeric timestamp must be skipped, not abort the loop."""
        events = [
            {"event_type": "user_comment", "timestamp": self._ts("2024-01-01"), "details": {}},
            {"event_type": "user_comment", "timestamp": "not-a-number", "details": {}},
            {"event_type": "avatar_reply",  "timestamp": self._ts("2024-01-01"), "details": {}},
        ]
        path = self._write_events(events)
        try:
            s = dashboard._conversation_stats(path)
            # Both user events counted; avatar event after the bad-ts must also count.
            self.assertEqual(s["total_user"], 2,
                             "User events (including bad-ts one) must be counted")
            self.assertEqual(s["total_avatar"], 1,
                             "Avatar event after bad-ts must be counted (loop must not abort)")
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

    def test_includes_rotated_gz_archives(self):
        """ローテートされた .gz アーカイブもバックアップに含まれること。
        機種変更時に旧会話履歴が丸ごと失われる問題の回帰テスト。"""
        import gzip
        gz_name = os.path.basename(self._log) + ".20260101_000000.gz"
        gz_path = os.path.join(self._tmp, gz_name)
        with gzip.open(gz_path, "wt", encoding="utf-8") as fh:
            fh.write('{"event_type":"user_comment","timestamp":1}\n')
        names = self._names()
        self.assertIn(gz_name, names)

    def test_backup_without_gz_archives_still_works(self):
        """アーカイブが存在しない場合も通常通り動作すること。"""
        names = self._names()
        self.assertIn("avatar_event_log.jsonl", names)
        self.assertIn("config/persona.json", names)


class ConversationSearchNullTimestampTests(unittest.TestCase):
    """Regression: conversation_search route must catch TypeError from
    datetime.fromtimestamp(None) when an event has "timestamp": null.

    The original except clause was (ValueError, OSError, OverflowError) —
    missing TypeError — so a null timestamp caused an unhandled exception
    and a 500 error for the search route.
    """

    def test_conversation_search_catches_type_error(self):
        """Source of conversation_search must include TypeError in the
        fromtimestamp except to guard against null/string timestamps."""
        import inspect
        src = inspect.getsource(dashboard.conversation_search)
        self.assertIn("TypeError", src,
                      "conversation_search must catch TypeError from "
                      "datetime.fromtimestamp(None) on null timestamps")


class CoerceAffinityTests(unittest.TestCase):
    """_coerce_affinity guards the /mood/history route against null/non-numeric
    affinity values.  Regression: float(e.get("affinity", 0)) crashed with
    TypeError when a history entry had "affinity": null, 500-ing the route."""

    def test_none_returns_default(self):
        self.assertEqual(dashboard._coerce_affinity(None), 0.0)

    def test_none_returns_custom_default(self):
        self.assertEqual(dashboard._coerce_affinity(None, 50.0), 50.0)

    def test_float_passthrough(self):
        self.assertEqual(dashboard._coerce_affinity(75.0), 75.0)

    def test_int_coerced(self):
        self.assertEqual(dashboard._coerce_affinity(80), 80.0)

    def test_numeric_string_coerced(self):
        self.assertEqual(dashboard._coerce_affinity("80"), 80.0)

    def test_non_numeric_string_returns_default(self):
        self.assertEqual(dashboard._coerce_affinity("abc"), 0.0)

    def test_used_by_mood_history_route(self):
        """The /mood/history route must use _coerce_affinity, not raw float()."""
        import inspect
        src = inspect.getsource(dashboard.mood_history)
        self.assertIn("_coerce_affinity", src,
                      "mood_history must use _coerce_affinity to guard null affinity")
        self.assertNotIn('float(e.get("affinity", 0))', src,
                         "mood_history must not call float() directly on a null-able field")


class DashboardPortResolutionTests(unittest.TestCase):
    """Regression: launcher (--dashboard) and dashboard.py __main__ must resolve
    to the SAME default port. Previously the launcher defaulted to 5000 while
    dashboard.py ran on 5003, diverging from the README and direct execution."""

    def setUp(self):
        self._saved = os.environ.pop("SATIN_DASHBOARD_PORT", None)

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("SATIN_DASHBOARD_PORT", None)
        else:
            os.environ["SATIN_DASHBOARD_PORT"] = self._saved

    def test_default_port_is_5003(self):
        self.assertEqual(dashboard.DEFAULT_DASHBOARD_PORT, 5003)

    def test_resolve_port_default(self):
        self.assertEqual(dashboard._resolve_port(), 5003)

    def test_resolve_port_env_override(self):
        os.environ["SATIN_DASHBOARD_PORT"] = "6001"
        self.assertEqual(dashboard._resolve_port(), 6001)

    def test_resolve_port_invalid_env_falls_back(self):
        os.environ["SATIN_DASHBOARD_PORT"] = "not-a-number"
        self.assertEqual(dashboard._resolve_port(), 5003)

    def test_launcher_uses_shared_default(self):
        """satin_launcher._launch_dashboard with no explicit port must resolve to
        the dashboard module's default (5003), not a hardcoded 5000."""
        import importlib
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if root not in sys.path:
            sys.path.insert(0, root)
        launcher = importlib.import_module("satin_launcher")

        captured = {}

        class _FakeApp:
            def run(self, host=None, port=None, debug=None):
                captured["host"] = host
                captured["port"] = port

        import unittest.mock as mock
        with mock.patch.object(dashboard, "app", _FakeApp()):
            launcher._launch_dashboard(host="127.0.0.1", port=None)
        self.assertEqual(captured["port"], 5003)


if __name__ == "__main__":
    unittest.main()
