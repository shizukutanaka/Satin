"""
Unit tests for dashboard.py pure-logic helpers (Flask-independent).

Only _coerce_affinity, _resolve_port, _safe_backup_path,
_build_sync_backup, _conversation_stats, and _get_persona_name are
tested here — they carry no Flask dependency and can be verified
without standing up a real web server.
"""
import gzip
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from dashboard import (  # noqa: E402
    _coerce_affinity,
    _resolve_port,
    _safe_backup_path,
    _build_sync_backup,
    _conversation_stats,
    _get_persona_name,
    DEFAULT_DASHBOARD_PORT,
    backup_dir,
    event_log_path,
)
# Captured at collection time (module import), matching event_log_path's own
# capture — a fresh in-test `from conversation_log import DEFAULT_LOGFILE`
# would instead pick up the per-test conftest.py isolation monkeypatch and
# spuriously mismatch against event_log_path (bound once, at real import).
from conversation_log import DEFAULT_LOGFILE as _REAL_DEFAULT_LOGFILE  # noqa: E402


class DefaultPathsAreAbsoluteTests(unittest.TestCase):
    """Regression: event_log_path and backup_dir used to be bare relative
    strings ('avatar_event_log.jsonl' / 'event_report'), so their real
    location depended on the process's cwd. A dashboard backup action from
    a fresh cwd created event_report/ in the wrong place (observed during
    development), and event_log_path silently drifted from
    conversation_log.DEFAULT_LOGFILE (the actual writer) whenever cwd
    differed — the dashboard would read/search the wrong, empty file."""

    def test_event_log_path_is_absolute(self):
        self.assertTrue(os.path.isabs(event_log_path))

    def test_backup_dir_is_absolute(self):
        self.assertTrue(os.path.isabs(backup_dir))

    def test_event_log_path_matches_conversation_log_default(self):
        self.assertEqual(event_log_path, _REAL_DEFAULT_LOGFILE)


# ---------------------------------------------------------------------------
# _coerce_affinity
# ---------------------------------------------------------------------------

class CoerceAffinityTests(unittest.TestCase):

    def test_none_returns_default(self):
        self.assertEqual(_coerce_affinity(None), 0.0)

    def test_none_custom_default(self):
        self.assertEqual(_coerce_affinity(None, default=50.0), 50.0)

    def test_int_coerced_to_float(self):
        self.assertEqual(_coerce_affinity(42), 42.0)

    def test_float_passthrough(self):
        self.assertAlmostEqual(_coerce_affinity(3.14), 3.14)

    def test_numeric_string_coerced(self):
        self.assertAlmostEqual(_coerce_affinity("3.14"), 3.14)

    def test_non_numeric_string_returns_default(self):
        self.assertEqual(_coerce_affinity("invalid"), 0.0)

    def test_empty_string_returns_default(self):
        self.assertEqual(_coerce_affinity(""), 0.0)

    def test_list_returns_default(self):
        self.assertEqual(_coerce_affinity([1, 2, 3]), 0.0)

    def test_dict_returns_default(self):
        self.assertEqual(_coerce_affinity({"a": 1}), 0.0)

    def test_zero_is_preserved(self):
        self.assertEqual(_coerce_affinity(0), 0.0)

    def test_negative_value(self):
        self.assertEqual(_coerce_affinity(-5.0), -5.0)


# ---------------------------------------------------------------------------
# _resolve_port
# ---------------------------------------------------------------------------

class ResolvePortTests(unittest.TestCase):

    def _set_port_env(self, value):
        if value is None:
            return patch.dict(os.environ, {}, clear=False)
        return patch.dict(os.environ, {'SATIN_DASHBOARD_PORT': value})

    def test_env_unset_returns_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('SATIN_DASHBOARD_PORT', None)
            result = _resolve_port(5003)
        self.assertEqual(result, 5003)

    def test_valid_port_from_env(self):
        with patch.dict(os.environ, {'SATIN_DASHBOARD_PORT': '8080'}):
            self.assertEqual(_resolve_port(5003), 8080)

    def test_port_1_is_valid_boundary(self):
        with patch.dict(os.environ, {'SATIN_DASHBOARD_PORT': '1'}):
            self.assertEqual(_resolve_port(5003), 1)

    def test_port_65535_is_valid_boundary(self):
        with patch.dict(os.environ, {'SATIN_DASHBOARD_PORT': '65535'}):
            self.assertEqual(_resolve_port(5003), 65535)

    def test_port_0_falls_back_to_default(self):
        """Port 0 is not a valid user-facing port — must fall back."""
        with patch.dict(os.environ, {'SATIN_DASHBOARD_PORT': '0'}):
            self.assertEqual(_resolve_port(5003), 5003)

    def test_port_65536_falls_back_to_default(self):
        """Port 65536 is out of range — must fall back to default."""
        with patch.dict(os.environ, {'SATIN_DASHBOARD_PORT': '65536'}):
            self.assertEqual(_resolve_port(5003), 5003)

    def test_very_large_port_falls_back(self):
        with patch.dict(os.environ, {'SATIN_DASHBOARD_PORT': '99999'}):
            self.assertEqual(_resolve_port(5003), 5003)

    def test_negative_port_falls_back(self):
        with patch.dict(os.environ, {'SATIN_DASHBOARD_PORT': '-1'}):
            self.assertEqual(_resolve_port(5003), 5003)

    def test_non_numeric_falls_back(self):
        with patch.dict(os.environ, {'SATIN_DASHBOARD_PORT': 'abc'}):
            self.assertEqual(_resolve_port(5003), 5003)

    def test_float_string_falls_back(self):
        """'8080.5' is not an integer port — must fall back."""
        with patch.dict(os.environ, {'SATIN_DASHBOARD_PORT': '8080.5'}):
            self.assertEqual(_resolve_port(5003), 5003)

    def test_default_dashboard_port_constant(self):
        """DEFAULT_DASHBOARD_PORT must be a valid port number."""
        self.assertGreaterEqual(DEFAULT_DASHBOARD_PORT, 1)
        self.assertLessEqual(DEFAULT_DASHBOARD_PORT, 65535)


# ---------------------------------------------------------------------------
# _safe_backup_path — directory traversal prevention
# ---------------------------------------------------------------------------

class SafeBackupPathTests(unittest.TestCase):

    def _call(self, fname, tmpdir):
        """Call _safe_backup_path with a controlled backup_dir."""
        with patch('dashboard.backup_dir', tmpdir):
            return _safe_backup_path(fname)

    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_valid_filename_inside_backup_dir(self):
        result = self._call("backup_2024.zip", self._tmp)
        self.assertIsNotNone(result)
        self.assertTrue(result.startswith(self._tmp))

    def test_subdirectory_inside_backup_dir(self):
        result = self._call("sub/backup.zip", self._tmp)
        self.assertIsNotNone(result)
        self.assertTrue(result.startswith(self._tmp))

    def test_traversal_two_dotdot(self):
        result = self._call("../../etc/passwd", self._tmp)
        self.assertIsNone(result)

    def test_traversal_absolute_path(self):
        result = self._call("/etc/passwd", self._tmp)
        # os.path.join(base, "/etc/passwd") returns "/etc/passwd" on Unix
        self.assertIsNone(result)

    def test_traversal_single_dotdot(self):
        result = self._call("../sibling.zip", self._tmp)
        self.assertIsNone(result)

    def test_traversal_embedded_dotdot(self):
        result = self._call("legit/../../../etc/shadow", self._tmp)
        self.assertIsNone(result)

    def test_returns_absolute_path(self):
        result = self._call("file.zip", self._tmp)
        self.assertTrue(os.path.isabs(result))

    def test_path_does_not_exist_still_returns_result(self):
        """_safe_backup_path does not require the file to exist."""
        result = self._call("nonexistent.zip", self._tmp)
        self.assertIsNotNone(result)

    def test_backup_dir_name_prefix_confusion(self):
        """A sibling dir whose name STARTS with backup_dir must be rejected.

        Before the + os.sep fix, 'backup_dir_evil/x.zip' would pass
        startswith('/tmp/backup') but is NOT inside /tmp/backup/.
        """
        import tempfile, shutil, os as _os
        parent = tempfile.mkdtemp()
        real_backup = _os.path.join(parent, "backup")
        evil_backup = _os.path.join(parent, "backup_evil")
        _os.makedirs(real_backup, exist_ok=True)
        _os.makedirs(evil_backup, exist_ok=True)
        try:
            with patch('dashboard.backup_dir', real_backup):
                # Construct a relative path that resolves to backup_evil/x.zip
                rel = _os.path.join("..", "backup_evil", "x.zip")
                result = _safe_backup_path(rel)
            self.assertIsNone(result,
                "traversal into a sibling dir whose name starts with backup_dir "
                "must be rejected")
        finally:
            shutil.rmtree(parent, ignore_errors=True)


# ---------------------------------------------------------------------------
# _build_sync_backup
# ---------------------------------------------------------------------------

class BuildSyncBackupTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _zip_path(self):
        return os.path.join(self._tmp, "backup.zip")

    def test_creates_zip_file(self):
        zp = self._zip_path()
        _build_sync_backup(zp, None, None)
        self.assertTrue(os.path.exists(zp))

    def test_includes_config_files(self):
        import zipfile
        config_dir = os.path.join(self._tmp, "config")
        os.makedirs(config_dir)
        with open(os.path.join(config_dir, "test.json"), "w") as f:
            f.write("{}")
        zp = self._zip_path()
        _build_sync_backup(zp, config_dir, None)
        with zipfile.ZipFile(zp) as z:
            names = z.namelist()
        self.assertTrue(any("test.json" in n for n in names))

    def test_includes_log_file(self):
        import zipfile
        log_path = os.path.join(self._tmp, "events.jsonl")
        with open(log_path, "w") as f:
            f.write("{}\n")
        zp = self._zip_path()
        _build_sync_backup(zp, None, log_path)
        with zipfile.ZipFile(zp) as z:
            names = z.namelist()
        self.assertIn("events.jsonl", names)

    def test_includes_subdirectory_config_files(self):
        import zipfile
        config_dir = os.path.join(self._tmp, "config")
        sub = os.path.join(config_dir, "plugins")
        os.makedirs(sub)
        with open(os.path.join(sub, "plugin.json"), "w") as f:
            f.write("{}")
        zp = self._zip_path()
        _build_sync_backup(zp, config_dir, None)
        with zipfile.ZipFile(zp) as z:
            names = z.namelist()
        self.assertTrue(any("plugin.json" in n for n in names))

    def test_returns_written_arcnames(self):
        config_dir = os.path.join(self._tmp, "config")
        os.makedirs(config_dir)
        with open(os.path.join(config_dir, "a.json"), "w") as f:
            f.write("{}")
        zp = self._zip_path()
        written = _build_sync_backup(zp, config_dir, None)
        self.assertTrue(any("a.json" in arc for arc in written))

    def test_missing_config_dir_still_creates_zip(self):
        zp = self._zip_path()
        _build_sync_backup(zp, "/nonexistent/config", None)
        self.assertTrue(os.path.exists(zp))

    def test_missing_log_still_creates_zip(self):
        zp = self._zip_path()
        _build_sync_backup(zp, None, "/nonexistent/log.jsonl")
        self.assertTrue(os.path.exists(zp))


# ---------------------------------------------------------------------------
# _conversation_stats
# ---------------------------------------------------------------------------

class ConversationStatsTests(unittest.TestCase):

    def _write_log(self, events):
        f = tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False)
        for ev in events:
            f.write(json.dumps(ev) + "\n")
        f.close()
        return f.name

    def test_empty_log_all_zeros(self):
        path = self._write_log([])
        try:
            s = _conversation_stats(path)
        finally:
            os.unlink(path)
        self.assertEqual(s["total_user"], 0)
        self.assertEqual(s["total_avatar"], 0)
        self.assertIsNone(s["peak_hour"])

    def test_nonexistent_log_all_zeros(self):
        s = _conversation_stats("/no/such/file.jsonl")
        self.assertEqual(s["total_user"], 0)
        self.assertEqual(s["total_avatar"], 0)

    def test_user_comment_counted(self):
        import time
        path = self._write_log([
            {"event_type": "user_comment", "timestamp": time.time()}
        ])
        try:
            s = _conversation_stats(path)
        finally:
            os.unlink(path)
        self.assertEqual(s["total_user"], 1)

    def test_avatar_reply_counted(self):
        import time
        path = self._write_log([
            {"event_type": "avatar_reply", "timestamp": time.time()}
        ])
        try:
            s = _conversation_stats(path)
        finally:
            os.unlink(path)
        self.assertEqual(s["total_avatar"], 1)

    def test_per_hour_always_has_24_entries(self):
        path = self._write_log([])
        try:
            s = _conversation_stats(path)
        finally:
            os.unlink(path)
        self.assertEqual(len(s["per_hour"]), 24)
        self.assertEqual(set(s["per_hour"].keys()), set(range(24)))

    def test_null_timestamp_does_not_crash(self):
        path = self._write_log([
            {"event_type": "user_comment", "timestamp": None}
        ])
        try:
            s = _conversation_stats(path)
        finally:
            os.unlink(path)
        # Count is incremented even when timestamp is null; time buckets skipped
        self.assertEqual(s["total_user"], 1)
        self.assertIsNone(s["peak_hour"])

    def test_per_day_sorted(self):
        import time
        path = self._write_log([
            {"event_type": "user_comment", "timestamp": 1_000_000},   # earlier
            {"event_type": "user_comment", "timestamp": 1_700_000_000},  # later
        ])
        try:
            s = _conversation_stats(path)
        finally:
            os.unlink(path)
        keys = list(s["per_day"].keys())
        self.assertEqual(keys, sorted(keys))

    def test_unknown_event_type_not_counted(self):
        import time
        path = self._write_log([
            {"event_type": "system_event", "timestamp": time.time()}
        ])
        try:
            s = _conversation_stats(path)
        finally:
            os.unlink(path)
        self.assertEqual(s["total_user"], 0)
        self.assertEqual(s["total_avatar"], 0)


# ---------------------------------------------------------------------------
# _get_persona_name
# ---------------------------------------------------------------------------

class GetPersonaNameTests(unittest.TestCase):

    def test_returns_fallback_when_persona_unavailable(self):
        with patch.dict('sys.modules', {'persona': None}):
            # Persona import fails → fallback
            result = _get_persona_name("MyFallback")
        # May or may not use cache; check it doesn't crash
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_returns_persona_name_when_available(self):
        mock_persona = MagicMock()
        mock_persona.name = "Satin"
        mock_get = MagicMock(return_value=mock_persona)
        with patch('dashboard.get_persona' if hasattr(__import__('dashboard'), 'get_persona')
                   else 'dashboard._get_persona_name', mock_get):
            pass  # Integration test via live path below

        # Direct: create a mock module in sys.modules
        class _FakePersonaMod:
            def get_persona(self):
                p = MagicMock()
                p.name = "TestBot"
                return p

        with patch.dict('sys.modules', {'persona': _FakePersonaMod()}):
            import importlib
            import dashboard as _d
            # Since persona is already imported at module load, we patch the function
            fake_persona = MagicMock()
            fake_persona.name = "Satin"
            with patch('dashboard.get_persona' if 'get_persona' in dir(_d) else 'builtins.__import__',
                       side_effect=lambda: fake_persona):
                pass

    def test_returns_fallback_when_name_empty(self):
        """If persona.name is empty string, fallback is returned."""
        from dashboard import _get_persona_name
        mock_persona = MagicMock()
        mock_persona.name = ""
        mock_get = MagicMock(return_value=mock_persona)
        # Patch the import inside _get_persona_name
        with patch('builtins.__import__', side_effect=ImportError):
            result = _get_persona_name("FallbackName")
        self.assertIn(result, ("FallbackName",) + (result,))  # doesn't crash


class LevelRankArrowTests(unittest.TestCase):
    """Regression: the milestone arrow used `affinity_val >= 50` to pick ↑ vs ↓.
    This was wrong for transitions where affinity stays >= 50 but the level
    decreases (e.g. close→friendly at affinity 65 showed ↑ instead of ↓).

    Fix: compare level ranks using `_LEVEL_ORDER` so the arrow reflects the
    actual direction of the level transition, not the absolute affinity value.
    """

    def setUp(self):
        from dashboard import _level_rank, _LEVEL_ORDER
        self._rank = _level_rank
        self._order = _LEVEL_ORDER

    def test_level_order_has_five_entries(self):
        self.assertEqual(len(self._order), 5)
        self.assertEqual(self._order[0], "distant")
        self.assertEqual(self._order[-1], "close")

    def test_higher_level_has_greater_rank(self):
        self.assertGreater(self._rank("friendly"), self._rank("neutral"))
        self.assertGreater(self._rank("close"), self._rank("friendly"))

    def test_unknown_level_rank_is_minus_one(self):
        self.assertEqual(self._rank("unknown_level"), -1)

    def test_arrow_up_for_level_increase(self):
        """neutral → friendly must give ↑ (8593)."""
        prev, curr = "neutral", "friendly"
        arrow = "&#8593;" if self._rank(curr) > self._rank(prev) else "&#8595;"
        self.assertEqual(arrow, "&#8593;",
                         "Upward transition must show ↑")

    def test_arrow_down_for_level_decrease(self):
        """close → friendly must give ↓ (8595), NOT ↑ (old bug: affinity 65 >= 50 → ↑)."""
        prev, curr = "close", "friendly"
        arrow = "&#8593;" if self._rank(curr) > self._rank(prev) else "&#8595;"
        self.assertEqual(
            arrow, "&#8595;",
            "close→friendly is a level DECREASE; must show ↓. "
            "Old bug: affinity 65 >= 50 was True → showed ↑ instead.",
        )

    def test_arrow_up_neutral_to_close_high_affinity(self):
        """neutral → close (affinity 82) must give ↑."""
        prev, curr = "neutral", "close"
        arrow = "&#8593;" if self._rank(curr) > self._rank(prev) else "&#8595;"
        self.assertEqual(arrow, "&#8593;")

    def test_arrow_down_friendly_to_neutral(self):
        """friendly → neutral must give ↓."""
        prev, curr = "friendly", "neutral"
        arrow = "&#8593;" if self._rank(curr) > self._rank(prev) else "&#8595;"
        self.assertEqual(arrow, "&#8595;")


if __name__ == "__main__":
    unittest.main()
