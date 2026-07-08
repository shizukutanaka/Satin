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
        # Regression: a falsy-but-intentional default ("") must be honored, not
        # collapsed to the key by the old `default or key` idiom.
        self.assertEqual(i.t("yet_another_missing", ""), "")

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


class NullLocaleFileTests(unittest.TestCase):
    """load_translation must handle locale files containing null/non-dict JSON."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self._module = _load_i18n_module()
        self._module.I18N._translation_cache.clear()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)
        self._module.I18N._translation_cache.clear()

    def test_null_locale_file_falls_back_to_empty_dict(self):
        import json
        null_path = os.path.join(self.tmp, "xx.json")
        with open(null_path, "w") as f:
            json.dump(None, f)
        original = self._module.LOCALES_DIR
        self._module.LOCALES_DIR = self.tmp
        try:
            result = self._module.I18N(lang="xx")
            self.assertIsInstance(result.translations, dict,
                                  "translations must be dict even for null locale file")
            val = result.t("any_key", "fallback")
            self.assertEqual(val, "fallback")
        finally:
            self._module.LOCALES_DIR = original


class UnvalidatedLangCacheAndTraversalTests(unittest.TestCase):
    """Regression: I18N(lang) used the caller-supplied `lang` directly as a
    key into the process-wide I18N._translation_cache class dict AND
    directly in os.path.join(LOCALES_DIR, f'{lang}.json') before checking
    it was a real, known language. dashboard.py's get_lang() used to pass
    request.args.get('lang') straight through unvalidated, so this was
    reachable with fully attacker-controlled input: unique values grew the
    cache without bound (memory-exhaustion DoS), and traversal payloads
    like "../../config/mood_config" could open/parse arbitrary '.json'
    files outside LOCALES_DIR. Fixed by clamping the cache key (not
    self.lang, which legitimately needs the raw value for FONT_MAP
    lookups) to the actual locale files present before any path is built.
    """

    def setUp(self):
        self._module = _load_i18n_module()
        self._module.I18N._translation_cache.clear()

    def tearDown(self):
        self._module.I18N._translation_cache.clear()

    def test_arbitrary_lang_values_do_not_grow_cache_unboundedly(self):
        for i in range(500):
            self._module.I18N(lang=f"attacker-{i}")
        self.assertLessEqual(len(self._module.I18N._translation_cache), 2)

    def test_path_traversal_lang_does_not_read_outside_locales_dir(self):
        # Must not raise, must not leak content from outside LOCALES_DIR —
        # falls back to the 'en' cache key/content like any other unknown lang.
        i = self._module.I18N(lang="../../../../etc/passwd")
        self.assertIsInstance(i.translations, dict)
        self.assertIn("en", self._module.I18N._translation_cache.keys() | {"en"})

    def test_self_lang_still_reflects_raw_requested_value(self):
        # self.lang must stay the raw value (used for FONT_MAP font-matching),
        # even though the translation cache key underneath is clamped.
        i = self._module.I18N(lang="fr")
        self.assertEqual(i.lang, "fr")
        self.assertEqual(i.font, self._module.FONT_MAP.get("fr", "Arial"))


if __name__ == "__main__":
    unittest.main()
