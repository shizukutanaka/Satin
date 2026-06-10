"""
Regression tests for avatar_event_timeline_viewer.

Qt is absent in CI. We test load_logfile and show_detail by constructing a
minimal duck-typed object with the attributes those methods require, bypassing
the Qt-dependent __init__.
"""
import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import avatar_event_timeline_viewer as _mod  # noqa: E402


def _fake_viewer(logfile=""):
    """Build the minimal duck-typed object that load_logfile/show_detail need."""

    class _FakeListWidget:
        def __init__(self):
            self._items = []
        def clear(self):
            self._items.clear()
        def addItem(self, text):
            self._items.append(text)

    class _FakeLabel:
        def __init__(self):
            self._text = ""
        def setText(self, t):
            self._text = t
        def text(self):
            return self._text

    # Construct without calling __init__
    v = object.__new__(_mod.EventTimelineViewer)
    v.events = []
    v.list_widget = _FakeListWidget()
    v.detail_label = _FakeLabel()
    v.logfile = logfile
    return v


class LoadLogfileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._logfile = os.path.join(self._tmp, "events.jsonl")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write(self, events):
        with open(self._logfile, "w", encoding="utf-8") as f:
            for ev in events:
                f.write(json.dumps(ev) + "\n")

    def test_null_timestamp_does_not_crash(self):
        """Regression: timestamp=None must not raise TypeError."""
        self._write([{"timestamp": None, "event_type": "error", "details": {}}])
        v = _fake_viewer(self._logfile)
        v.load_logfile(self._logfile)
        self.assertEqual(len(v.events), 1)

    def test_missing_timestamp_does_not_crash(self):
        """Absent timestamp key must not raise."""
        self._write([{"event_type": "info", "details": {}}])
        v = _fake_viewer(self._logfile)
        v.load_logfile(self._logfile)
        self.assertEqual(len(v.events), 1)

    def test_invalid_json_lines_skipped(self):
        with open(self._logfile, "w", encoding="utf-8") as f:
            f.write("not json\n")
            f.write(json.dumps({"timestamp": 0, "event_type": "ok"}) + "\n")
        v = _fake_viewer(self._logfile)
        v.load_logfile(self._logfile)
        self.assertEqual(len(v.events), 1)

    def test_multiple_events_loaded(self):
        self._write([
            {"timestamp": 1_000_000, "event_type": "a"},
            {"timestamp": 2_000_000, "event_type": "b"},
        ])
        v = _fake_viewer(self._logfile)
        v.load_logfile(self._logfile)
        self.assertEqual(len(v.events), 2)
        self.assertEqual(len(v.list_widget._items), 2)


class ShowDetailTests(unittest.TestCase):
    def _viewer_with_events(self, events):
        v = _fake_viewer()
        v.events = events
        return v

    def test_html_escape_in_event_type(self):
        """event_type containing HTML tags must be escaped."""
        v = self._viewer_with_events([{
            "timestamp": 1_700_000_000,
            "event_type": "<b>EVIL</b>",
            "details": {},
        }])
        v.show_detail(0)
        html = v.detail_label.text()
        self.assertIn("&lt;b&gt;EVIL&lt;/b&gt;", html)
        self.assertNotIn("<b>EVIL</b>", html)

    def test_html_escape_in_details(self):
        """details dict with HTML content must be escaped."""
        v = self._viewer_with_events([{
            "timestamp": 1_700_000_000,
            "event_type": "test",
            "details": {"msg": "<script>alert(1)</script>"},
        }])
        v.show_detail(0)
        html = v.detail_label.text()
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_out_of_range_index_clears_label(self):
        """Out-of-range index must set empty text, not raise IndexError."""
        v = self._viewer_with_events([{"timestamp": 0, "event_type": "ok"}])
        v.show_detail(999)
        self.assertEqual(v.detail_label.text(), "")

    def test_negative_index_clears_label(self):
        v = self._viewer_with_events([{"timestamp": 0, "event_type": "ok"}])
        v.show_detail(-1)
        self.assertEqual(v.detail_label.text(), "")

    def test_valid_index_shows_detail(self):
        v = self._viewer_with_events([{
            "timestamp": 1_700_000_000,
            "event_type": "click",
            "details": {"x": 10},
        }])
        v.show_detail(0)
        html = v.detail_label.text()
        self.assertIn("click", html)
        self.assertIn("時刻", html)


if __name__ == "__main__":
    unittest.main()
