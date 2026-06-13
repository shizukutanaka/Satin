"""
Stdlib-only tests for main/daily_summary.py.

Run: python -m unittest tests.test_daily_summary -v
"""
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import date, timedelta, datetime

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from daily_summary import (  # noqa: E402
    daily_summary, summary_greeting, yesterday_summary, yesterday_greeting,
    _load_jsonl, _date_str,
)


def _ts(dt: datetime) -> float:
    return dt.timestamp()


def _write_events(path: str, events: list) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")


def _write_mood(path: str, entries: list) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


class LoadJsonlTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_missing_file_returns_empty(self):
        result = _load_jsonl(os.path.join(self._tmp, "nonexistent.jsonl"))
        self.assertEqual(result, [])

    def test_loads_valid_lines(self):
        path = os.path.join(self._tmp, "data.jsonl")
        _write_events(path, [{"key": "a"}, {"key": "b"}])
        result = _load_jsonl(path)
        self.assertEqual(len(result), 2)

    def test_skips_corrupt_lines(self):
        path = os.path.join(self._tmp, "mixed.jsonl")
        with open(path, "w") as f:
            f.write('{"key": "ok"}\n')
            f.write("not json {\n")
            f.write('{"key": "also_ok"}\n')
        result = _load_jsonl(path)
        self.assertEqual(len(result), 2)


class DateStrTests(unittest.TestCase):
    def test_valid_timestamp(self):
        dt = datetime(2024, 6, 1, 10, 0, 0)
        self.assertEqual(_date_str(dt.timestamp()), "2024-06-01")

    def test_zero_returns_epoch_date(self):
        result = _date_str(0)
        self.assertIsInstance(result, str)


class DailySummaryNoDataTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _no_data_paths(self):
        return {
            "event_log_path": os.path.join(self._tmp, "ev.jsonl"),
            "mood_history_path": os.path.join(self._tmp, "mood.jsonl"),
        }

    def test_returns_dict_when_no_data(self):
        result = daily_summary(**self._no_data_paths())
        self.assertIsInstance(result, dict)

    def test_zero_interactions_when_no_data(self):
        result = daily_summary(**self._no_data_paths())
        self.assertEqual(result["total_interactions"], 0)

    def test_date_in_result(self):
        result = daily_summary(**self._no_data_paths())
        self.assertEqual(result["date"], date.today().strftime("%Y-%m-%d"))

    def test_affinity_none_when_no_mood_data(self):
        result = daily_summary(**self._no_data_paths())
        self.assertIsNone(result["affinity"])

    def test_peak_hour_none_when_no_data(self):
        result = daily_summary(**self._no_data_paths())
        self.assertIsNone(result["peak_hour"])


class DailySummaryWithDataTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        today = date.today()
        today_str = today.strftime("%Y-%m-%d")
        noon = datetime(today.year, today.month, today.day, 12, 0, 0)
        eve = datetime(today.year, today.month, today.day, 18, 0, 0)

        self._ev_path = os.path.join(self._tmp, "ev.jsonl")
        self._mood_path = os.path.join(self._tmp, "mood.jsonl")

        events = [
            {"event_type": "user_comment", "timestamp": _ts(noon)},
            {"event_type": "avatar_reply", "timestamp": _ts(noon)},
            {"event_type": "user_comment", "timestamp": _ts(noon)},
            {"event_type": "avatar_reply", "timestamp": _ts(eve)},
            {"event_type": "user_comment", "timestamp": _ts(eve)},
        ]
        _write_events(self._ev_path, events)

        mood_entries = [
            {"date": today_str, "affinity": 50.0, "level": "neutral"},
            {"date": today_str, "affinity": 55.0, "level": "neutral"},
        ]
        _write_mood(self._mood_path, mood_entries)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _kwargs(self):
        return {"event_log_path": self._ev_path, "mood_history_path": self._mood_path}

    def test_user_messages_counted(self):
        result = daily_summary(**self._kwargs())
        self.assertEqual(result["user_messages"], 3)

    def test_avatar_replies_counted(self):
        result = daily_summary(**self._kwargs())
        self.assertEqual(result["avatar_replies"], 2)

    def test_total_interactions(self):
        result = daily_summary(**self._kwargs())
        self.assertEqual(result["total_interactions"], 5)

    def test_peak_hour_detected(self):
        result = daily_summary(**self._kwargs())
        # noon has 3 events, eve has 2 → peak is 12
        self.assertEqual(result["peak_hour"], 12)

    def test_affinity_from_last_mood_entry(self):
        result = daily_summary(**self._kwargs())
        self.assertAlmostEqual(result["affinity"], 55.0)

    def test_affinity_change_computed(self):
        result = daily_summary(**self._kwargs())
        self.assertAlmostEqual(result["affinity_change"], 5.0)

    def test_event_counts_dict(self):
        result = daily_summary(**self._kwargs())
        self.assertIn("user_comment", result["event_counts"])
        self.assertIn("avatar_reply", result["event_counts"])

    def test_has_all_expected_keys(self):
        result = daily_summary(**self._kwargs())
        for key in ("date", "user_messages", "avatar_replies", "total_interactions",
                    "peak_hour", "affinity", "affinity_level", "affinity_change",
                    "event_counts"):
            self.assertIn(key, result)


class DailySummaryDateFilterTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        today = date.today()
        yesterday = today - timedelta(days=1)
        today_noon = datetime(today.year, today.month, today.day, 12, 0, 0)
        yesterday_noon = datetime(yesterday.year, yesterday.month, yesterday.day, 12, 0, 0)

        self._ev_path = os.path.join(self._tmp, "ev.jsonl")
        self._mood_path = os.path.join(self._tmp, "mood.jsonl")

        events = [
            {"event_type": "user_comment", "timestamp": _ts(today_noon)},
            {"event_type": "user_comment", "timestamp": _ts(yesterday_noon)},
            {"event_type": "user_comment", "timestamp": _ts(yesterday_noon)},
        ]
        _write_events(self._ev_path, events)
        _write_mood(self._mood_path, [])

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _kwargs(self):
        return {"event_log_path": self._ev_path, "mood_history_path": self._mood_path}

    def test_today_only_includes_today_events(self):
        result = daily_summary(**self._kwargs())
        self.assertEqual(result["user_messages"], 1)

    def test_yesterday_only_includes_yesterday_events(self):
        yesterday = date.today() - timedelta(days=1)
        result = daily_summary(target_date=yesterday, **self._kwargs())
        self.assertEqual(result["user_messages"], 2)


class LegacyAliasConsistencyTests(unittest.TestCase):
    """daily_summary must count legacy 'user'/'avatar' event aliases the same
    way the dashboard does, so /stats and /summary never disagree on one log."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._ev_path = os.path.join(self._tmp, "ev.jsonl")
        self._mood_path = os.path.join(self._tmp, "mood.jsonl")
        today = date.today()
        noon = datetime(today.year, today.month, today.day, 12, 0, 0).timestamp()
        events = [
            {"event_type": "user_comment", "timestamp": noon},
            {"event_type": "user", "timestamp": noon},          # legacy alias
            {"event_type": "avatar_reply", "timestamp": noon},
            {"event_type": "avatar", "timestamp": noon},        # legacy alias
        ]
        _write_events(self._ev_path, events)
        _write_mood(self._mood_path, [])

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _kwargs(self):
        return {"event_log_path": self._ev_path, "mood_history_path": self._mood_path}

    def test_legacy_user_alias_counted(self):
        result = daily_summary(**self._kwargs())
        self.assertEqual(result["user_messages"], 2)

    def test_legacy_avatar_alias_counted(self):
        result = daily_summary(**self._kwargs())
        self.assertEqual(result["avatar_replies"], 2)

    def test_agrees_with_dashboard_conversation_stats(self):
        import dashboard
        result = daily_summary(**self._kwargs())
        cs = dashboard._conversation_stats(self._ev_path)
        self.assertEqual(result["user_messages"], cs["total_user"])
        self.assertEqual(result["avatar_replies"], cs["total_avatar"])

    def test_shared_constants_are_imported_from_conversation_log(self):
        import daily_summary as ds
        import conversation_log as cl
        self.assertIs(ds.USER_EVENT_TYPES, cl.USER_EVENT_TYPES)
        self.assertIs(ds.AVATAR_EVENT_TYPES, cl.AVATAR_EVENT_TYPES)


class PeakHourSemanticsTests(unittest.TestCase):
    """peak_hour must reflect USER activity (matching dashboard /stats), not
    total event volume. Otherwise /summary and /stats print different peaks."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._ev_path = os.path.join(self._tmp, "ev.jsonl")
        self._mood_path = os.path.join(self._tmp, "mood.jsonl")
        today = date.today()

        def at(hour):
            return datetime(today.year, today.month, today.day, hour, 0, 0).timestamp()

        # Hour 9: 3 USER messages.
        # Hour 14: 1 user + 5 avatar replies (6 total events).
        # All-events peak would be 14; USER-activity peak is 9.
        events = (
            [{"event_type": "user_comment", "timestamp": at(9)}] * 3
            + [{"event_type": "user_comment", "timestamp": at(14)}]
            + [{"event_type": "avatar_reply", "timestamp": at(14)}] * 5
        )
        _write_events(self._ev_path, events)
        _write_mood(self._mood_path, [])

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _kwargs(self):
        return {"event_log_path": self._ev_path, "mood_history_path": self._mood_path}

    def test_peak_hour_reflects_user_activity_not_total_events(self):
        result = daily_summary(**self._kwargs())
        self.assertEqual(result["peak_hour"], 9)

    def test_peak_hour_agrees_with_dashboard(self):
        import dashboard
        result = daily_summary(**self._kwargs())
        cs = dashboard._conversation_stats(self._ev_path)
        self.assertEqual(result["peak_hour"], cs["peak_hour"])

    def test_non_conversation_events_do_not_skew_peak(self):
        # A burst of non-conversation events must not become the peak hour.
        today = date.today()
        ts = datetime(today.year, today.month, today.day, 3, 0, 0).timestamp()
        with open(self._ev_path, "a", encoding="utf-8") as f:
            for _ in range(20):
                f.write(json.dumps({"event_type": "system_tick", "timestamp": ts}) + "\n")
        result = daily_summary(**self._kwargs())
        self.assertEqual(result["peak_hour"], 9)  # still user-driven, not hour 3


class SummaryGreetingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._ev_path = os.path.join(self._tmp, "ev.jsonl")
        self._mood_path = os.path.join(self._tmp, "mood.jsonl")
        _write_mood(self._mood_path, [])

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _kwargs(self):
        return {"event_log_path": self._ev_path, "mood_history_path": self._mood_path}

    def test_returns_string_when_no_data(self):
        result = summary_greeting(**self._kwargs())
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_returns_string_in_english(self):
        result = summary_greeting(lang="en", **self._kwargs())
        self.assertIsInstance(result, str)

    def test_with_many_interactions_uses_many_template(self):
        today = date.today()
        events = [
            {"event_type": "user_comment",
             "timestamp": datetime(today.year, today.month, today.day, 12, 0, 0).timestamp()}
        ] * 10
        _write_events(self._ev_path, events)
        result = summary_greeting(lang="ja", **self._kwargs())
        self.assertIn("10", result)

    def test_yesterday_greeting_returns_string(self):
        result = yesterday_greeting(lang="ja", **self._kwargs())
        self.assertIsInstance(result, str)

    def test_yesterday_summary_returns_dict(self):
        result = yesterday_summary(lang="ja", **self._kwargs())
        self.assertIsInstance(result, dict)
        self.assertIn("date", result)


if __name__ == "__main__":
    unittest.main()
