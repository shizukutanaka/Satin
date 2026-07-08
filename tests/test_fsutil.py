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

from fsutil import restrict_to_owner, iter_jsonl_dicts, load_jsonl_dicts, atomic_write_text  # noqa: E402


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


class AtomicWriteTextTests(unittest.TestCase):
    """Regression: user_profile.py/mood.py/config_manager_enhanced.py each
    hand-rolled write-to-temp-then-os.replace using a FIXED temp filename
    (f"{path}.tmp") shared by every writer to that path. Two concurrent
    save() calls to the same path raced on that one temp file: one writer's
    open(tmp, "w") truncated the other's in-flight temp file, and the loser's
    os.replace(tmp, path) then raised FileNotFoundError — silently dropping
    the update (caught by a broad except Exception, logged as a warning).
    atomic_write_text uses tempfile.mkstemp for a name unique per call,
    eliminating the collision.
    """

    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_writes_content_and_replaces_atomically(self):
        path = os.path.join(self._tmp, "data.json")
        atomic_write_text(path, '{"a": 1}')
        with open(path) as f:
            self.assertEqual(f.read(), '{"a": 1}')

    def test_creates_parent_directories(self):
        path = os.path.join(self._tmp, "nested", "dir", "data.json")
        atomic_write_text(path, "hello")
        with open(path) as f:
            self.assertEqual(f.read(), "hello")

    def test_restrict_true_makes_file_owner_only(self):
        path = os.path.join(self._tmp, "secret.json")
        atomic_write_text(path, "private", restrict=True)
        mode = stat.S_IMODE(os.stat(path).st_mode)
        self.assertEqual(mode & 0o077, 0)

    def test_no_stray_temp_file_left_on_success(self):
        path = os.path.join(self._tmp, "data.json")
        atomic_write_text(path, "content")
        leftovers = [f for f in os.listdir(self._tmp) if f != "data.json"]
        self.assertEqual(leftovers, [])

    def test_temp_file_cleaned_up_on_failure(self):
        # Passing a non-str, non-encodable-cheaply content to force a write
        # failure inside the `with` block (bytes object has no .write(str)
        # compatible path via a text-mode file handle in a way that errors).
        path = os.path.join(self._tmp, "data.json")
        with self.assertRaises(TypeError):
            atomic_write_text(path, b"not a str")  # type: ignore[arg-type]
        leftovers = [f for f in os.listdir(self._tmp) if f != "data.json"]
        self.assertEqual(leftovers, [], f"temp file must be cleaned up on failure: {leftovers}")
        self.assertFalse(os.path.exists(path))

    def test_concurrent_writers_to_same_path_do_not_collide(self):
        """The core regression: N threads writing to the SAME path
        concurrently, each via its own unique temp file, must never raise
        FileNotFoundError from a temp-file collision, and the file must end
        up containing exactly one of the writers' complete content (never a
        truncated/mixed mash of two writers)."""
        import threading
        path = os.path.join(self._tmp, "shared.json")
        errors = []

        def writer(i):
            try:
                for _ in range(30):
                    atomic_write_text(path, f'{{"writer": {i}}}')
            except Exception as e:  # pragma: no cover - failure path
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        self.assertEqual(errors, [], f"concurrent writes raised: {errors}")
        with open(path) as f:
            content = f.read()
        # Must be exactly one complete writer's JSON, never truncated/mixed.
        self.assertRegex(content, r'^\{"writer": \d\}$')


if __name__ == "__main__":
    unittest.main()
