"""
End-to-end language tests for the Flask dashboard (work order W-06).

The verification pass behind W-06 found the dashboard was *mostly* localized —
37 keys already went through i18n.t() — but two pages (/stats, /summary) plus
two CSV link labels built their text from inline `'English' if is_en else
'日本語'` ternaries, and three places rendered the raw internal affinity level
key ("friendly", "neutral") straight from config/mood_history.jsonl into a
Japanese page.

Inline ternaries do switch language, so this is not a broken-UX bug — it is a
structural one: the strings live outside the locale files, so a third language
can never be added, and `f'{name} replies'` vs `f'{name}の返答'` hardcodes word
order that differs per language. These tests pin the behaviour to the locale
files instead of the source.

Also covers Accept-Language content negotiation (RFC 9110 proactive
negotiation): the dashboard runs on a server whose OS locale may have nothing
to do with the person holding the browser, so an unset SATIN_LANG should fall
through to what the browser asks for rather than to the server's locale.

Run: python -m unittest tests.test_dashboard_i18n -v
"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MAIN = os.path.join(_ROOT, "main")
sys.path.insert(0, _MAIN)

import dashboard  # noqa: E402
import mood as mood_mod  # noqa: E402

_HAS_FLASK = getattr(dashboard, "_FLASK_AVAILABLE", False)


class LevelLabelTests(unittest.TestCase):
    """mood.level_label — lookup by stored key, not by numeric affinity."""

    def test_known_keys_localize(self):
        self.assertEqual(mood_mod.level_label("friendly", "ja"), "なかよし")
        self.assertEqual(mood_mod.level_label("friendly", "en"), "friendly")
        self.assertEqual(mood_mod.level_label("close", "ja"), "親友")
        self.assertEqual(mood_mod.level_label("distant", "ja"), "よそよそしい")

    def test_every_level_key_has_a_japanese_label(self):
        for _lower, key, _labels in mood_mod._LEVELS:
            self.assertNotEqual(
                mood_mod.level_label(key, "ja"), key,
                f"level '{key}' has no Japanese label",
            )

    def test_unknown_key_is_passed_through(self):
        """A hand-edited or future level must not be swallowed."""
        self.assertEqual(mood_mod.level_label("bogus", "ja"), "bogus")
        self.assertEqual(mood_mod.level_label("", "ja"), "")
        self.assertEqual(mood_mod.level_label(None, "ja"), "")

    def test_matches_affinity_label_for_the_same_level(self):
        """The two lookups share _LEVELS, so they must not disagree."""
        for lower, key, _labels in mood_mod._LEVELS:
            self.assertEqual(
                mood_mod.level_label(key, "ja"),
                mood_mod.affinity_label(lower, "ja"),
                key,
            )

    def test_dashboard_helper_survives_mood_being_unavailable(self):
        with mock.patch.object(dashboard, "_level_label", None):
            self.assertEqual(dashboard._localized_level("friendly", "ja"), "friendly")


@unittest.skipUnless(_HAS_FLASK, "Flask not installed")
class _RenderBase(unittest.TestCase):
    """Drives the real routes with a temp conversation log + mood history."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.log = os.path.join(self._tmp, "ev.jsonl")
        self.hist = os.path.join(self._tmp, "mood_history.jsonl")
        now = time.time()
        with open(self.log, "w", encoding="utf-8") as fh:
            for i in range(3):
                fh.write(json.dumps({
                    "timestamp": now - i * 60, "event_type": "user_comment",
                    "details": {"text": "hello"}}) + "\n")
                fh.write(json.dumps({
                    "timestamp": now - i * 60, "event_type": "avatar_reply",
                    "details": {"text": "hi"}}) + "\n")
        today = time.strftime("%Y-%m-%d")
        with open(self.hist, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "date": "2026-08-01", "affinity": 45.0, "level": "neutral"}) + "\n")
            fh.write(json.dumps({
                "date": today, "affinity": 66.0, "level": "friendly",
                "level_changed": True, "prev_level": "neutral"}) + "\n")

        self._patchers = [
            mock.patch.object(dashboard, "event_log_path", self.log),
            mock.patch.object(dashboard, "_mood_history_path", lambda: self.hist),
        ]
        for p in self._patchers:
            p.start()
        dashboard.app.config["TESTING"] = True
        self.client = dashboard.app.test_client()
        dashboard.I18N._translation_cache.clear()

    def tearDown(self):
        for p in self._patchers:
            p.stop()
        shutil.rmtree(self._tmp, ignore_errors=True)
        dashboard.I18N._translation_cache.clear()

    def _body(self, path, lang):
        resp = self.client.get(f"{path}?lang={lang}")
        self.assertEqual(resp.status_code, 200, path)
        return resp.data.decode("utf-8")


class StatsPageLanguageTests(_RenderBase):
    def test_english_labels(self):
        body = self._body("/stats", "en")
        for probe in ("User messages", "Avatar replies", "Messages per day",
                      "Peak activity", "Messages per hour"):
            self.assertIn(probe, body, probe)

    def test_japanese_labels(self):
        body = self._body("/stats", "ja")
        for probe in ("ユーザーメッセージ", "アバター返答", "日別メッセージ数",
                      "ピーク時間帯", "時間別メッセージ数"):
            self.assertIn(probe, body, probe)

    def test_japanese_page_has_no_english_leftovers(self):
        body = self._body("/stats", "ja")
        for leak in ("User messages", "Avatar replies", "Messages per day",
                     "Peak activity", "Messages per hour"):
            self.assertNotIn(leak, body, leak)

    def test_hour_axis_unit_is_localized(self):
        """The hour column read '00h' in Japanese too."""
        self.assertIn("00h", self._body("/stats", "en"))
        self.assertIn("00時", self._body("/stats", "ja"))

    def test_empty_state_is_localized(self):
        empty = os.path.join(self._tmp, "empty.jsonl")
        open(empty, "w").close()
        with mock.patch.object(dashboard, "event_log_path", empty):
            self.assertIn("No conversation data yet.", self._body("/stats", "en"))
            self.assertIn("まだ会話データがありません。", self._body("/stats", "ja"))


class SummaryPageLanguageTests(_RenderBase):
    def test_english_labels(self):
        body = self._body("/summary", "en")
        for probe in ("Your messages", "Total interactions", "Peak hour",
                      "Affinity"):
            self.assertIn(probe, body, probe)

    def test_japanese_labels(self):
        body = self._body("/summary", "ja")
        for probe in ("あなたのメッセージ", "合計やりとり", "好感度"):
            self.assertIn(probe, body, probe)

    def test_japanese_page_has_no_english_leftovers(self):
        body = self._body("/summary", "ja")
        for leak in ("Your messages", "Total interactions", "Peak hour"):
            self.assertNotIn(leak, body, leak)

    def test_persona_name_keeps_its_place_in_both_languages(self):
        """Word order differs — '{name} replies' vs '{name}の返答'."""
        name = dashboard._get_persona_name()
        en = self._body("/summary", "en")
        ja = self._body("/summary", "ja")
        self.assertIn(f"{name} replies", en)
        self.assertIn(f"{name}の返答", ja)

    def test_affinity_level_is_localized_not_a_raw_key(self):
        body = self._body("/summary", "ja")
        self.assertIn("なかよし", body)
        self.assertNotIn("friendly", body)


class MoodHistoryLevelTests(_RenderBase):
    def test_level_column_is_localized(self):
        body = self._body("/mood/history", "ja")
        self.assertIn("なかよし", body)
        self.assertIn("ふつう", body)

    def test_raw_level_keys_do_not_leak_into_the_japanese_page(self):
        body = self._body("/mood/history", "ja")
        for leak in ("friendly", "neutral"):
            self.assertNotIn(leak, body, leak)

    def test_english_page_still_shows_english_levels(self):
        body = self._body("/mood/history", "en")
        self.assertIn("friendly", body)

    def test_milestone_arrow_direction_still_correct(self):
        """Localizing the labels must not disturb the rank comparison that
        picks the up/down arrow (it compares raw keys, not labels)."""
        self.assertIn("&#8593;", self._body("/mood/history", "ja"))

    def test_csv_link_label_is_localized(self):
        self.assertIn("Download CSV", self._body("/mood/history", "en"))
        self.assertIn("CSVダウンロード", self._body("/mood/history", "ja"))


class ConversationCsvLabelTests(_RenderBase):
    def test_csv_link_label_is_localized(self):
        self.assertIn("CSV形式", self._body("/conversation", "ja"))
        body_en = self._body("/conversation", "en")
        self.assertIn("CSV", body_en)
        self.assertNotIn("CSV形式", body_en)


@unittest.skipUnless(_HAS_FLASK, "Flask not installed")
class AcceptLanguageNegotiationTests(unittest.TestCase):
    """RFC 9110 proactive content negotiation for the display language."""

    def setUp(self):
        dashboard.I18N._translation_cache.clear()
        self._env = mock.patch.dict(os.environ, {}, clear=False)
        self._env.start()
        os.environ.pop("SATIN_LANG", None)

    def tearDown(self):
        self._env.stop()
        dashboard.I18N._translation_cache.clear()

    def _lang(self, headers=None, path="/"):
        with dashboard.app.test_request_context(path, headers=headers or {}):
            return dashboard.get_lang()

    def test_browser_preference_is_honoured(self):
        self.assertEqual(self._lang({"Accept-Language": "ja,en;q=0.8"}), "ja")
        self.assertEqual(self._lang({"Accept-Language": "en-US,en;q=0.9"}), "en")

    def test_quality_values_are_respected(self):
        self.assertEqual(
            self._lang({"Accept-Language": "en;q=0.3, ja;q=0.9"}), "ja")

    def test_unsupported_languages_fall_back(self):
        lang = self._lang({"Accept-Language": "fr-FR,fr;q=0.9,de;q=0.8"})
        self.assertIn(lang, dashboard._SUPPORTED_DASHBOARD_LANGS)

    def test_query_parameter_beats_the_header(self):
        """An explicit user choice must win over the browser's guess."""
        self.assertEqual(
            self._lang({"Accept-Language": "ja"}, path="/?lang=en"), "en")

    def test_satin_lang_beats_the_header(self):
        """The operator's explicit setting outranks the browser too."""
        os.environ["SATIN_LANG"] = "ja"
        self.assertEqual(self._lang({"Accept-Language": "en-US,en;q=0.9"}), "ja")

    def test_satin_lang_region_variants_are_accepted(self):
        for value in ("ja_JP", "ja-JP", "JA"):
            os.environ["SATIN_LANG"] = value
            self.assertEqual(
                self._lang({"Accept-Language": "en"}), "ja", value)

    def test_unsupported_satin_lang_falls_through_to_the_header(self):
        os.environ["SATIN_LANG"] = "fr"
        self.assertEqual(self._lang({"Accept-Language": "ja"}), "ja")

    def test_malformed_header_does_not_error(self):
        for bad in ("", ";;;", "q=", "ja;q=notanumber", "*"):
            lang = self._lang({"Accept-Language": bad})
            self.assertIn(lang, dashboard._SUPPORTED_DASHBOARD_LANGS, bad)

    def test_result_is_always_clamped_to_the_allowlist(self):
        """The XSS/cache-growth clamp must survive the new negotiation step."""
        for header in ("zz", "../../etc/passwd", "<script>alert(1)</script>"):
            self.assertIn(
                self._lang({"Accept-Language": header}),
                dashboard._SUPPORTED_DASHBOARD_LANGS,
                header,
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


@unittest.skipUnless(_HAS_FLASK, "flask is not installed")
class BackupPageHonestyTests(_RenderBase):
    """バックアップページが「クラウド同期」を騙らないこと。

    /sync は config/ と会話ログをローカルの zip にまとめるだけで、ネットワークに
    一切触れない。にもかかわらず見出しは「クラウド同期」/"Cloud Sync"、ボタンは
    「今すぐ同期」、完了メッセージは「クラウド同期を実行しました」だった
    （`sync_to_cloud` が存在した頃のラベルの残骸）。

    その直下の説明文には「ローカルバックアップを作成します」と正しく書いてあり、
    ページが自分自身と矛盾していた。「ローカル完結・オフライン・プライバシー
    第一」を第一原理に掲げる製品で、データが外部へ出ると読める表示をするのは
    単なる誤字ではない — ユーザーが最も気にしている一点について嘘をついている。
    """

    def test_page_does_not_claim_to_sync_to_a_cloud(self):
        for lang, forbidden in (("en", ("Cloud Sync", "cloud sync")),
                                ("ja", ("クラウド同期",))):
            body = self._body("/sync", lang)
            for word in forbidden:
                with self.subTest(lang=lang, word=word):
                    self.assertNotIn(word, body)

    def test_page_says_what_it_actually_does(self):
        self.assertIn("Create Backup", self._body("/sync", "en"))
        self.assertIn("バックアップを作成", self._body("/sync", "ja"))

    def test_page_states_that_nothing_leaves_the_machine(self):
        """プライバシーについては黙っているのでなく、明示的に安心させる。"""
        self.assertIn("Nothing is sent anywhere", self._body("/sync", "en"))
        self.assertIn("外部へ送信されることはありません", self._body("/sync", "ja"))

    def test_the_route_makes_no_network_call(self):
        """表示だけでなく実装もローカル完結であること（表示の裏取り）。"""
        import inspect
        source = inspect.getsource(dashboard.sync)
        source += inspect.getsource(dashboard._build_sync_backup)
        for forbidden in ("requests.", "urllib", "http.client", "socket.",
                          "boto3", "google.cloud"):
            with self.subTest(api=forbidden):
                self.assertNotIn(forbidden, source)
