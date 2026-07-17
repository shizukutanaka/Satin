"""
Stdlib-only tests for .env (dotenv) file loading in config/env.py.

Brings Satin in line with Dynaconf / Pydantic-Settings, which auto-load a
.env file. Values land in os.environ and then flow through the existing
SATIN_ env-override overlay into the effective config.

Run: python -m unittest tests.test_config_dotenv -v
"""
import os
import sys
import tempfile
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from config import env as cenv  # noqa: E402


class ParseDotenvTests(unittest.TestCase):
    def test_basic_key_value(self):
        self.assertEqual(cenv.parse_dotenv("A=1\nB=two\n"), {"A": "1", "B": "two"})

    def test_blank_and_comment_lines_ignored(self):
        text = "\n# a comment\n   \nA=1\n#B=2\n"
        self.assertEqual(cenv.parse_dotenv(text), {"A": "1"})

    def test_export_prefix_stripped(self):
        self.assertEqual(cenv.parse_dotenv("export FOO=bar\n"), {"FOO": "bar"})

    def test_surrounding_double_quotes_removed(self):
        self.assertEqual(cenv.parse_dotenv('A="hello world"\n'), {"A": "hello world"})

    def test_surrounding_single_quotes_removed(self):
        self.assertEqual(cenv.parse_dotenv("A='hello world'\n"), {"A": "hello world"})

    def test_double_quote_escapes_expanded(self):
        self.assertEqual(cenv.parse_dotenv('A="line1\\nline2"\n'), {"A": "line1\nline2"})

    def test_hash_inside_value_preserved(self):
        # Values legitimately containing '#' must not be truncated.
        self.assertEqual(cenv.parse_dotenv("A=val#frag\n"), {"A": "val#frag"})

    def test_value_with_equals_sign(self):
        self.assertEqual(cenv.parse_dotenv("A=k=v\n"), {"A": "k=v"})

    def test_empty_key_skipped(self):
        self.assertEqual(cenv.parse_dotenv("=novalue\n"), {})


class LoadDotenvTests(unittest.TestCase):
    def setUp(self):
        self._saved = {k: v for k, v in os.environ.items()
                       if k.startswith(("SATIN_", "DOTENV_TEST_"))}
        for k in self._saved:
            del os.environ[k]

    def tearDown(self):
        for k in [k for k in os.environ if k.startswith(("SATIN_", "DOTENV_TEST_"))]:
            del os.environ[k]
        os.environ.update(self._saved)

    def _write(self, contents):
        fd, path = tempfile.mkstemp(suffix=".env")
        os.write(fd, contents.encode("utf-8"))
        os.close(fd)
        self.addCleanup(os.unlink, path)
        return path

    def test_missing_file_returns_empty(self):
        self.assertEqual(cenv.load_dotenv("/no/such/.env"), {})

    def test_values_applied_to_environ(self):
        path = self._write("DOTENV_TEST_A=1\nDOTENV_TEST_B=two\n")
        applied = cenv.load_dotenv(path)
        self.assertEqual(applied, {"DOTENV_TEST_A": "1", "DOTENV_TEST_B": "two"})
        self.assertEqual(os.environ["DOTENV_TEST_A"], "1")

    def test_existing_real_env_not_overridden_by_default(self):
        os.environ["DOTENV_TEST_A"] = "real"
        path = self._write("DOTENV_TEST_A=fromfile\n")
        applied = cenv.load_dotenv(path)
        self.assertNotIn("DOTENV_TEST_A", applied)
        self.assertEqual(os.environ["DOTENV_TEST_A"], "real")

    def test_override_true_replaces_existing(self):
        os.environ["DOTENV_TEST_A"] = "real"
        path = self._write("DOTENV_TEST_A=fromfile\n")
        cenv.load_dotenv(path, override=True)
        self.assertEqual(os.environ["DOTENV_TEST_A"], "fromfile")

    def test_dotenv_feeds_override_overlay(self):
        path = self._write("SATIN_SETTINGS__LOG_LEVEL=DEBUG\n")
        cenv.load_dotenv(path)
        overlay = cenv.get_dynamic_env_config()
        self.assertEqual(overlay, {"settings": {"log_level": "DEBUG"}})


class AutoloadGuardTests(unittest.TestCase):
    def test_autoload_runs_only_once(self):
        original = cenv._DOTENV_AUTOLOADED
        try:
            cenv._DOTENV_AUTOLOADED = False
            cenv._maybe_autoload_dotenv()
            self.assertTrue(cenv._DOTENV_AUTOLOADED)
            # Second call is a no-op (flag already set); must not raise.
            cenv._maybe_autoload_dotenv()
            self.assertTrue(cenv._DOTENV_AUTOLOADED)
        finally:
            cenv._DOTENV_AUTOLOADED = original


if __name__ == "__main__":
    unittest.main()
