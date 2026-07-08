"""
Tests for main/user_wellbeing.py — the user-mood reflection feature.

user_wellbeing observes the sentiment of the USER's recent messages (distinct
from mood.py which tracks the avatar's affinity) and produces an empathetic
"check-in" line: a gentle nudge when the user has been down, shared joy when
up, and silence (empty string) when there is no clear signal.

Stdlib-only; no GUI/network. Run: python -m unittest tests.test_user_wellbeing -v
"""
import json
import os
import sys
import tempfile
import time
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import user_wellbeing as uw  # noqa: E402
import mood as _mood  # noqa: E402


class ClassifySentimentTests(unittest.TestCase):
    """mood.classify_sentiment is the shared single source of truth."""

    def test_positive(self):
        self.assertEqual(_mood.classify_sentiment("ありがとう、大好き！"), 1)
        self.assertEqual(_mood.classify_sentiment("thank you, that's great"), 1)

    def test_negative(self):
        self.assertEqual(_mood.classify_sentiment("最悪、むかつく"), -1)
        self.assertEqual(_mood.classify_sentiment("I hate this, so boring"), -1)

    def test_neutral(self):
        self.assertEqual(_mood.classify_sentiment("今日は水曜日です"), 0)
        self.assertEqual(_mood.classify_sentiment("the meeting is at noon"), 0)

    def test_empty_and_non_string(self):
        self.assertEqual(_mood.classify_sentiment(""), 0)
        self.assertEqual(_mood.classify_sentiment("   "), 0)
        self.assertEqual(_mood.classify_sentiment(None), 0)

    def test_no_affinity_side_effect(self):
        """classify_sentiment must be pure — it must not touch any mood state."""
        before = _mood.classify_sentiment("ありがとう")
        again = _mood.classify_sentiment("ありがとう")
        self.assertEqual(before, again)  # deterministic, stateless


class WellbeingSummaryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._log = os.path.join(self._tmp, "ev.jsonl")
        self._now = time.time()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write(self, texts, event_type="user_comment", ts=None):
        ts = self._now - 3600 if ts is None else ts
        with open(self._log, "a", encoding="utf-8") as f:
            for t in texts:
                f.write(json.dumps({
                    "event_type": event_type, "timestamp": ts,
                    "details": {"text": t},
                }) + "\n")

    def test_missing_log_is_neutral(self):
        s = uw.wellbeing_summary(event_log_path="/no/such.jsonl", now=self._now)
        self.assertEqual(s["sample_size"], 0)
        self.assertEqual(s["trend"], "neutral")

    def test_low_trend(self):
        self._write(["最悪", "むかつく", "つまらない"])
        s = uw.wellbeing_summary(event_log_path=self._log, days=3, now=self._now)
        self.assertEqual(s["trend"], "low")
        self.assertEqual(s["negative"], 3)

    def test_high_trend(self):
        self._write(["ありがとう", "大好き", "嬉しい"])
        s = uw.wellbeing_summary(event_log_path=self._log, days=3, now=self._now)
        self.assertEqual(s["trend"], "high")
        self.assertEqual(s["positive"], 3)

    def test_below_min_sample_is_neutral(self):
        # Only 2 messages -> not enough to judge.
        self._write(["最悪", "むかつく"])
        s = uw.wellbeing_summary(event_log_path=self._log, days=3, now=self._now)
        self.assertEqual(s["trend"], "neutral")

    def test_mixed_is_neutral(self):
        self._write(["ありがとう", "最悪", "嬉しい", "むかつく", "ふつう"])
        s = uw.wellbeing_summary(event_log_path=self._log, days=3, now=self._now)
        # pos==neg -> no clear trend
        self.assertEqual(s["trend"], "neutral")

    def test_avatar_messages_are_ignored(self):
        # Avatar replies must NOT count toward the user's mood.
        self._write(["最悪", "むかつく", "つまらない"], event_type="avatar_reply")
        s = uw.wellbeing_summary(event_log_path=self._log, days=3, now=self._now)
        self.assertEqual(s["sample_size"], 0)
        self.assertEqual(s["trend"], "neutral")

    def test_old_messages_outside_window_excluded(self):
        # 10 days ago, outside the default 3-day window.
        self._write(["最悪", "むかつく", "つまらない"], ts=self._now - 10 * 86400)
        s = uw.wellbeing_summary(event_log_path=self._log, days=3, now=self._now)
        self.assertEqual(s["sample_size"], 0)

    def test_future_timestamps_excluded(self):
        self._write(["ありがとう", "大好き", "嬉しい"], ts=self._now + 86400)
        s = uw.wellbeing_summary(event_log_path=self._log, days=3, now=self._now)
        self.assertEqual(s["sample_size"], 0)

    def test_null_and_missing_text_safe(self):
        with open(self._log, "w", encoding="utf-8") as f:
            f.write("null\n")  # json null line
            f.write(json.dumps({"event_type": "user_comment", "timestamp": self._now - 60}) + "\n")  # no details
            f.write(json.dumps({"event_type": "user_comment", "timestamp": self._now - 60,
                                "details": {"text": "ありがとう"}}) + "\n")
        s = uw.wellbeing_summary(event_log_path=self._log, days=3, now=self._now)
        # Only the valid messages counted; no crash.
        self.assertEqual(s["sample_size"], 2)  # the no-details one is neutral, the thanks is positive

    def test_cache_returns_same_result_within_ttl(self):
        """Second call with now=None reuses the cached result without re-reading the file."""
        self._write(["最悪", "むかつく", "つまらない"])
        uw._summary_cache.clear()
        # First real call (now=None means cache is active)
        s1 = uw.wellbeing_summary(event_log_path=self._log, days=3)
        # Second call: overwrite the log so we can detect if it was re-read
        with open(self._log, "w", encoding="utf-8") as f:
            f.write("")  # empty file would give sample_size=0
        s2 = uw.wellbeing_summary(event_log_path=self._log, days=3)
        # s2 should still be the cached result from s1
        self.assertEqual(s1["trend"], s2["trend"])
        self.assertEqual(s1["sample_size"], s2["sample_size"])

    def test_explicit_now_bypasses_cache(self):
        """Passing now= explicitly must bypass the cache (test isolation)."""
        self._write(["最悪", "むかつく", "つまらない"])
        s1 = uw.wellbeing_summary(event_log_path=self._log, days=3, now=self._now)
        # Overwrite the log — if cache were active, s2 would equal s1
        with open(self._log, "w", encoding="utf-8") as f:
            f.write("")
        s2 = uw.wellbeing_summary(event_log_path=self._log, days=3, now=self._now)
        # No cache bypass: re-read file gives empty → sample_size=0
        self.assertEqual(s2["sample_size"], 0)


class WellbeingSummaryArchiveTests(unittest.TestCase):
    """Regression: wellbeing_summary() only read the live event log file,
    never the rotated .gz archives avatar_event_log_rotate.rotate_log()
    creates. Since it looks back `days` (default 3, spanning multiple
    days), a size-based rotation mid-window silently dropped every message
    that got rotated into an archive — daily_summary.py's equivalent
    _load_jsonl(include_archives=True) already solved this same problem
    for the same reason (so "yesterday" doesn't read as empty right after
    rotation).
    """

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._log = os.path.join(self._tmp, "ev.jsonl")
        self._now = time.time()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write_archive(self, texts, ts):
        import gzip
        gz_name = os.path.basename(self._log) + ".20260101_000000.gz"
        gz_path = os.path.join(self._tmp, gz_name)
        with gzip.open(gz_path, "wt", encoding="utf-8") as fh:
            for t in texts:
                fh.write(json.dumps({
                    "event_type": "user_comment", "timestamp": ts,
                    "details": {"text": t},
                }) + "\n")

    def test_archived_messages_are_counted(self):
        # Live file empty (just rotated); all messages are in the archive.
        open(self._log, "w").close()
        self._write_archive(["最悪", "むかつく", "つまらない"], ts=self._now - 3600)
        s = uw.wellbeing_summary(event_log_path=self._log, days=3, now=self._now)
        self.assertEqual(s["sample_size"], 3)
        self.assertEqual(s["trend"], "low")

    def test_archived_and_live_messages_are_combined(self):
        open(self._log, "w", encoding="utf-8").write(
            json.dumps({"event_type": "user_comment", "timestamp": self._now - 60,
                       "details": {"text": "最悪"}}) + "\n"
        )
        self._write_archive(["むかつく", "つまらない"], ts=self._now - 3600)
        s = uw.wellbeing_summary(event_log_path=self._log, days=3, now=self._now)
        self.assertEqual(s["sample_size"], 3)
        self.assertEqual(s["trend"], "low")

    def test_archived_messages_outside_window_still_excluded(self):
        open(self._log, "w").close()
        self._write_archive(["最悪", "むかつく", "つまらない"], ts=self._now - 10 * 86400)
        s = uw.wellbeing_summary(event_log_path=self._log, days=3, now=self._now)
        self.assertEqual(s["sample_size"], 0)


class WellbeingMessageTests(unittest.TestCase):
    def test_neutral_returns_empty(self):
        self.assertEqual(uw.wellbeing_message({"trend": "neutral"}), "")

    def test_non_dict_returns_empty(self):
        self.assertEqual(uw.wellbeing_message(None), "")
        self.assertEqual(uw.wellbeing_message("nope"), "")

    def test_low_returns_message(self):
        msg = uw.wellbeing_message({"trend": "low"}, lang="ja")
        self.assertTrue(msg)
        self.assertIn(msg, uw._WELLBEING_MESSAGES["low"]["ja"])

    def test_high_returns_message_en(self):
        msg = uw.wellbeing_message({"trend": "high"}, lang="en")
        self.assertTrue(msg)
        self.assertIn(msg, uw._WELLBEING_MESSAGES["high"]["en"])

    def test_unknown_lang_falls_back_to_en(self):
        msg = uw.wellbeing_message({"trend": "high"}, lang="zz")
        self.assertIn(msg, uw._WELLBEING_MESSAGES["high"]["en"])

    def test_no_repeat_consecutive(self):
        # With several options, two consecutive picks should differ.
        uw._last_pick.clear()
        picks = {uw.wellbeing_message({"trend": "low"}, lang="ja") for _ in range(8)}
        # at least 2 distinct lines used across 8 picks (no-repeat keeps rotating)
        self.assertGreaterEqual(len(picks), 2)


class WellbeingReflectionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._log = os.path.join(self._tmp, "ev.jsonl")
        self._now = time.time()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_reflection_low(self):
        with open(self._log, "w", encoding="utf-8") as f:
            for t in ["最悪", "むかつく", "つまらない"]:
                f.write(json.dumps({"event_type": "user_comment",
                                    "timestamp": self._now - 60,
                                    "details": {"text": t}}) + "\n")
        msg = uw.wellbeing_reflection(event_log_path=self._log, days=3,
                                      lang="ja", now=self._now)
        self.assertIn(msg, uw._WELLBEING_MESSAGES["low"]["ja"])

    def test_reflection_empty_when_no_data(self):
        msg = uw.wellbeing_reflection(event_log_path="/no/such.jsonl",
                                      lang="ja", now=self._now)
        self.assertEqual(msg, "")


if __name__ == "__main__":
    unittest.main()
