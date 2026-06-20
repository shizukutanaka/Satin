"""
Tests for the i18n *package* translation manager (main/i18n/__init__.py).

This is distinct from tests/test_i18n.py, which tests the standalone
main/i18n.py *file* (the dashboard's I18N class).  On `import i18n` the package
shadows the file, so I18nManager is what `import i18n` actually resolves to.

Focus: I18nManager.get() must degrade gracefully — a missing key, a non-string
value, or a malformed format string must never raise; it returns the dotted key
(or the str() of a non-string value) instead.  Regression: the original except
clause only caught (KeyError, AttributeError), so a translation string with a
stray '{' or a positional '{0}' placeholder raised ValueError/IndexError that
crashed callers.
"""
import importlib
import os
import sys
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)


def _fresh_manager():
    """Import the i18n package and return a fresh I18nManager instance.

    Guards against the standalone i18n.py file being imported instead by
    asserting the package class is present.
    """
    pkg = importlib.import_module("i18n")
    assert hasattr(pkg, "I18nManager"), "expected the i18n package, got the file"
    return pkg.I18nManager()


class I18nManagerGetTests(unittest.TestCase):
    def setUp(self):
        self.m = _fresh_manager()
        self._lang = self.m.current_lang

    def test_named_placeholder_formats(self):
        out = self.m.get("validation.min_length", min=3)
        self.assertIn("3", out)
        self.assertNotIn("{min}", out)

    def test_missing_key_returns_key(self):
        self.assertEqual(self.m.get("no.such.key.path"), "no.such.key.path")

    def test_missing_kwarg_does_not_crash(self):
        # No 'min' kwarg — must not raise; degrades to the dotted key.
        self.assertEqual(self.m.get("validation.min_length"),
                         "validation.min_length")

    def test_stray_brace_does_not_crash(self):
        """A translation with an unbalanced '{' must not raise ValueError."""
        self.m.translations[self._lang]["_t_stray"] = "oops {"
        self.assertEqual(self.m.get("_t_stray"), "_t_stray")

    def test_positional_placeholder_does_not_crash(self):
        """Positional '{0}' with no args must not raise IndexError."""
        self.m.translations[self._lang]["_t_pos"] = "value {0}"
        self.assertEqual(self.m.get("_t_pos"), "_t_pos")

    def test_non_string_value_returns_str(self):
        self.m.translations[self._lang]["_t_num"] = 42
        self.assertEqual(self.m.get("_t_num"), "42")

    def test_plain_string_without_placeholders(self):
        self.m.translations[self._lang]["_t_plain"] = "Hello"
        self.assertEqual(self.m.get("_t_plain"), "Hello")

    def test_extra_kwargs_ignored(self):
        self.m.translations[self._lang]["_t_plain2"] = "Hello"
        self.assertEqual(self.m.get("_t_plain2", unused="x"), "Hello")


class I18nManagerLoadLanguageTests(unittest.TestCase):
    def test_load_known_language(self):
        m = _fresh_manager()
        self.assertTrue(m.load_language("ja"))
        self.assertEqual(m.current_lang, "ja")

    def test_load_unknown_language_returns_false(self):
        m = _fresh_manager()
        self.assertFalse(m.load_language("zz_nonexistent"))


if __name__ == "__main__":
    unittest.main()
