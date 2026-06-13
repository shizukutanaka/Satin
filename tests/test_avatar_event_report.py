"""
Unit tests for avatar_event_report — load_events, event_stats, and plot_stats
(plot_stats when matplotlib is absent, which is the case in test environments).
"""
import json
import os
import sys
import tempfile
import unittest
from collections import Counter

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import avatar_event_report as aer  # noqa: E402


def _make_log(tmpdir, events):
    path = os.path.join(tmpdir, "events.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return path


class LoadEventsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_load_returns_list_of_dicts(self):
        path = _make_log(self._tmp, [
            {"event_type": "comment", "timestamp": 1000.0},
        ])
        events = aer.load_events(path)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "comment")

    def test_blank_lines_are_skipped(self):
        path = os.path.join(self._tmp, "ev.jsonl")
        with open(path, "w") as f:
            f.write('{"event_type": "a"}\n\n{"event_type": "b"}\n')
        events = aer.load_events(path)
        self.assertEqual(len(events), 2)

    def test_invalid_json_lines_are_skipped(self):
        path = os.path.join(self._tmp, "ev.jsonl")
        with open(path, "w") as f:
            f.write('{"event_type": "a"}\n')
            f.write('this is not json\n')
            f.write('{"event_type": "b"}\n')
        events = aer.load_events(path)
        self.assertEqual(len(events), 2)

    def test_empty_file_returns_empty_list(self):
        path = os.path.join(self._tmp, "empty.jsonl")
        open(path, "w").close()
        self.assertEqual(aer.load_events(path), [])


class EventStatsTests(unittest.TestCase):
    def test_counts_event_types(self):
        events = [
            {"event_type": "comment", "timestamp": 1000.0},
            {"event_type": "comment", "timestamp": 2000.0},
            {"event_type": "tts_fail", "timestamp": 3000.0},
        ]
        counts, by_hour, times = aer.event_stats(events)
        self.assertEqual(counts["comment"], 2)
        self.assertEqual(counts["tts_fail"], 1)

    def test_by_hour_accumulates_correctly(self):
        # 1000s ≈ 1970-01-01 00:16 UTC — hour 0 in local
        from datetime import datetime
        events = [{"event_type": "e", "timestamp": 1000.0}]
        counts, by_hour, times = aer.event_stats(events)
        total = sum(by_hour.values())
        self.assertEqual(total, 1)

    def test_events_without_timestamp_excluded_from_times(self):
        events = [
            {"event_type": "a"},  # no timestamp
            {"event_type": "b", "timestamp": 1000.0},
        ]
        _, _, times = aer.event_stats(events)
        self.assertEqual(len(times), 1)

    def test_empty_events(self):
        counts, by_hour, times = aer.event_stats([])
        self.assertIsInstance(counts, Counter)
        self.assertEqual(len(counts), 0)
        self.assertEqual(times, [])

    def test_returns_three_values(self):
        result = aer.event_stats([])
        self.assertEqual(len(result), 3)


class PlotStatsNoMatplotlibTests(unittest.TestCase):
    """plot_stats should no-op gracefully when matplotlib is absent."""

    def test_skips_without_matplotlib(self):
        from unittest import mock
        with mock.patch.object(aer, "plt", None), \
             mock.patch("builtins.print") as mock_print:
            aer.plot_stats(Counter({"a": 1}), {0: 1}, [], "/tmp/unused")
        # Should print a skip message, not raise
        all_text = " ".join(str(a) for call in mock_print.call_args_list for a in call.args)
        self.assertIn("matplotlib", all_text)


if __name__ == "__main__":
    unittest.main()
