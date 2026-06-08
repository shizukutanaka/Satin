"""
Tests for avatar_event_alert.py.

Covers: send_slack_alert graceful degradation when requests is None,
monitor_log deduplication by (timestamp, event_type), and alert
triggering only for known error event types.

Run: python -m unittest tests.test_avatar_event_alert -v
"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import avatar_event_alert  # noqa: E402
from avatar_event_alert import send_slack_alert  # noqa: E402


class SendSlackAlertTests(unittest.TestCase):
    def test_requests_none_prints_and_returns(self):
        """When requests is unavailable, send_slack_alert must not raise."""
        with patch.object(avatar_event_alert, "requests", None):
            # Should not raise
            send_slack_alert("http://example.com/webhook", "hello")

    def test_posts_payload_on_success(self):
        mock_requests = MagicMock()
        mock_response = MagicMock()
        mock_requests.post.return_value = mock_response
        with patch.object(avatar_event_alert, "requests", mock_requests):
            send_slack_alert("http://hook", "test message")
        mock_requests.post.assert_called_once_with(
            "http://hook", json={"text": "test message"}, timeout=5
        )

    def test_exception_in_post_does_not_propagate(self):
        mock_requests = MagicMock()
        mock_requests.post.side_effect = ConnectionError("timeout")
        with patch.object(avatar_event_alert, "requests", mock_requests):
            send_slack_alert("http://hook", "msg")  # must not raise


class MonitorLogDeduplicationTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._logfile = os.path.join(self._tmp, "events.log")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write_event(self, event_type, ts=1700000000.0, details=None):
        ev = {"timestamp": ts, "event_type": event_type, "details": details or {}}
        with open(self._logfile, "a", encoding="utf-8") as f:
            f.write(json.dumps(ev) + "\n")

    def test_alert_sent_for_error_events(self):
        self._write_event("error", ts=1.0)
        alerts = []

        def fake_alert(url, msg):
            alerts.append(msg)

        # Run one iteration of monitor_log using a thread that we stop early
        with patch.object(avatar_event_alert, "send_slack_alert", fake_alert):
            stop = threading.Event()
            original_sleep = time.sleep

            def patched_sleep(_):
                stop.set()
                raise KeyboardInterrupt  # break the while True

            with patch("avatar_event_alert.time") as mock_time:
                mock_time.sleep.side_effect = patched_sleep
                try:
                    avatar_event_alert.monitor_log(self._logfile, "http://hook", poll_interval=0)
                except (KeyboardInterrupt, SystemExit):
                    pass

        self.assertEqual(len(alerts), 1)
        self.assertIn("error", alerts[0])

    def test_no_alert_for_info_event(self):
        self._write_event("info", ts=2.0)
        alerts = []

        def fake_alert(url, msg):
            alerts.append(msg)

        with patch.object(avatar_event_alert, "send_slack_alert", fake_alert):
            with patch("avatar_event_alert.time") as mock_time:
                mock_time.sleep.side_effect = KeyboardInterrupt
                try:
                    avatar_event_alert.monitor_log(self._logfile, "http://hook", poll_interval=0)
                except (KeyboardInterrupt, SystemExit):
                    pass

        self.assertEqual(alerts, [])

    def test_duplicate_events_not_re_alerted(self):
        """Same (timestamp, event_type) appearing twice should only trigger one alert."""
        self._write_event("disconnect", ts=3.0)
        self._write_event("disconnect", ts=3.0)
        alerts = []

        call_count = [0]

        def fake_alert(url, msg):
            alerts.append(msg)

        with patch.object(avatar_event_alert, "send_slack_alert", fake_alert):
            with patch("avatar_event_alert.time") as mock_time:
                mock_time.sleep.side_effect = KeyboardInterrupt
                try:
                    avatar_event_alert.monitor_log(self._logfile, "http://hook", poll_interval=0)
                except (KeyboardInterrupt, SystemExit):
                    pass

        self.assertEqual(len(alerts), 1)


if __name__ == "__main__":
    unittest.main()
