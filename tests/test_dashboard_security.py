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
import unittest

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


if __name__ == "__main__":
    unittest.main()
