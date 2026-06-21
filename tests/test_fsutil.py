"""
Tests for fsutil.restrict_to_owner — best-effort owner-only file permissions
for private data (conversation history, affinity).

Run: python -m unittest tests.test_fsutil -v
"""
import os
import stat
import sys
import tempfile
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import json  # noqa: E402

from fsutil import restrict_to_owner, iter_jsonl_dicts, load_jsonl_dicts  # noqa: E402


class RestrictToOwnerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._path = os.path.join(self._tmp, "secret.txt")
        with open(self._path, "w") as f:
            f.write("private")
        os.chmod(self._path, 0o644)  # start world-readable

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_makes_file_owner_only(self):
        self.assertTrue(restrict_to_owner(self._path))
        mode = stat.S_IMODE(os.stat(self._path).st_mode)
        self.assertEqual(mode & 0o077, 0)  # no group/other bits

    def test_owner_can_still_read_write(self):
        restrict_to_owner(self._path)
        mode = stat.S_IMODE(os.stat(self._path).st_mode)
        self.assertTrue(mode & stat.S_IRUSR)
        self.assertTrue(mode & stat.S_IWUSR)

    def test_missing_file_returns_false_no_raise(self):
        result = restrict_to_owner(os.path.join(self._tmp, "nope.txt"))
        self.assertFalse(result)  # must not raise


class LoadJsonlDictsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write(self, lines):
        path = os.path.join(self._tmp, "data.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            f.write("".join(lines))
        return path

    def test_missing_file_returns_empty(self):
        self.assertEqual(load_jsonl_dicts(os.path.join(self._tmp, "nope.jsonl")), [])

    def test_loads_dict_rows(self):
        path = self._write(['{"a": 1}\n', '{"b": 2}\n'])
        self.assertEqual(load_jsonl_dicts(path), [{"a": 1}, {"b": 2}])

    def test_skips_blank_lines(self):
        path = self._write(['{"a": 1}\n', "\n", "   \n", '{"b": 2}\n'])
        self.assertEqual(len(load_jsonl_dicts(path)), 2)

    def test_skips_invalid_json(self):
        path = self._write(['{"a": 1}\n', "not json {\n", '{"b": 2}\n'])
        self.assertEqual(len(load_jsonl_dicts(path)), 2)

    def test_skips_null_line(self):
        # json.loads("null") -> None (no exception); must be skipped, not appended.
        path = self._write(['{"a": 1}\n', "null\n", '{"b": 2}\n'])
        result = load_jsonl_dicts(path)
        self.assertEqual(len(result), 2)
        self.assertTrue(all(isinstance(d, dict) for d in result))

    def test_skips_non_dict_json(self):
        # arrays, numbers and strings are valid JSON but not dict rows.
        path = self._write(['{"a": 1}\n', "[1, 2, 3]\n", "42\n", '"hi"\n', '{"b": 2}\n'])
        self.assertEqual(load_jsonl_dicts(path), [{"a": 1}, {"b": 2}])

    def test_empty_file_returns_empty(self):
        path = self._write([])
        self.assertEqual(load_jsonl_dicts(path), [])

    def test_iter_is_lazy_generator(self):
        import types
        path = self._write(['{"a": 1}\n'])
        gen = iter_jsonl_dicts(path)
        self.assertIsInstance(gen, types.GeneratorType)
        self.assertEqual(list(gen), [{"a": 1}])

    def test_tail_slice_pattern(self):
        path = self._write([json.dumps({"i": i}) + "\n" for i in range(10)])
        self.assertEqual(load_jsonl_dicts(path)[-3:], [{"i": 7}, {"i": 8}, {"i": 9}])


if __name__ == "__main__":
    unittest.main()
