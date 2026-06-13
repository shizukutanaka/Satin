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


class JaLocaleTests(unittest.TestCase):
    """ja.json must have non-empty translations for all dashboard keys."""

    _DASHBOARD_KEYS = [
        "title", "event_log", "conversation", "backups", "cloud_sync",
        "mood", "time", "type", "details", "no_file",
        "executed_cloud_sync", "manual_cloud_sync", "you", "avatar",
        "no_conversation", "affinity_score", "affinity_level",
        "interactions", "last_interaction", "mood_unavailable",
        "mood_no_interactions_yet", "reset_mood",
        "mood_history", "mood_no_history", "date", "back_to_mood",
        "total_messages", "download_conversation",
        "search", "search_placeholder", "search_results",
        "stats",
    ]

    def setUp(self):
        module = _load_i18n_module()
        # clear cache so each test starts fresh
        module.I18N._translation_cache.clear()
        self.i18n = module.I18N(lang="ja")

    def test_ja_json_is_not_empty(self):
        self.assertGreater(len(self.i18n.translations), 0)

    def test_all_dashboard_keys_present(self):
        missing = [k for k in self._DASHBOARD_KEYS if k not in self.i18n.translations]
        self.assertEqual(missing, [], f"Missing ja keys: {missing}")

    def test_all_values_are_japanese_nonempty(self):
        for key in self._DASHBOARD_KEYS:
            val = self.i18n.t(key)
            self.assertNotEqual(val, key, f"Key '{key}' returned raw key (likely missing)")
            self.assertTrue(val.strip(), f"Key '{key}' has blank value")

    def test_title_contains_satin(self):
        self.assertIn("Satin", self.i18n.t("title"))

    def test_you_is_japanese(self):
        self.assertEqual(self.i18n.t("you"), "あなた")

    def test_avatar_key(self):
        self.assertEqual(self.i18n.t("avatar"), "アバター")


class EnLocaleTests(unittest.TestCase):
    """en.json must also have all dashboard keys."""

    _DASHBOARD_KEYS = [
        "title", "event_log", "conversation", "backups", "cloud_sync",
        "mood", "time", "type", "details", "no_file",
        "executed_cloud_sync", "manual_cloud_sync", "you", "avatar",
        "no_conversation", "affinity_score", "affinity_level",
        "interactions", "last_interaction", "mood_unavailable",
        "mood_no_interactions_yet", "reset_mood",
        "mood_history", "mood_no_history", "date", "back_to_mood",
        "total_messages", "download_conversation",
        "search", "search_placeholder", "search_results",
        "stats",
    ]

    def setUp(self):
        module = _load_i18n_module()
        module.I18N._translation_cache.clear()
        self.i18n = module.I18N(lang="en")

    def test_all_dashboard_keys_present(self):
        missing = [k for k in self._DASHBOARD_KEYS if k not in self.i18n.translations]
        self.assertEqual(missing, [], f"Missing en keys: {missing}")

    def test_you_is_english(self):
        self.assertEqual(self.i18n.t("you"), "You")

    def test_fallback_to_en_when_lang_missing(self):
        module = _load_i18n_module()
        module.I18N._translation_cache.clear()
        i = module.I18N(lang="zz")  # non-existent lang
        # should fall back to en.json
        self.assertEqual(i.t("you", "fallback"), "You")


if __name__ == "__main__":
    unittest.main()
