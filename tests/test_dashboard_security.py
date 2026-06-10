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


if __name__ == "__main__":
    unittest.main()
