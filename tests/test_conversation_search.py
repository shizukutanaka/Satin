"""
Unit tests for ConversationLog.search() — keyword search over conversation history.
"""
import json
import os
import sys
import tempfile
import time
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import conversation_log as cl_mod  # noqa: E402
from conversation_log import ConversationLog  # noqa: E402


def _make_log(tmp: str) -> ConversationLog:
    path = os.path.join(tmp, "test_log.jsonl")
    return ConversationLog(logfile=path)


def _write_event(logfile: str, event_type: str, text: str, ts: float = None):
    entry = {
        "event_type": event_type,
        "timestamp": ts or time.time(),
        "details": {"text": text},
    }
    with open(logfile, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


class SearchEmptyTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._log = _make_log(self._tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_missing_file_returns_empty(self):
        result = self._log.search("hello")
        self.assertEqual(result, [])

    def test_empty_query_returns_all_events(self):
        self._log.log_user_comment("hello world")
        self._log.log_avatar_reply("hi there")
        result = self._log.search("")
        self.assertEqual(len(result), 2)

    def test_empty_log_returns_empty(self):
        open(self._log.logfile, "w").close()
        result = self._log.search("anything")
        self.assertEqual(result, [])


class SearchMatchTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._log = _make_log(self._tmp)
        self._log.log_user_comment("I love machine learning")
        self._log.log_avatar_reply("machine learning is fascinating")
        self._log.log_user_comment("let us talk about cooking")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_keyword_match_returns_matching_events(self):
        result = self._log.search("machine learning")
        self.assertEqual(len(result), 2)

    def test_no_match_returns_empty(self):
        result = self._log.search("quantum physics")
        self.assertEqual(result, [])

    def test_case_insensitive_match(self):
        result = self._log.search("MACHINE LEARNING")
        self.assertEqual(len(result), 2)

    def test_partial_match_works(self):
        result = self._log.search("cooking")
        self.assertEqual(len(result), 1)
        text = result[0]["details"]["text"]
        self.assertIn("cooking", text)

    def test_results_ordered_oldest_first(self):
        result = self._log.search("")
        texts = [r["details"]["text"] for r in result]
        self.assertEqual(texts[0], "I love machine learning")
        self.assertEqual(texts[-1], "let us talk about cooking")

    def test_non_conversation_events_excluded(self):
        _write_event(self._log.logfile, "system_event", "machine learning status")
        result = self._log.search("machine learning")
        for ev in result:
            self.assertIn(ev["event_type"], ("user_comment", "avatar_reply"))


class SearchLimitTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._log = _make_log(self._tmp)
        for i in range(10):
            self._log.log_user_comment(f"message {i}")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_n_limits_results(self):
        result = self._log.search("message", n=3)
        self.assertEqual(len(result), 3)

    def test_n_zero_returns_all(self):
        result = self._log.search("message", n=0)
        self.assertEqual(len(result), 10)

    def test_n_larger_than_matches_returns_all_matches(self):
        result = self._log.search("message", n=100)
        self.assertEqual(len(result), 10)

    def test_n_limit_takes_newest(self):
        result = self._log.search("message", n=2)
        texts = [r["details"]["text"] for r in result]
        self.assertIn("message 9", texts)
        self.assertIn("message 8", texts)


class SearchRobustnessTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._log = _make_log(self._tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_corrupt_lines_skipped(self):
        with open(self._log.logfile, "w") as f:
            f.write("{ not valid json }\n")
            f.write(json.dumps({
                "event_type": "user_comment",
                "timestamp": time.time(),
                "details": {"text": "hello"},
            }) + "\n")
        result = self._log.search("hello")
        self.assertEqual(len(result), 1)

    def test_blank_lines_skipped(self):
        self._log.log_user_comment("test")
        with open(self._log.logfile, "a") as f:
            f.write("\n\n")
        result = self._log.search("test")
        self.assertEqual(len(result), 1)


class SearchLegacyAliasTests(unittest.TestCase):
    """search() must recognize legacy 'user'/'avatar' event aliases, matching
    the shared USER_EVENT_TYPES/AVATAR_EVENT_TYPES used elsewhere — otherwise
    it silently drops legacy conversation events the dashboard would show."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._log = _make_log(self._tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_legacy_user_alias_matched(self):
        _write_event(self._log.logfile, "user", "hello world")
        result = self._log.search("hello")
        self.assertEqual(len(result), 1)

    def test_legacy_avatar_alias_matched(self):
        _write_event(self._log.logfile, "avatar", "greetings")
        result = self._log.search("greetings")
        self.assertEqual(len(result), 1)

    def test_canonical_and_legacy_both_counted(self):
        _write_event(self._log.logfile, "user_comment", "apple")
        _write_event(self._log.logfile, "user", "apple")
        _write_event(self._log.logfile, "avatar_reply", "apple")
        _write_event(self._log.logfile, "avatar", "apple")
        result = self._log.search("apple")
        self.assertEqual(len(result), 4)

    def test_non_conversation_event_still_excluded(self):
        _write_event(self._log.logfile, "system_tick", "apple")
        result = self._log.search("apple")
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
