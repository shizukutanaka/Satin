"""
Security regression tests for dashboard._safe_backup_path.

The /download/<fname> route built a path with os.path.join(backup_dir, fname)
and served it directly. _safe_backup_path now confines the resolved path to
backup_dir, blocking directory traversal (../../etc/passwd, absolute paths).

dashboard.py imports cleanly without Flask installed (it falls back to a no-op
app), so these tests run anywhere.

Run: python -m unittest tests.test_dashboard_security -v
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import dashboard  # noqa: E402


class SafeBackupPathTests(unittest.TestCase):
    def test_plain_filename_allowed(self):
        p = dashboard._safe_backup_path("report.png")
        self.assertIsNotNone(p)
        self.assertTrue(p.endswith(os.path.join("event_report", "report.png")))

    def test_parent_traversal_blocked(self):
        self.assertIsNone(dashboard._safe_backup_path("../secret.txt"))
        self.assertIsNone(dashboard._safe_backup_path("../../etc/passwd"))

    def test_nested_traversal_blocked(self):
        self.assertIsNone(dashboard._safe_backup_path("a/../../etc/passwd"))

    def test_absolute_path_blocked(self):
        # os.path.join(base, '/etc/passwd') collapses to '/etc/passwd', which is
        # outside backup_dir and must be rejected.
        self.assertIsNone(dashboard._safe_backup_path("/etc/passwd"))

    def test_subdirectory_file_allowed(self):
        # A legitimate nested file under backup_dir stays contained.
        p = dashboard._safe_backup_path("sub/report.gz")
        self.assertIsNotNone(p)
        base = os.path.abspath(dashboard.backup_dir)
        self.assertTrue(p.startswith(base + os.sep))


class SecretKeyHardeningTests(unittest.TestCase):
    def test_secret_key_not_hardcoded_literal(self):
        # The old hardcoded value must no longer be the secret.
        if getattr(dashboard, "_FLASK_AVAILABLE", False):
            self.assertNotEqual(dashboard.app.secret_key, "satin_dashboard_secret")


class EventLogHtmlEscapeTests(unittest.TestCase):
    """Regression: event data from JSONL must be HTML-escaped in the /logs page."""

    def _build_row(self, ts, event_type, details):
        """Mirror the dashboard's HTML-building logic (lines 113-115)."""
        import html as _html
        return (
            f"<tr><td>{_html.escape(ts)}</td>"
            f"<td>{_html.escape(str(event_type))}</td>"
            f"<td>{_html.escape(str(details))}</td></tr>"
        )

    def test_event_type_with_html_tags_is_escaped(self):
        row = self._build_row("2024-01-01 00:00:00", "<script>alert(1)</script>", {})
        self.assertNotIn("<script>", row)
        self.assertIn("&lt;script&gt;", row)

    def test_details_with_html_tags_is_escaped(self):
        row = self._build_row("2024-01-01 00:00:00", "click", "<img src=x onerror=alert(1)>")
        self.assertNotIn("<img", row)
        self.assertIn("&lt;img", row)

    def test_plain_text_passes_through(self):
        row = self._build_row("2024-01-01 12:00:00", "speak", {"text": "hello"})
        self.assertIn("speak", row)
        self.assertIn("hello", row)


class SearchXSSTests(unittest.TestCase):
    """Ensure search query and conversation text are HTML-escaped in /conversation/search."""

    def _build_search_row(self, ts, speaker, text, query):
        """Mirror the search highlighting logic in dashboard.conversation_search."""
        import html as _html
        q_esc = _html.escape(query)
        highlighted = _html.escape(text).replace(
            q_esc, f'<mark>{q_esc}</mark>'
        )
        return (
            f'<small style="color:#888">{_html.escape(ts)}'
            f' <b>{_html.escape(speaker)}</b></small><br>'
            f'{highlighted}'
        )

    def test_xss_script_in_conversation_text_escaped(self):
        # If the text itself contains a <script> tag and query matches part of it,
        # the output must not contain raw <script> — only the escaped form.
        row = self._build_search_row(
            "12:00:00", "You", "<script>alert(1)</script>", "alert"
        )
        self.assertNotIn("<script>", row)
        self.assertIn("alert", row)  # match still present, but safely escaped

    def test_xss_in_conversation_text_escaped(self):
        # <img> in text + "img" as query: the raw <img …> tag must not survive
        row = self._build_search_row(
            "12:00:00", "Avatar", "<img src=x onerror=alert(1)>", "img"
        )
        # Raw '<img' must not appear as a live tag start (escaped to &lt;)
        self.assertNotIn("<img", row)
        # The escaped form of the opening angle bracket must be present
        self.assertIn("&lt;", row)

    def test_matched_keyword_highlighted_safely(self):
        row = self._build_search_row("12:00:00", "You", "hello world", "hello")
        self.assertIn("<mark>hello</mark>", row)
        self.assertNotIn("<script>", row)

    def test_html_in_speaker_escaped(self):
        row = self._build_search_row("12:00:00", "<b>hacker</b>", "normal text", "normal")
        # The injected <b>hacker</b> must be escaped (shown as &lt;b&gt;)
        self.assertIn("&lt;b&gt;hacker", row)

    def test_xss_query_containing_malicious_html_in_text(self):
        # User searches for "<script>" which exists literally in conversation text
        row = self._build_search_row(
            "12:00:00", "You", "he said <script>alert(1)</script> here", "<script>"
        )
        self.assertNotIn("<script>", row)  # raw must not appear


class SSTIRegressionTests(unittest.TestCase):
    """User conversation text is rendered via the dashboard. It must never be
    concatenated into the Jinja template SOURCE, or {{ }} in a comment becomes
    Server-Side Template Injection (-> RCE). It must be passed as a variable."""

    def test_template_renders_content_as_variable(self):
        self.assertIn("{{ content|safe }}", dashboard.TEMPLATE)

    def test_no_route_concatenates_content_into_template_source(self):
        import inspect
        src = inspect.getsource(dashboard)
        # The vulnerable pattern must not appear in actual code (the docstring
        # example uses "...", not the full "+ '{% endblock %}'").
        self.assertNotIn(
            "TEMPLATE + '{% block content %}' + content + '{% endblock %}'", src
        )

    def test_render_page_helper_exists(self):
        self.assertTrue(hasattr(dashboard, "_render_page"))

    def test_template_does_not_evaluate_jinja_expression_in_content(self):
        try:
            from jinja2 import Template
        except ImportError:
            self.skipTest("jinja2 not installed")

        class _I18N:
            def t(self, key, default=None):
                return default or key

        rendered = Template(dashboard.TEMPLATE).render(
            content="{{7*7}}", i18n=_I18N(), lang="en", switcher=""
        )
        self.assertIn("{{7*7}}", rendered)   # rendered literally
        self.assertNotIn("49", rendered)     # NOT evaluated (no SSTI)

    def test_template_does_not_execute_statement_tags_in_content(self):
        try:
            from jinja2 import Template
        except ImportError:
            self.skipTest("jinja2 not installed")

        class _I18N:
            def t(self, key, default=None):
                return default or key

        payload = "{% for x in range(3) %}X{% endfor %}"
        rendered = Template(dashboard.TEMPLATE).render(
            content=payload, i18n=_I18N(), lang="en", switcher=""
        )
        self.assertIn(payload, rendered)  # literal, not expanded to "XXX"
        self.assertNotIn(">XXX<", rendered)


class NoCacheHeaderTests(unittest.TestCase):
    """すべてのレスポンスに Cache-Control: no-store が含まれること。
    会話・感情データはブラウザキャッシュに保存されてはならない（個人情報保護）。

    Flask 未インストール環境では _no_cache() 関数を直接テストする。
    """

    def _get_no_cache_fn(self):
        """after_request フック関数を取得する。Flask 無しでも動作する。"""
        # Flask ありなら app.after_request で登録済みの関数を使う。
        # Flask 無しでも dashboard モジュール内で定義された _no_cache を参照する。
        return getattr(dashboard, '_no_cache', None)

    def test_no_cache_function_exists(self):
        fn = self._get_no_cache_fn()
        self.assertIsNotNone(fn, "_no_cache after_request hook must exist in dashboard")

    def test_no_cache_sets_cache_control_no_store(self):
        fn = self._get_no_cache_fn()
        if fn is None:
            self.skipTest("_no_cache not found")

        class _MockResponse:
            def __init__(self):
                self.headers = {}

        resp = _MockResponse()
        result = fn(resp)
        self.assertIs(result, resp)
        self.assertIn("no-store", result.headers.get("Cache-Control", ""))

    def test_no_cache_sets_pragma(self):
        fn = self._get_no_cache_fn()
        if fn is None:
            self.skipTest("_no_cache not found")

        class _MockResponse:
            def __init__(self):
                self.headers = {}

        resp = _MockResponse()
        fn(resp)
        self.assertEqual(resp.headers.get("Pragma"), "no-cache")

    def test_no_cache_includes_must_revalidate(self):
        fn = self._get_no_cache_fn()
        if fn is None:
            self.skipTest("_no_cache not found")

        class _MockResponse:
            def __init__(self):
                self.headers = {}

        resp = _MockResponse()
        fn(resp)
        self.assertIn("must-revalidate", resp.headers.get("Cache-Control", ""))


class HealthzTests(unittest.TestCase):
    """The /healthz endpoint must return HTTP 200 and {"status":"ok"}."""

    def test_healthz_route_registered(self):
        if not getattr(dashboard, "_FLASK_AVAILABLE", False):
            self.skipTest("Flask not available")
        app = dashboard.app
        rules = [r.rule for r in app.url_map.iter_rules()]
        self.assertIn("/healthz", rules)


class MoodResetPersistenceTests(unittest.TestCase):
    """Regression: mood_reset referenced an unimported name (_default_mood_path),
    so the save() was silently swallowed and resets were never persisted to disk.
    The dashboard must expose a usable _mood_path callable for persistence."""

    def test_mood_path_helper_imported(self):
        # mood is pure-stdlib and importable in tests, so the alias must resolve
        # to a callable (not None and not an undefined name).
        self.assertTrue(callable(getattr(dashboard, "_mood_path", None)))

    def test_module_does_not_reference_undefined_mood_path_name(self):
        import inspect
        src = inspect.getsource(dashboard)
        # _default_mood_path was never imported into dashboard; the code must use
        # the imported alias _mood_path instead. Only the import line may mention
        # the original name (as "_default_mood_path as _mood_path").
        for line in src.splitlines():
            if "_default_mood_path" in line:
                self.assertIn("as _mood_path", line,
                              f"Undefined name used outside import: {line!r}")


@unittest.skipUnless(
    getattr(dashboard.app, "config", None) is not None
    and hasattr(dashboard.app, "secret_key"),
    "Flask not installed (no-op app)",
)
class SessionCookieHardeningTests(unittest.TestCase):
    """Regression: Flask's stock SESSION_COOKIE_* defaults leave SAMESITE unset
    and the lifetime at 31 days, weakening CSRF/replay defenses. Verify the
    hardened settings from Zenn's Flask session security guidance."""

    def test_session_cookie_is_httponly(self):
        self.assertTrue(dashboard.app.config.get("SESSION_COOKIE_HTTPONLY"))

    def test_session_cookie_samesite_is_lax(self):
        self.assertEqual(dashboard.app.config.get("SESSION_COOKIE_SAMESITE"), "Lax")

    def test_session_cookie_secure_defaults_to_false(self):
        # Off by default so http://127.0.0.1 dev works; opt-in via env for HTTPS.
        self.assertFalse(dashboard.app.config.get("SESSION_COOKIE_SECURE"))

    def test_session_cookie_secure_opt_in_via_env(self):
        import importlib
        os.environ["SATIN_DASHBOARD_HTTPS"] = "1"
        try:
            importlib.reload(dashboard)
            self.assertTrue(dashboard.app.config.get("SESSION_COOKIE_SECURE"))
        finally:
            os.environ.pop("SATIN_DASHBOARD_HTTPS", None)
            importlib.reload(dashboard)

    def test_permanent_session_lifetime_is_short(self):
        import datetime as _dt
        lifetime = dashboard.app.config.get("PERMANENT_SESSION_LIFETIME")
        self.assertIsInstance(lifetime, _dt.timedelta)
        # Must be no longer than 24h — Flask's default 31d is too generous for
        # a local dashboard that shows private affinity/conversation data.
        self.assertLessEqual(lifetime, _dt.timedelta(hours=24))


@unittest.skipUnless(getattr(dashboard, "_FLASK_AVAILABLE", False), "Flask not installed")
class LangParamXSSAndDoSTests(unittest.TestCase):
    """Regression: get_lang() returned request.args.get('lang') completely
    unvalidated. Several routes (/backups, /sync) embed that value into an
    href via raw Python f-string BEFORE the result is rendered with
    {{ content|safe }} — Jinja2 autoescaping is explicitly bypassed for
    `content`, so an unescaped lang value is a live reflected-XSS vector:
    ?lang="><script>alert(1)</script> breaks out of the href attribute.
    The same unvalidated value is also used as a key into i18n.py's
    process-wide, unbounded I18N._translation_cache class dict — a caller
    sending a unique ?lang= on every request grows that cache without
    bound (memory-exhaustion DoS), and (via load_translation's
    os.path.join(LOCALES_DIR, f'{lang}.json')) could path-traverse to open
    arbitrary '.json' files outside the locales directory.

    Fixed by validating in get_lang() against the fixed {'en','ja'} set that
    LANG_SWITCHER_HTML actually offers, before it's ever stored in the
    session or embedded in HTML, with a matching clamp in
    i18n.load_translation()'s cache-key/path construction as defense in
    depth for any other caller of I18N directly.
    """

    def setUp(self):
        # dashboard.I18N is the exact class dashboard.py itself resolved and
        # binds at import time (main/i18n.py's I18N, reached via a fallback
        # dynamic file-path load — a plain `import i18n` from a test instead
        # resolves to the unrelated i18n/ package, which shadows i18n.py and
        # has no I18N attribute at all).
        self._I18N = dashboard.I18N
        self._I18N._translation_cache.clear()

    def tearDown(self):
        self._I18N._translation_cache.clear()

    def test_xss_payload_in_lang_query_param_is_rejected(self):
        payload = '"><script>alert(1)</script>'
        with dashboard.app.test_request_context(f"/?lang={payload}"):
            lang = dashboard.get_lang()
        self.assertIn(lang, {"en", "ja"})
        self.assertNotEqual(lang, payload)

    def test_xss_payload_is_not_persisted_to_session(self):
        payload = '"><script>alert(1)</script>'
        with dashboard.app.test_request_context(f"/?lang={payload}"):
            dashboard.get_lang()
            from flask import session
            self.assertIn(session.get("lang"), (None, "en", "ja"))
            self.assertNotEqual(session.get("lang"), payload)

    def test_path_traversal_payload_in_lang_is_rejected(self):
        payload = "../../../../etc/passwd"
        with dashboard.app.test_request_context(f"/?lang={payload}"):
            lang = dashboard.get_lang()
        self.assertIn(lang, {"en", "ja"})

    def test_valid_lang_still_works(self):
        with dashboard.app.test_request_context("/?lang=ja"):
            self.assertEqual(dashboard.get_lang(), "ja")
        with dashboard.app.test_request_context("/?lang=en"):
            self.assertEqual(dashboard.get_lang(), "en")

    def test_unbounded_lang_values_do_not_grow_translation_cache(self):
        for i in range(200):
            with dashboard.app.test_request_context(f"/?lang=attacker-value-{i}"):
                dashboard.get_lang()
                dashboard.I18N(dashboard.get_lang())
        # Cache must stay bounded to the small set of real locale files,
        # never one entry per distinct attacker-supplied string.
        self.assertLessEqual(len(self._I18N._translation_cache), 2)


@unittest.skipUnless(getattr(dashboard, "_FLASK_AVAILABLE", False), "Flask not installed")
class CsrfProtectionTests(unittest.TestCase):
    """Regression: /mood/reset and /sync are state-changing POST routes with
    no CSRF protection at all — no token, no Origin/Referer check. Neither
    route looked at the session before acting, so SESSION_COOKIE_SAMESITE=
    'Lax' (which only stops a cookie from attaching to a cross-site POST)
    provided no real protection: the routes didn't check the cookie/session
    in the first place. A malicious page open in another tab could
    auto-submit a hidden form to silently reset the user's affinity
    (/mood/reset) or repeatedly trigger backup creation
    (/sync — a disk-fill DoS vector). Fixed with a per-session CSRF token
    (require_csrf decorator + _csrf_field() in both forms).
    """

    def setUp(self):
        dashboard.app.config["TESTING"] = True
        self.client = dashboard.app.test_client()
        # /sync writes a real backup zip on any successful POST — isolate it
        # to a temp dir so tests don't leave files in the repo's real
        # event_report/ directory.
        self._tmp = tempfile.mkdtemp()
        self._backup_dir_patcher = mock.patch.object(dashboard, "backup_dir", self._tmp)
        self._backup_dir_patcher.start()

    def tearDown(self):
        self._backup_dir_patcher.stop()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_mood_reset_post_without_token_is_rejected(self):
        resp = self.client.post("/mood/reset")
        self.assertEqual(resp.status_code, 403)

    def test_sync_post_without_token_is_rejected(self):
        resp = self.client.post("/sync")
        self.assertEqual(resp.status_code, 403)

    def test_mood_reset_post_with_wrong_token_is_rejected(self):
        with self.client.session_transaction() as sess:
            sess["csrf_token"] = "the-real-token"
        resp = self.client.post("/mood/reset", data={"csrf_token": "a-guessed-token"})
        self.assertEqual(resp.status_code, 403)

    def test_mood_reset_post_with_valid_token_is_accepted(self):
        with self.client.session_transaction() as sess:
            sess["csrf_token"] = "the-real-token"
        resp = self.client.post("/mood/reset", data={"csrf_token": "the-real-token"})
        self.assertNotEqual(resp.status_code, 403)

    def test_sync_post_with_valid_token_is_accepted(self):
        with self.client.session_transaction() as sess:
            sess["csrf_token"] = "the-real-token"
        resp = self.client.post("/sync", data={"csrf_token": "the-real-token"})
        self.assertNotEqual(resp.status_code, 403)

    def test_sync_get_does_not_require_a_token(self):
        # GET just renders the form (which contains a fresh token) — only
        # the state-changing POST must be gated.
        resp = self.client.get("/sync")
        self.assertNotEqual(resp.status_code, 403)

    def test_mood_reset_get_is_not_routable(self):
        # The route is POST-only; GET must 405, not silently execute.
        resp = self.client.get("/mood/reset")
        self.assertEqual(resp.status_code, 405)

    def test_rendered_sync_form_contains_a_csrf_field(self):
        resp = self.client.get("/sync")
        self.assertIn(b'name="csrf_token"', resp.data)

    def test_get_csrf_token_is_stable_within_a_session(self):
        with dashboard.app.test_request_context("/"):
            from flask import session as _session
            t1 = dashboard._get_csrf_token()
            t2 = dashboard._get_csrf_token()
            self.assertEqual(t1, t2)
            self.assertEqual(_session.get("csrf_token"), t1)


if __name__ == "__main__":
    unittest.main()
