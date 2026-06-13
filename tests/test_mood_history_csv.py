"""
Unit tests for mood.mood_history_to_csv() — CSV export of mood history.
"""
import csv
import io
import json
import os
import sys
import tempfile
import time
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from mood import mood_history_to_csv  # noqa: E402


def _write_history(path: str, entries):
    with open(path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def _parse_csv(csv_str: str):
    reader = csv.DictReader(io.StringIO(csv_str))
    return list(reader)


class EmptyHistoryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_missing_file_returns_header_only(self):
        path = os.path.join(self._tmp, "nonexistent.jsonl")
        csv_str = mood_history_to_csv(history_path=path)
        rows = _parse_csv(csv_str)
        self.assertEqual(rows, [])

    def test_header_has_expected_columns(self):
        path = os.path.join(self._tmp, "empty.jsonl")
        open(path, "w").close()
        csv_str = mood_history_to_csv(history_path=path)
        first_line = csv_str.splitlines()[0]
        for col in ("date", "datetime", "affinity", "level", "interactions"):
            self.assertIn(col, first_line)


class PopulatedHistoryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._path = os.path.join(self._tmp, "history.jsonl")
        now = time.time()
        _write_history(self._path, [
            {"date": "2024-01-01", "timestamp": now - 86400, "affinity": 10.0, "level": "neutral", "interactions": 5},
            {"date": "2024-01-02", "timestamp": now, "affinity": 25.5, "level": "friendly", "interactions": 12},
        ])

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_row_count_matches_history(self):
        rows = _parse_csv(mood_history_to_csv(history_path=self._path))
        self.assertEqual(len(rows), 2)

    def test_date_column_correct(self):
        rows = _parse_csv(mood_history_to_csv(history_path=self._path))
        self.assertEqual(rows[0]["date"], "2024-01-01")
        self.assertEqual(rows[1]["date"], "2024-01-02")

    def test_affinity_column_correct(self):
        rows = _parse_csv(mood_history_to_csv(history_path=self._path))
        self.assertAlmostEqual(float(rows[0]["affinity"]), 10.0)
        self.assertAlmostEqual(float(rows[1]["affinity"]), 25.5)

    def test_level_column_correct(self):
        rows = _parse_csv(mood_history_to_csv(history_path=self._path))
        self.assertEqual(rows[0]["level"], "neutral")
        self.assertEqual(rows[1]["level"], "friendly")

    def test_interactions_column_correct(self):
        rows = _parse_csv(mood_history_to_csv(history_path=self._path))
        self.assertEqual(int(rows[0]["interactions"]), 5)
        self.assertEqual(int(rows[1]["interactions"]), 12)

    def test_datetime_column_is_nonempty(self):
        rows = _parse_csv(mood_history_to_csv(history_path=self._path))
        for row in rows:
            self.assertTrue(row["datetime"], "datetime column should not be empty")

    def test_output_is_crlf_terminated(self):
        csv_str = mood_history_to_csv(history_path=self._path)
        self.assertIn("\r\n", csv_str)

    def test_n_limits_rows(self):
        rows = _parse_csv(mood_history_to_csv(history_path=self._path, n=1))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["date"], "2024-01-02")

    def test_n_zero_returns_all(self):
        rows = _parse_csv(mood_history_to_csv(history_path=self._path, n=0))
        self.assertEqual(len(rows), 2)

    def test_returns_str(self):
        result = mood_history_to_csv(history_path=self._path)
        self.assertIsInstance(result, str)


class RobustnessTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_corrupt_lines_skipped(self):
        path = os.path.join(self._tmp, "history.jsonl")
        with open(path, "w") as f:
            f.write("{ not json }\n")
            f.write(json.dumps({"date": "2024-01-01", "timestamp": time.time(),
                                "affinity": 5.0, "level": "neutral", "interactions": 1}) + "\n")
        rows = _parse_csv(mood_history_to_csv(history_path=path))
        self.assertEqual(len(rows), 1)

    def test_missing_fields_produce_empty_strings(self):
        path = os.path.join(self._tmp, "history.jsonl")
        _write_history(path, [{"date": "2024-01-01", "timestamp": 0}])
        rows = _parse_csv(mood_history_to_csv(history_path=path))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["date"], "2024-01-01")


if __name__ == "__main__":
    unittest.main()
