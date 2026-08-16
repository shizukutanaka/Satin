"""
Tests for main/usage_guardrails.py — the emotional-dependence safety guardrail.

usage_guardrails observes the INTENSITY of app usage (not mood) — late-night
activity and extreme single-day frequency — and, only when a genuinely
health-affecting pattern appears, produces a gentle nudge toward rest / real-
world connection. It stays silent (empty string) otherwise. This is the A1
item from the research-driven improvement list, motivated by 2025-2026
companion-app safety research (APA 2026, Princeton CITP 2025, arXiv:2506.12605):
a relationship-deepening companion app should not encourage unhealthy
emotional dependence.

Stdlib-only; no GUI/network. Run: python -m unittest tests.test_usage_guardrails -v
"""
import gzip
import importlib
import json
import os
import sys
import tempfile
import time
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import usage_guardrails as ug  # noqa: E402


class _LogBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._log = os.path.join(self._tmp, "ev.jsonl")
        # Pin "now" to 18:00 local today so tests are deterministic regardless
        # of the wall-clock hour the suite runs at. (If "now" fell in the
        # late-night 0:00-4:59 window, midday events clamped to now-1 would
        # themselves land in that window and trip the late_night concern
        # instead of the one under test.)
        _lt = time.localtime()
        self._now = time.mktime((_lt.tm_year, _lt.tm_mon, _lt.tm_mday, 18, 0, 0, 0, 0, -1))

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write(self, entries):
        with open(self._log, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

    def _user_event(self, ts, text="hi"):
        return {"event_type": "user_comment", "timestamp": ts, "details": {"text": text}}

    def _at_hour(self, hour, days_ago=0, minute_offset=0):
        """A local timestamp at `hour` on the day `days_ago` days before now."""
        base = self._now - days_ago * 86400
        lt = time.localtime(base)
        ts = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, hour, 0, 0, 0, 0, -1))
        return ts + minute_offset * 60


class ConcernDetectionTests(_LogBase):
    def test_empty_log_is_no_concern(self):
        self._write([])
        s = ug.usage_summary(event_log_path=self._log, now=self._now)
        self.assertEqual(s["concern"], "none")
        self.assertEqual(s["late_night_events"], 0)
        self.assertEqual(s["busiest_day_events"], 0)

    def test_light_daytime_use_is_no_concern(self):
        # A handful of afternoon messages over a few days — normal use.
        entries = []
        for d in range(3):
            for i in range(3):
                entries.append(self._user_event(self._at_hour(15, days_ago=d, minute_offset=i)))
        self._write(entries)
        s = ug.usage_summary(event_log_path=self._log, now=self._now)
        self.assertEqual(s["concern"], "none")

    def test_sustained_late_night_use_flags_late_night(self):
        # ~4 msgs/night at 2am across 5 recent nights = 20 late-night events.
        entries = []
        for d in range(5):
            two_am = self._at_hour(2, days_ago=d)
            if two_am > self._now:
                continue
            for i in range(4):
                entries.append(self._user_event(two_am + i * 60, "up late"))
        self._write(entries)
        s = ug.usage_summary(event_log_path=self._log, now=self._now)
        self.assertEqual(s["concern"], "late_night")
        self.assertGreaterEqual(s["late_night_events"], ug._LATE_NIGHT_MIN_EVENTS)

    def test_extreme_single_day_frequency_flags_high_frequency(self):
        # 120 messages in one afternoon, no late-night activity.
        entries = []
        noon = ug._start_of_day(self._now) + 12 * 3600
        for i in range(120):
            ts = noon + i * 10
            if ts > self._now:
                ts = self._now - 1
            entries.append(self._user_event(ts, "chat"))
        self._write(entries)
        s = ug.usage_summary(event_log_path=self._log, now=self._now)
        self.assertEqual(s["concern"], "high_frequency")
        self.assertGreaterEqual(s["busiest_day_events"], ug._HIGH_FREQUENCY_MIN_PER_DAY)

    def test_late_night_takes_priority_over_high_frequency(self):
        # Both patterns present: late-night must win (sleep impact is the
        # more direct wellbeing harm).
        entries = []
        for d in range(5):
            two_am = self._at_hour(2, days_ago=d)
            if two_am > self._now:
                continue
            for i in range(4):
                entries.append(self._user_event(two_am + i * 60, "up late"))
        noon = ug._start_of_day(self._now) + 12 * 3600
        for i in range(120):
            ts = noon + i * 10
            if ts > self._now:
                ts = self._now - 1
            entries.append(self._user_event(ts, "chat"))
        self._write(entries)
        s = ug.usage_summary(event_log_path=self._log, now=self._now)
        self.assertEqual(s["concern"], "late_night")

    def test_avatar_messages_do_not_count(self):
        # Only USER events count toward usage intensity.
        entries = []
        for d in range(5):
            two_am = self._at_hour(2, days_ago=d)
            if two_am > self._now:
                continue
            for i in range(4):
                entries.append({"event_type": "avatar_reply", "timestamp": two_am + i * 60,
                                "details": {"text": "up late"}})
        self._write(entries)
        s = ug.usage_summary(event_log_path=self._log, now=self._now)
        self.assertEqual(s["late_night_events"], 0)
        self.assertEqual(s["concern"], "none")

    def test_events_outside_window_excluded(self):
        # Late-night events from 30 days ago must not count in a 7-day window.
        entries = []
        for i in range(20):
            entries.append(self._user_event(self._at_hour(2, days_ago=30, minute_offset=i), "old"))
        self._write(entries)
        s = ug.usage_summary(event_log_path=self._log, days=7, now=self._now)
        self.assertEqual(s["concern"], "none")

    def test_missing_log_is_no_concern(self):
        s = ug.usage_summary(event_log_path="/no/such/file.jsonl", now=self._now)
        self.assertEqual(s["concern"], "none")

    def test_malformed_lines_are_skipped(self):
        with open(self._log, "w", encoding="utf-8") as f:
            f.write("not json\n")
            f.write("null\n")
            f.write(json.dumps(self._user_event(self._at_hour(15))) + "\n")
        # Must not raise.
        s = ug.usage_summary(event_log_path=self._log, now=self._now)
        self.assertEqual(s["concern"], "none")


class ArchiveTests(_LogBase):
    """Rotated .gz archives must be included (mirrors the user_wellbeing fix)."""

    def test_late_night_events_in_archive_are_counted(self):
        # Live file empty; all late-night events live in a rotated archive.
        open(self._log, "w").close()
        gz_name = os.path.basename(self._log) + ".20260101_000000.gz"
        gz_path = os.path.join(self._tmp, gz_name)
        with gzip.open(gz_path, "wt", encoding="utf-8") as fh:
            for d in range(5):
                two_am = self._at_hour(2, days_ago=d)
                if two_am > self._now:
                    continue
                for i in range(4):
                    fh.write(json.dumps(self._user_event(two_am + i * 60, "up late")) + "\n")
        s = ug.usage_summary(event_log_path=self._log, now=self._now)
        self.assertEqual(s["concern"], "late_night")


class NudgeMessageTests(_LogBase):
    def test_none_concern_returns_empty(self):
        self.assertEqual(ug.usage_nudge({"concern": "none"}), "")
        self.assertEqual(ug.usage_nudge({}), "")
        self.assertEqual(ug.usage_nudge(None), "")

    def test_late_night_nudge_is_nonempty_and_gentle(self):
        msg = ug.usage_nudge({"concern": "late_night"}, lang="ja")
        self.assertTrue(msg)
        self.assertIn(msg, ug._NUDGE_MESSAGES["late_night"]["ja"])

    def test_high_frequency_nudge_english(self):
        msg = ug.usage_nudge({"concern": "high_frequency"}, lang="en")
        self.assertTrue(msg)
        self.assertIn(msg, ug._NUDGE_MESSAGES["high_frequency"]["en"])

    def test_unknown_lang_falls_back_to_english(self):
        msg = ug.usage_nudge({"concern": "late_night"}, lang="fr")
        self.assertIn(msg, ug._NUDGE_MESSAGES["late_night"]["en"])

    def test_reflection_end_to_end_silent_when_normal(self):
        self._write([self._user_event(self._at_hour(15))])
        self.assertEqual(ug.usage_reflection(event_log_path=self._log, now=self._now), "")

    def test_reflection_end_to_end_speaks_on_late_night(self):
        entries = []
        for d in range(5):
            two_am = self._at_hour(2, days_ago=d)
            if two_am > self._now:
                continue
            for i in range(4):
                entries.append(self._user_event(two_am + i * 60, "up late"))
        self._write(entries)
        msg = ug.usage_reflection(event_log_path=self._log, lang="ja", now=self._now)
        self.assertTrue(msg)


class FallbackStubSignatureTests(unittest.TestCase):
    """The optional-import fallbacks must match the real functions they stand in for.

    usage_guardrails and user_wellbeing both re-implement
    conversation_log._find_archives for the case where that import fails. Both
    stubs had named the parameter `path` while the real function calls it
    `logfile`, so a keyword call would have raised TypeError only when the
    fallback was active — the hardest kind of bug to notice, since the normal
    path works fine. mypy found it when the type gate went in (W-07); this test
    keeps it caught even for anyone who doesn't run mypy locally.

    Checked by name rather than by calling, so it holds regardless of whether
    conversation_log is importable in the current environment.
    """

    def _params(self, func):
        import inspect
        return list(inspect.signature(func).parameters)

    def _reload_with_fallback(self, module_name):
        """Reload module_name with conversation_log unimportable.

        The stub lives in an `except ImportError` branch, so in a healthy
        environment it is never bound — `module._find_archives` is simply the
        real function and any signature check passes vacuously. Forcing the
        import to fail is the only way to actually exercise the stub.
        """
        from unittest import mock
        module = importlib.import_module(module_name)
        with mock.patch.dict(sys.modules, {"conversation_log": None}):
            importlib.reload(module)
            stub = module._find_archives
            params = self._params(stub)
        importlib.reload(module)  # restore the real import for other tests
        return stub, params

    def test_stub_signature_matches_the_real_function(self):
        import conversation_log
        real = self._params(conversation_log._find_archives)
        self.assertIn("logfile", real)  # the name callers would use
        for module_name in ("usage_guardrails", "user_wellbeing"):
            _stub, params = self._reload_with_fallback(module_name)
            self.assertEqual(
                params, real,
                f"{module_name}'s fallback _find_archives diverged from "
                f"conversation_log's — a keyword call would break only when "
                f"the fallback is active",
            )

    def test_stub_is_callable_with_the_real_keyword(self):
        for module_name in ("usage_guardrails", "user_wellbeing"):
            stub, _params = self._reload_with_fallback(module_name)
            self.assertEqual(stub(logfile="anything.jsonl"), [], module_name)

    def test_modules_still_work_after_the_reloads(self):
        """The reload dance must leave the suite's modules usable."""
        self.assertEqual(ug.usage_nudge({"concern": "none"}), "")


if __name__ == "__main__":
    unittest.main()
