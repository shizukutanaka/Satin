"""
Tests for main/log_retention.py — time-based retention for the conversation log.

Satin's privacy story was complete except along the time axis. The log is
rotated at 5 MB × 5 generations, but that is a *size* cap — disk hygiene, not
storage limitation. Someone who chats occasionally kept every disclosure they
ever made, indefinitely, and the only controls were all-or-nothing
(`/clear-log`, `/forget-all`, `data purge`): keep everything forever, or lose
the whole relationship.

GDPR Art. 5(1)(e) (storage limitation) and the retention half of data
minimisation (NIST Privacy Framework CT.DM / PR.DS) both ask for a bounded
period derived from the purpose. This module supplies that bound.

The safety properties matter more than the feature here, so they are what these
tests mostly pin down:
  - the default is unchanged behaviour (0 = keep forever); upgrading must never
    silently delete someone's history;
  - a line whose timestamp cannot be read is never treated as old;
  - the live log is rewritten atomically and stays 0600;
  - an archive is only deleted when its rotation stamp predates the cutoff.

Stdlib-only; no GUI/network. Run: python -m unittest tests.test_log_retention -v
"""
import gzip
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MAIN = os.path.join(_ROOT, "main")
sys.path.insert(0, _MAIN)

import log_retention as lr  # noqa: E402

_DAY = 86400.0


class _LogBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.log = os.path.join(self._tmp, "ev.jsonl")
        self.now = time.time()

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write(self, entries):
        with open(self.log, "w", encoding="utf-8") as fh:
            for entry in entries:
                if isinstance(entry, str):
                    fh.write(entry + "\n")
                else:
                    fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _event(self, days_ago, text="hi"):
        return {"timestamp": self.now - days_ago * _DAY,
                "event_type": "user_comment", "details": {"text": text}}

    def _lines(self):
        with open(self.log, encoding="utf-8") as fh:
            return [line for line in fh.read().splitlines() if line.strip()]

    def _archive(self, days_ago):
        stamp = time.strftime("%Y%m%d_%H%M%S",
                              time.localtime(self.now - days_ago * _DAY))
        path = f"{self.log}.{stamp}.gz"
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            fh.write(json.dumps({"timestamp": self.now - days_ago * _DAY}) + "\n")
        return path


class TestDefaultsAreSafe(_LogBase):
    def test_default_is_keep_forever(self):
        self.assertEqual(lr.DEFAULT_RETENTION_DAYS, 0)

    def test_zero_days_is_a_no_op(self):
        self._write([self._event(9999), self._event(0)])
        result = lr.prune_conversation_log(logfile=self.log, days=0, now=self.now)
        self.assertFalse(result["pruned"])
        self.assertEqual(result["removed"], 0)
        self.assertEqual(len(self._lines()), 2)

    def test_negative_days_is_a_no_op(self):
        self._write([self._event(9999)])
        result = lr.prune_conversation_log(logfile=self.log, days=-30, now=self.now)
        self.assertFalse(result["pruned"])
        self.assertEqual(len(self._lines()), 1)

    def test_missing_file_is_not_an_error(self):
        result = lr.prune_conversation_log(
            logfile=os.path.join(self._tmp, "nope.jsonl"), days=30, now=self.now)
        self.assertEqual(result["removed"], 0)

    def test_cutoff_timestamp(self):
        self.assertEqual(lr.cutoff_timestamp(0), 0.0)
        self.assertEqual(lr.cutoff_timestamp(-1), 0.0)
        self.assertAlmostEqual(lr.cutoff_timestamp(30, now=1_000_000.0),
                               1_000_000.0 - 30 * _DAY)


class TestPruning(_LogBase):
    def test_only_events_older_than_the_window_go(self):
        self._write([self._event(200, "very old"), self._event(100, "old"),
                     self._event(10, "recent"), self._event(0, "now")])
        result = lr.prune_conversation_log(logfile=self.log, days=90, now=self.now)
        self.assertEqual(result["removed"], 2)
        self.assertEqual(result["kept"], 2)
        kept = "\n".join(self._lines())
        self.assertIn("recent", kept)
        self.assertIn("now", kept)
        self.assertNotIn("very old", kept)

    def test_boundary_event_is_kept(self):
        """Exactly at the cutoff is inside the window."""
        self._write([{"timestamp": self.now - 90 * _DAY, "details": {"text": "edge"}}])
        lr.prune_conversation_log(logfile=self.log, days=90, now=self.now)
        self.assertIn("edge", "\n".join(self._lines()))

    def test_undated_lines_are_never_removed(self):
        """If we cannot read a timestamp we must not decide it is old."""
        self._write([self._event(500), {"event_type": "no_timestamp", "details": {}},
                     {"timestamp": "not-a-number", "details": {}}])
        lr.prune_conversation_log(logfile=self.log, days=30, now=self.now)
        kept = "\n".join(self._lines())
        self.assertIn("no_timestamp", kept)
        self.assertIn("not-a-number", kept)

    def test_unparseable_lines_are_never_removed(self):
        self._write([self._event(500), "this is not json"])
        lr.prune_conversation_log(logfile=self.log, days=30, now=self.now)
        self.assertIn("this is not json", self._lines())

    def test_nothing_old_leaves_the_file_untouched(self):
        self._write([self._event(1), self._event(2)])
        before = open(self.log, encoding="utf-8").read()
        result = lr.prune_conversation_log(logfile=self.log, days=90, now=self.now)
        self.assertFalse(result["pruned"])
        self.assertEqual(open(self.log, encoding="utf-8").read(), before)

    def test_removing_everything_leaves_a_valid_empty_file(self):
        self._write([self._event(500), self._event(400)])
        lr.prune_conversation_log(logfile=self.log, days=30, now=self.now)
        self.assertTrue(os.path.exists(self.log))
        self.assertEqual(self._lines(), [])

    @unittest.skipIf(os.name == "nt", "POSIX permission bits only")
    def test_rewritten_log_stays_owner_only(self):
        self._write([self._event(500), self._event(1)])
        lr.prune_conversation_log(logfile=self.log, days=30, now=self.now)
        self.assertEqual(os.stat(self.log).st_mode & 0o777, 0o600)

    def test_surviving_lines_are_still_valid_jsonl(self):
        self._write([self._event(500), self._event(1, "keep me")])
        lr.prune_conversation_log(logfile=self.log, days=30, now=self.now)
        for line in self._lines():
            json.loads(line)  # must not raise


class TestArchives(_LogBase):
    def test_archive_older_than_the_cutoff_is_deleted(self):
        self._write([self._event(1)])
        old = self._archive(200)
        result = lr.prune_conversation_log(logfile=self.log, days=90, now=self.now)
        self.assertEqual(result["archives_removed"], 1)
        self.assertFalse(os.path.exists(old))

    def test_archive_inside_the_window_is_kept(self):
        self._write([self._event(1)])
        recent = self._archive(5)
        lr.prune_conversation_log(logfile=self.log, days=90, now=self.now)
        self.assertTrue(os.path.exists(recent))

    def test_unstamped_archive_is_kept(self):
        """A filename we cannot date is not evidence that it is old."""
        self._write([self._event(1)])
        odd = self.log + ".backup.gz"
        with gzip.open(odd, "wt", encoding="utf-8") as fh:
            fh.write("{}\n")
        lr.prune_conversation_log(logfile=self.log, days=1, now=self.now)
        self.assertTrue(os.path.exists(odd))

    def test_other_logs_archives_are_untouched(self):
        self._write([self._event(1)])
        stamp = time.strftime("%Y%m%d_%H%M%S",
                              time.localtime(self.now - 200 * _DAY))
        other = os.path.join(self._tmp, f"other.jsonl.{stamp}.gz")
        with gzip.open(other, "wt", encoding="utf-8") as fh:
            fh.write("{}\n")
        lr.prune_conversation_log(logfile=self.log, days=90, now=self.now)
        self.assertTrue(os.path.exists(other))

    def test_archive_epoch_parsing(self):
        self.assertIsNone(lr._archive_epoch("ev.jsonl.gz"))
        self.assertIsNone(lr._archive_epoch("ev.jsonl.99999999_999999.gz"))
        self.assertEqual(
            lr._archive_epoch("ev.jsonl.20240102_030405.gz"),
            time.mktime(time.strptime("20240102_030405", "%Y%m%d_%H%M%S")),
        )


class TestConfiguredRetentionDays(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.cfg = os.path.join(self._tmp, "config.json")

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write(self, data):
        with open(self.cfg, "w", encoding="utf-8") as fh:
            json.dump(data, fh)

    def test_reads_the_setting(self):
        self._write({"settings": {lr.CONFIG_KEY: 90}})
        self.assertEqual(lr.configured_retention_days(self.cfg), 90)

    def test_absent_setting_means_forever(self):
        self._write({"settings": {"language": "ja"}})
        self.assertEqual(lr.configured_retention_days(self.cfg), 0)

    def test_missing_file_means_forever(self):
        self.assertEqual(
            lr.configured_retention_days(os.path.join(self._tmp, "nope.json")), 0)

    def test_broken_config_means_forever(self):
        """A config we cannot parse must never authorise deletion."""
        with open(self.cfg, "w", encoding="utf-8") as fh:
            fh.write("{ not json")
        self.assertEqual(lr.configured_retention_days(self.cfg), 0)

    def test_non_numeric_setting_means_forever(self):
        self._write({"settings": {lr.CONFIG_KEY: "ninety"}})
        self.assertEqual(lr.configured_retention_days(self.cfg), 0)

    def test_negative_setting_means_forever(self):
        self._write({"settings": {lr.CONFIG_KEY: -5}})
        self.assertEqual(lr.configured_retention_days(self.cfg), 0)

    def test_shipped_config_keeps_everything_by_default(self):
        """The default install must not delete anything."""
        shipped = os.path.join(_ROOT, "config", "config.json")
        self.assertEqual(lr.configured_retention_days(shipped), 0)


class TestApplyRetentionIfConfigured(_LogBase):
    def setUp(self):
        super().setUp()
        self.cfg = os.path.join(self._tmp, "config.json")

    def _config(self, days):
        with open(self.cfg, "w", encoding="utf-8") as fh:
            json.dump({"settings": {lr.CONFIG_KEY: days}}, fh)

    def test_no_setting_means_no_change(self):
        self._config(0)
        self._write([self._event(9999)])
        result = lr.apply_retention_if_configured(logfile=self.log,
                                                  config_path=self.cfg)
        self.assertFalse(result["pruned"])
        self.assertEqual(len(self._lines()), 1)

    def test_setting_is_applied(self):
        self._config(30)
        self._write([self._event(500), self._event(1)])
        result = lr.apply_retention_if_configured(logfile=self.log,
                                                  config_path=self.cfg)
        self.assertTrue(result["pruned"])
        self.assertEqual(result["removed"], 1)
        self.assertEqual(len(self._lines()), 1)


class TestManageCli(_LogBase):
    """`manage_satin log prune` — the on-demand entry point."""

    def _run(self, **kw):
        import manage_satin
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = manage_satin.cmd_log_prune(log_path=self.log, **kw)
        return code, buf.getvalue()

    def test_dry_run_reports_without_deleting(self):
        self._write([self._event(500), self._event(1)])
        code, out = self._run(days=30, dry_run=True)
        self.assertEqual(code, 0)
        self.assertIn("DRY-RUN", out)
        self.assertIn("1 件", out)
        self.assertEqual(len(self._lines()), 2)

    def test_prune_deletes_and_reports(self):
        self._write([self._event(500), self._event(1)])
        code, out = self._run(days=30)
        self.assertEqual(code, 0)
        self.assertIn("30 日", out)
        self.assertEqual(len(self._lines()), 1)

    def test_without_days_or_config_it_refuses_to_guess(self):
        self._write([self._event(500)])
        code, out = self._run()
        self.assertEqual(code, 0)
        self.assertIn("無期限", out)
        self.assertEqual(len(self._lines()), 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
