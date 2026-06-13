"""
Unit tests for config/env.py — pure Python parsing functions that require
no external dependencies and no filesystem access.

Covers: parse_dotenv, _parse_env_value, _set_nested, _deep_merge,
and get_env_bool/int/float/str/list typed accessors.
"""
import os
import sys
import unittest

_CONFIG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main", "config"
)
sys.path.insert(0, _CONFIG)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main"))

from env import (  # noqa: E402
    parse_dotenv,
    _parse_env_value,
    _set_nested,
    _deep_merge,
    get_env_bool,
    get_env_int,
    get_env_float,
    get_env_str,
    get_env_list,
)


class ParseDotenvTests(unittest.TestCase):
    def test_simple_key_value(self):
        result = parse_dotenv("KEY=value\n")
        self.assertEqual(result["KEY"], "value")

    def test_blank_lines_ignored(self):
        result = parse_dotenv("A=1\n\nB=2\n")
        self.assertIn("A", result)
        self.assertIn("B", result)
        self.assertEqual(len(result), 2)

    def test_comment_lines_ignored(self):
        result = parse_dotenv("# this is a comment\nA=1\n")
        self.assertNotIn("# this is a comment", result)
        self.assertEqual(result["A"], "1")

    def test_export_prefix_stripped(self):
        result = parse_dotenv("export MY_VAR=hello\n")
        self.assertEqual(result["MY_VAR"], "hello")

    def test_double_quoted_value(self):
        result = parse_dotenv('KEY="hello world"\n')
        self.assertEqual(result["KEY"], "hello world")

    def test_single_quoted_value(self):
        result = parse_dotenv("KEY='hello world'\n")
        self.assertEqual(result["KEY"], "hello world")

    def test_double_quoted_escape_sequences(self):
        result = parse_dotenv('KEY="line1\\nline2"\n')
        self.assertIn("\n", result["KEY"])

    def test_single_quoted_no_escape(self):
        result = parse_dotenv("KEY='line1\\nline2'\n")
        self.assertIn("\\n", result["KEY"])  # escapes NOT processed in single quotes

    def test_value_with_hash_preserved(self):
        result = parse_dotenv("KEY=value#notacomment\n")
        self.assertEqual(result["KEY"], "value#notacomment")

    def test_no_equals_sign_skipped(self):
        result = parse_dotenv("NOVALUE\nKEY=ok\n")
        self.assertNotIn("NOVALUE", result)
        self.assertEqual(result["KEY"], "ok")

    def test_empty_value(self):
        result = parse_dotenv("KEY=\n")
        self.assertEqual(result["KEY"], "")

    def test_multiple_entries(self):
        text = "A=1\nB=two\nC=three\n"
        result = parse_dotenv(text)
        self.assertEqual(result, {"A": "1", "B": "two", "C": "three"})


class ParseEnvValueTests(unittest.TestCase):
    def test_true_values(self):
        for v in ("true", "True", "TRUE", "yes", "1"):
            with self.subTest(v=v):
                self.assertTrue(_parse_env_value(v))

    def test_false_values(self):
        for v in ("false", "False", "FALSE", "no", "0"):
            with self.subTest(v=v):
                self.assertFalse(_parse_env_value(v))

    def test_integer_parsed(self):
        self.assertEqual(_parse_env_value("42"), 42)
        self.assertIsInstance(_parse_env_value("42"), int)

    def test_negative_integer_parsed(self):
        self.assertEqual(_parse_env_value("-5"), -5)

    def test_float_parsed(self):
        self.assertAlmostEqual(_parse_env_value("3.14"), 3.14)

    def test_comma_separated_becomes_list(self):
        result = _parse_env_value("a,b,c")
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 3)

    def test_json_object_parsed(self):
        result = _parse_env_value('{"key": "val"}')
        self.assertIsInstance(result, dict)
        self.assertEqual(result["key"], "val")

    def test_plain_string_returned(self):
        self.assertEqual(_parse_env_value("hello"), "hello")


class SetNestedTests(unittest.TestCase):
    def test_simple_key(self):
        cfg = {}
        _set_nested(cfg, "key", "value")
        self.assertEqual(cfg["key"], "value")

    def test_nested_key(self):
        cfg = {}
        _set_nested(cfg, "a.b.c", 42)
        self.assertEqual(cfg["a"]["b"]["c"], 42)

    def test_overwrites_existing(self):
        cfg = {"a": {"b": "old"}}
        _set_nested(cfg, "a.b", "new")
        self.assertEqual(cfg["a"]["b"], "new")

    def test_creates_intermediate_dicts(self):
        cfg = {}
        _set_nested(cfg, "x.y.z", True)
        self.assertIsInstance(cfg["x"], dict)
        self.assertIsInstance(cfg["x"]["y"], dict)


class DeepMergeTests(unittest.TestCase):
    def test_simple_merge(self):
        result = _deep_merge({"a": 1}, {"b": 2})
        self.assertEqual(result, {"a": 1, "b": 2})

    def test_override_wins(self):
        result = _deep_merge({"a": 1}, {"a": 99})
        self.assertEqual(result["a"], 99)

    def test_nested_merge(self):
        base = {"a": {"x": 1, "y": 2}}
        override = {"a": {"y": 99, "z": 3}}
        result = _deep_merge(base, override)
        self.assertEqual(result["a"]["x"], 1)
        self.assertEqual(result["a"]["y"], 99)
        self.assertEqual(result["a"]["z"], 3)

    def test_does_not_mutate_base(self):
        base = {"a": 1}
        _deep_merge(base, {"a": 2})
        self.assertEqual(base["a"], 1)


class TypedEnvAccessorTests(unittest.TestCase):
    def setUp(self):
        self._saved = {}

    def _set(self, key, val):
        self._saved[key] = os.environ.get(key)
        os.environ[key] = val

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_get_env_bool_true(self):
        self._set("_TEST_BOOL", "true")
        self.assertTrue(get_env_bool("_TEST_BOOL"))

    def test_get_env_bool_false(self):
        self._set("_TEST_BOOL", "false")
        self.assertFalse(get_env_bool("_TEST_BOOL"))

    def test_get_env_bool_default(self):
        self.assertFalse(get_env_bool("_MISSING_BOOL_XYZ", False))
        self.assertTrue(get_env_bool("_MISSING_BOOL_XYZ", True))

    def test_get_env_int(self):
        self._set("_TEST_INT", "42")
        self.assertEqual(get_env_int("_TEST_INT"), 42)

    def test_get_env_int_invalid_returns_default(self):
        self._set("_TEST_INT", "abc")
        self.assertEqual(get_env_int("_TEST_INT", 7), 7)

    def test_get_env_float(self):
        self._set("_TEST_FLOAT", "3.14")
        self.assertAlmostEqual(get_env_float("_TEST_FLOAT"), 3.14)

    def test_get_env_str(self):
        self._set("_TEST_STR", "hello")
        self.assertEqual(get_env_str("_TEST_STR"), "hello")

    def test_get_env_str_default(self):
        self.assertEqual(get_env_str("_MISSING_STR_XYZ", "default"), "default")

    def test_get_env_list(self):
        self._set("_TEST_LIST", "a,b,c")
        result = get_env_list("_TEST_LIST")
        self.assertEqual(len(result), 3)

    def test_get_env_list_default(self):
        result = get_env_list("_MISSING_LIST_XYZ", default=["x"])
        self.assertEqual(result, ["x"])


if __name__ == "__main__":
    unittest.main()
