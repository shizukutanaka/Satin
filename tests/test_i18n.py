"""
Stdlib-only regression test for main/i18n.py.

i18n.py is shadowed by the i18n/ package on `import i18n`, so we load it by file
path. The key regression: it must import without tkinter (headless), which was
broken by an unconditional `import tkinter` that the active code never used.

Run: python -m unittest tests.test_i18n -v
"""
import importlib.util
import os
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
_I18N_PY = os.path.join(_MAIN, "i18n.py")


def _load_i18n_module():
    spec = importlib.util.spec_from_file_location("satin_i18n_file", _I18N_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class I18nModuleTests(unittest.TestCase):
    def test_loads_headless_without_tkinter(self):
        module = _load_i18n_module()  # must not raise ModuleNotFoundError: tkinter
        self.assertFalse(hasattr(module, "tk"))
        self.assertTrue(hasattr(module, "I18N"))

    def test_translation_and_font_lookup(self):
        module = _load_i18n_module()
        i = module.I18N(lang="ja")
        self.assertEqual(i.font, module.FONT_MAP["ja"])
        # missing key falls back to the provided default
        self.assertEqual(i.t("definitely_missing_key", "fallback"), "fallback")
        # missing key with no default falls back to the key itself
        self.assertEqual(i.t("another_missing_key"), "another_missing_key")

    def test_detect_language_from_env(self):
        module = _load_i18n_module()
        original = os.environ.get("SATIN_LANG")
        os.environ["SATIN_LANG"] = "FR"
        try:
            i = module.I18N()
            self.assertEqual(i.lang, "fr")  # normalized to lower-case
        finally:
            if original is None:
                os.environ.pop("SATIN_LANG", None)
            else:
                os.environ["SATIN_LANG"] = original


if __name__ == "__main__":
    unittest.main()
