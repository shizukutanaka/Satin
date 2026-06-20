"""
Tests for avatar_event_logger.AvatarEventLogger.

Covers: log_event writes valid JSON lines, replay_events calls the
callback in chronological order at the right inter-event spacing,
empty-file replay is a no-op, and concurrent log_event calls are
thread-safe.

Run: python -m unittest tests.test_avatar_event_logger -v
"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from avatar_event_logger import AvatarEventLogger  # noqa: E402


class AvatarEventLoggerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._logfile = os.path.join(self._tmp, "events.jsonl")
        self.logger = AvatarEventLogger(logfile=self._logfile)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    # log_event
    # ------------------------------------------------------------------

    def test_log_event_writes_valid_json(self):
        self.logger.log_event("move", x=1.0, y=0.5)
        with open(self._logfile, encoding="utf-8") as f:
            lines = [l for l in f if l.strip()]
        self.assertEqual(len(lines), 1)
        ev = json.loads(lines[0])
        self.assertEqual(ev["event_type"], "move")
        self.assertAlmostEqual(ev["details"]["x"], 1.0)
        self.assertIn("timestamp", ev)

    def test_log_event_multiple_entries(self):
        for i in range(5):
            self.logger.log_event("tick", n=i)
        with open(self._logfile, encoding="utf-8") as f:
            lines = [l for l in f if l.strip()]
        self.assertEqual(len(lines), 5)
        for i, line in enumerate(lines):
            ev = json.loads(line)
            self.assertEqual(ev["details"]["n"], i)

    def test_log_event_thread_safe(self):
        errors = []
        def writer():
            for _ in range(50):
                try:
                    self.logger.log_event("ping")
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=writer) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], msg=f"Errors during concurrent log_event: {errors}")

        with open(self._logfile, encoding="utf-8") as f:
            lines = [l for l in f if l.strip()]
        self.assertEqual(len(lines), 200)
        for line in lines:
            json.loads(line)  # must be valid JSON

    # ------------------------------------------------------------------
    # replay_events
    # ------------------------------------------------------------------

    def test_replay_empty_file_is_noop(self):
        # Create an empty logfile
        open(self._logfile, "w").close()
        called = []
        self.logger.replay_events(lambda ev: called.append(ev), delay_factor=0.0)
        self.assertEqual(called, [])

    def test_replay_missing_file_is_noop(self):
        """replay_events() on a logfile that doesn't exist must not raise."""
        import os
        import tempfile
        nonexistent = os.path.join(tempfile.mkdtemp(), "no_such_file.jsonl")
        logger = AvatarEventLogger(logfile=nonexistent)
        called = []
        logger.replay_events(lambda ev: called.append(ev), delay_factor=0.0)
        self.assertEqual(called, [])

    def test_replay_calls_callback_for_each_event(self):
        for i in range(3):
            self.logger.log_event("step", i=i)
        received = []
        self.logger.replay_events(lambda ev: received.append(ev), delay_factor=0.0)
        self.assertEqual(len(received), 3)
        for i, ev in enumerate(received):
            self.assertEqual(ev["details"]["i"], i)

    def test_replay_respects_delay_factor_zero(self):
        """delay_factor=0 should skip sleep and return quickly."""
        t0 = time.monotonic()
        for _ in range(3):
            self.logger.log_event("beat")
        self.logger.replay_events(lambda ev: None, delay_factor=0.0)
        elapsed = time.monotonic() - t0
        self.assertLess(elapsed, 1.0, "replay with delay_factor=0 should be instant")

    def test_replay_events_in_timestamp_order(self):
        """Events must be replayed in the order they were logged."""
        events = ["a", "b", "c", "d"]
        for name in events:
            self.logger.log_event(name)
        received_types = []
        self.logger.replay_events(
            lambda ev: received_types.append(ev["event_type"]),
            delay_factor=0.0
        )
        self.assertEqual(received_types, events)

    def test_replay_skips_malformed_lines(self):
        """A corrupted/truncated line (e.g. from a crash mid-write) must be
        skipped, not crash the whole replay."""
        self.logger.log_event("good1")
        # Append a broken line directly, then another valid event.
        with open(self._logfile, "a", encoding="utf-8") as f:
            f.write("{not valid json\n")
        self.logger.log_event("good2")

        received = []
        # Must not raise json.JSONDecodeError.
        self.logger.replay_events(lambda ev: received.append(ev["event_type"]),
                                  delay_factor=0.0)
        self.assertEqual(received, ["good1", "good2"])

    def test_replay_event_missing_timestamp_does_not_crash(self):
        """Valid JSON line without 'timestamp' key must not raise KeyError."""
        self.logger.log_event("before")
        with open(self._logfile, "a", encoding="utf-8") as f:
            f.write('{"event_type": "no_ts", "details": {}}\n')
        self.logger.log_event("after")
        received = []
        self.logger.replay_events(lambda ev: received.append(ev["event_type"]),
                                  delay_factor=0.0)
        self.assertEqual(received, ["before", "no_ts", "after"])


class LogRotationTests(unittest.TestCase):
    """The write path must self-cap the log so a long-running companion does not
    grow avatar_event_log.jsonl without bound (and slow every reader)."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._logfile = os.path.join(self._tmp, "events.jsonl")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_log_is_capped_at_max_size(self):
        logger = AvatarEventLogger(self._logfile, max_size=2000, max_backups=3)
        for i in range(300):
            logger.log_event("speak", text="x" * 60, i=i)
        # File stays near the cap rather than growing with all 300 events.
        self.assertLessEqual(os.path.getsize(self._logfile), 2000 + 500)

    def test_rotation_creates_gz_backup(self):
        import glob
        logger = AvatarEventLogger(self._logfile, max_size=1500, max_backups=3)
        for i in range(100):
            logger.log_event("speak", text="y" * 60, i=i)
        self.assertGreaterEqual(len(glob.glob(self._logfile + ".*.gz")), 1)

    def test_logging_works_after_rotation(self):
        logger = AvatarEventLogger(self._logfile, max_size=1500, max_backups=3)
        for i in range(100):
            logger.log_event("speak", text="z" * 60, i=i)
        logger.log_event("speak", text="final_marker")
        with open(self._logfile, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("final_marker", content)

    def test_max_size_zero_disables_rotation(self):
        import glob
        logger = AvatarEventLogger(self._logfile, max_size=0)
        for i in range(200):
            logger.log_event("speak", text="w" * 60, i=i)
        # No rotation: all events retained, no gz backups.
        self.assertEqual(glob.glob(self._logfile + ".*.gz"), [])
        with open(self._logfile, encoding="utf-8") as f:
            self.assertEqual(len([l for l in f if l.strip()]), 200)

    def test_rotation_failure_does_not_break_logging(self):
        from unittest import mock
        logger = AvatarEventLogger(self._logfile, max_size=100)
        with mock.patch("avatar_event_log_rotate.rotate_log",
                        side_effect=OSError("boom")):
            # Must not raise even though rotation fails.
            logger.log_event("speak", text="still logged")
        with open(self._logfile, encoding="utf-8") as f:
            self.assertIn("still logged", f.read())

    def test_rotated_archive_is_owner_only(self):
        """The .gz archive created by rotation must inherit the live file's
        0o600 permission — conversation data must not be world-readable."""
        import glob
        import stat
        logger = AvatarEventLogger(self._logfile, max_size=1500, max_backups=3)
        for i in range(100):
            logger.log_event("speak", text="priv" * 20, i=i)
        archives = glob.glob(self._logfile + ".*.gz")
        self.assertGreaterEqual(len(archives), 1,
                                "Expected at least one archive after rotation")
        for gz in archives:
            mode = stat.S_IMODE(os.stat(gz).st_mode)
            self.assertEqual(mode & 0o077, 0,
                             f"{gz} must not be group/other readable")


class LogPrivacyTests(unittest.TestCase):
    """The conversation log holds private user content; it must not be created
    world-readable."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._logfile = os.path.join(self._tmp, "conv.jsonl")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_log_is_owner_only(self):
        import stat
        AvatarEventLogger(self._logfile).log_event(
            "user_comment", text="my private secret"
        )
        mode = stat.S_IMODE(os.stat(self._logfile).st_mode)
        self.assertEqual(mode & 0o077, 0, "conversation log must not be group/other readable")


if __name__ == "__main__":
    unittest.main()
