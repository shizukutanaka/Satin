"""
Tests for PerformanceMonitor._check_alerts threshold state machine.

_check_alerts increments an internal counter each consecutive cycle a
threshold is breached, and only returns True once alert_count reaches
alert_threshold.  A clean cycle resets the counter.  These are pure-logic
tests that don't touch psutil or spawn threads.

Run: python -m unittest tests.test_performance_monitor -v
"""
import os
import sys
import unittest
from unittest.mock import patch

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)


def _make_monitor(thresholds=None, alert_threshold=3):
    """Build a PerformanceMonitor without running __init__ (avoids config I/O)."""
    from performance_monitor import PerformanceMonitor
    pm = object.__new__(PerformanceMonitor)
    pm.thresholds = thresholds or {
        "memory": 80, "cpu": 90, "disk": 90, "network": 1_000_000,
    }
    pm.alert_threshold = alert_threshold
    pm.alert_count = 0
    pm.alert_enabled = True
    pm.last_alert = None
    return pm


def _stats(memory=10, cpu=10, disk=10, sent=0, recv=0):
    return {
        "timestamp": "2026-01-01T00:00:00",
        "memory": {"percent": memory, "total": 100, "used": memory},
        "cpu": {"usage": cpu, "count": 4},
        "disk": {"percent": disk, "io_read": 0, "io_write": 0},
        "network": {"io_sent": sent, "io_recv": recv},
    }


class CheckAlertsTests(unittest.TestCase):
    def test_no_breach_returns_false(self):
        pm = _make_monitor()
        self.assertFalse(pm._check_alerts(_stats()))
        self.assertEqual(pm.alert_count, 0)

    def test_single_breach_below_threshold_returns_false(self):
        pm = _make_monitor(alert_threshold=3)
        # 1st breach -> count=1, still below threshold
        self.assertFalse(pm._check_alerts(_stats(memory=95)))
        self.assertEqual(pm.alert_count, 1)

    def test_breach_reaching_threshold_returns_true(self):
        pm = _make_monitor(alert_threshold=3)
        self.assertFalse(pm._check_alerts(_stats(memory=95)))  # 1
        self.assertFalse(pm._check_alerts(_stats(memory=95)))  # 2
        self.assertTrue(pm._check_alerts(_stats(memory=95)))   # 3 -> alert
        self.assertEqual(pm.alert_count, 3)

    def test_clean_cycle_resets_counter(self):
        pm = _make_monitor(alert_threshold=3)
        pm._check_alerts(_stats(memory=95))  # count=1
        pm._check_alerts(_stats(memory=95))  # count=2
        pm._check_alerts(_stats(memory=10))  # clean -> reset
        self.assertEqual(pm.alert_count, 0)

    def test_cpu_threshold_breach(self):
        pm = _make_monitor(alert_threshold=1)
        self.assertTrue(pm._check_alerts(_stats(cpu=95)))

    def test_disk_threshold_breach(self):
        pm = _make_monitor(alert_threshold=1)
        self.assertTrue(pm._check_alerts(_stats(disk=95)))

    def test_network_threshold_breach_sums_sent_and_recv(self):
        pm = _make_monitor(alert_threshold=1)
        # sent + recv = 600k + 600k = 1.2M > 1M threshold
        self.assertTrue(pm._check_alerts(_stats(sent=600_000, recv=600_000)))

    def test_network_below_threshold_individually_but_sum_breaches(self):
        """Each of sent/recv is below threshold but their sum exceeds it."""
        pm = _make_monitor(alert_threshold=1)
        self.assertTrue(pm._check_alerts(_stats(sent=900_000, recv=200_000)))


class CollectStatsNullDiskIOTest(unittest.TestCase):
    """Regression: psutil.disk_io_counters() returning None raised AttributeError."""

    def test_collect_stats_with_null_disk_io_counters(self):
        from performance_monitor import PerformanceMonitor
        import unittest.mock as mock

        pm = object.__new__(PerformanceMonitor)

        fake_vmem = mock.MagicMock()
        fake_vmem.total = 8_000_000_000
        fake_vmem.used = 4_000_000_000
        fake_vmem.percent = 50.0

        fake_net = mock.MagicMock()
        fake_net.bytes_sent = 1024
        fake_net.bytes_recv = 2048

        fake_disk_usage = mock.MagicMock()
        fake_disk_usage.percent = 42.0

        with mock.patch('performance_monitor.psutil') as psutil_mock:
            psutil_mock.virtual_memory.return_value = fake_vmem
            psutil_mock.cpu_percent.return_value = 30.0
            psutil_mock.cpu_count.return_value = 4
            psutil_mock.disk_io_counters.return_value = None  # platform with no counters
            psutil_mock.disk_usage.return_value = fake_disk_usage
            psutil_mock.net_io_counters.return_value = fake_net

            stats = pm._collect_stats()

        self.assertEqual(stats['disk']['io_read'], 0)
        self.assertEqual(stats['disk']['io_write'], 0)
        self.assertEqual(stats['disk']['percent'], 42.0)


if __name__ == "__main__":
    unittest.main()
