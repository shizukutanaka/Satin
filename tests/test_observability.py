"""
Stdlib-only regression tests for the Tier-1 fixes in main/observability.py.

Run: python -m unittest tests.test_observability -v
"""
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main.observability import Metrics  # noqa: E402


class MetricsTests(unittest.TestCase):
    def test_counters_are_thread_safe(self):
        m = Metrics()
        threads_n, per_thread = 8, 5000

        def worker():
            for _ in range(per_thread):
                m.record_api_call("api")
                m.record_error("err")

        threads = [threading.Thread(target=worker) for _ in range(threads_n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        expected = threads_n * per_thread
        # Without locking, concurrent read-modify-write loses increments.
        self.assertEqual(m.api_call_counts["api"], expected)
        self.assertEqual(m.error_counts["err"], expected)

    def test_latency_samples_are_bounded(self):
        m = Metrics()
        for i in range(m._MAX_LATENCY_SAMPLES + 500):
            m.record_operation_latency("op", float(i))
        self.assertEqual(len(m.operation_latencies["op"]), m._MAX_LATENCY_SAMPLES)

    def test_summary_snapshot_is_consistent(self):
        m = Metrics()
        m.record_operation_latency("op", 10.0)
        m.record_operation_latency("op", 20.0)
        summary = m.get_summary()
        self.assertEqual(summary["operation_latencies"]["op"]["count"], 2)
        self.assertEqual(summary["operation_latencies"]["op"]["mean_ms"], 15.0)


if __name__ == "__main__":
    unittest.main()
