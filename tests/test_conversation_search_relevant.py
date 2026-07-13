"""
Unit tests for ConversationLog.search_relevant() — BM25 relevance ranking
over conversation history (research A4).

Unlike substring search(), search_relevant() must rank past utterances by
relevance so that different word orders / phrasings still recall the closest
memory (e.g. querying "楽しかった旅行" recalls "旅行が楽しかった"), and it
must return nothing for a zero-relevance query.
"""
import gzip
import json
import os
import sys
import tempfile
import time
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from conversation_log import (  # noqa: E402
    ConversationLog,
    _tokenize_for_retrieval,
    _bm25_scores,
)


def _make_log(tmp: str) -> ConversationLog:
    path = os.path.join(tmp, "test_log.jsonl")
    return ConversationLog(logfile=path)


def _write_event(logfile: str, event_type: str, text: str, ts: float = None):
    entry = {
        "event_type": event_type,
        "timestamp": ts if ts is not None else time.time(),
        "details": {"text": text},
    }
    with open(logfile, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


class TokenizeTests(unittest.TestCase):
    def test_ascii_words_lowercased(self):
        self.assertEqual(_tokenize_for_retrieval("Machine LEARNING"),
                         ["machine", "learning"])

    def test_cjk_split_into_char_bigrams(self):
        # 3 文字 → 2 バイグラム
        self.assertEqual(_tokenize_for_retrieval("旅行日"), ["旅行", "行日"])

    def test_single_cjk_char_kept(self):
        self.assertEqual(_tokenize_for_retrieval("猫"), ["猫"])

    def test_mixed_ascii_and_cjk(self):
        toks = _tokenize_for_retrieval("Python が好き")
        self.assertIn("python", toks)
        self.assertIn("が好", toks)

    def test_empty_text_returns_empty(self):
        self.assertEqual(_tokenize_for_retrieval(""), [])


class Bm25Tests(unittest.TestCase):
    def test_no_docs_returns_empty(self):
        self.assertEqual(_bm25_scores(["a"], []), [])

    def test_empty_query_scores_all_zero(self):
        self.assertEqual(_bm25_scores([], [["a"], ["b"]]), [0.0, 0.0])

    def test_matching_doc_scores_higher_than_non_matching(self):
        docs = [["machine", "learning"], ["cooking", "recipe"]]
        scores = _bm25_scores(["machine"], docs)
        self.assertGreater(scores[0], scores[1])
        self.assertEqual(scores[1], 0.0)

    def test_idf_never_negative(self):
        # 全文書に出現する語は idf<=0 になりうるが 0 で下限クリップ
        docs = [["x"], ["x"], ["x"]]
        scores = _bm25_scores(["x"], docs)
        for s in scores:
            self.assertGreaterEqual(s, 0.0)


class SearchRelevantEmptyTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._log = _make_log(self._tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_missing_file_returns_empty(self):
        self.assertEqual(self._log.search_relevant("hello"), [])

    def test_empty_query_returns_empty(self):
        self._log.log_user_comment("hello world")
        self.assertEqual(self._log.search_relevant(""), [])

    def test_whitespace_query_returns_empty(self):
        self._log.log_user_comment("hello world")
        self.assertEqual(self._log.search_relevant("   "), [])

    def test_no_relevant_match_returns_empty(self):
        self._log.log_user_comment("I love machine learning")
        self._log.log_avatar_reply("cooking is fun")
        self.assertEqual(self._log.search_relevant("quantum physics"), [])


class SearchRelevantRankingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._log = _make_log(self._tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_word_order_difference_recalled(self):
        """substring search cannot match across word order; BM25 must."""
        self._log.log_user_comment("旅行が楽しかった")
        self._log.log_user_comment("今日は雨だった")
        result = self._log.search_relevant("楽しかった旅行", n=5)
        self.assertTrue(result)
        self.assertEqual(result[0]["details"]["text"], "旅行が楽しかった")

    def test_more_relevant_ranked_first(self):
        self._log.log_user_comment("machine learning is hard")
        self._log.log_user_comment("machine learning and deep learning research")
        self._log.log_user_comment("cooking dinner tonight")
        result = self._log.search_relevant("machine learning research", n=5)
        # 「research」も一致する 2 番目の発話が最上位
        self.assertEqual(result[0]["details"]["text"],
                         "machine learning and deep learning research")

    def test_zero_score_docs_excluded(self):
        self._log.log_user_comment("apple banana")
        self._log.log_user_comment("orange grape")
        result = self._log.search_relevant("apple", n=5)
        texts = [r["details"]["text"] for r in result]
        self.assertIn("apple banana", texts)
        self.assertNotIn("orange grape", texts)

    def test_n_limits_results(self):
        for i in range(5):
            self._log.log_user_comment(f"machine learning topic {i}")
        result = self._log.search_relevant("machine learning", n=2)
        self.assertEqual(len(result), 2)

    def test_n_zero_returns_all_relevant(self):
        for i in range(5):
            self._log.log_user_comment(f"machine learning topic {i}")
        result = self._log.search_relevant("machine learning", n=0)
        self.assertEqual(len(result), 5)

    def test_ties_preserve_chronological_order(self):
        # 同一本文なら BM25 スコアも同点 → 古い順が保たれる
        self._log.log_user_comment("hello", )
        time.sleep(0.001)
        self._log.log_avatar_reply("hello")
        result = self._log.search_relevant("hello", n=5)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["event_type"], "user_comment")
        self.assertEqual(result[1]["event_type"], "avatar_reply")

    def test_non_conversation_events_excluded(self):
        _write_event(self._log.logfile, "system_event", "machine learning status")
        _write_event(self._log.logfile, "user_comment", "machine learning talk")
        result = self._log.search_relevant("machine learning", n=5)
        for ev in result:
            self.assertIn(ev["event_type"], ("user_comment", "avatar_reply"))

    def test_legacy_aliases_matched(self):
        _write_event(self._log.logfile, "user", "machine learning")
        _write_event(self._log.logfile, "avatar", "machine learning too")
        result = self._log.search_relevant("machine learning", n=5)
        self.assertEqual(len(result), 2)


class SearchRelevantArchiveTests(unittest.TestCase):
    """search_relevant() must transparently include rotated .gz archives."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._log = _make_log(self._tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write_gz_archive(self, filename, events):
        gz_path = os.path.join(self._tmp, filename)
        with gzip.open(gz_path, "wt", encoding="utf-8") as fh:
            for ev in events:
                fh.write(json.dumps(ev) + "\n")
        return gz_path

    def test_archived_events_included(self):
        gz_name = os.path.basename(self._log.logfile) + ".20260101_000000.gz"
        self._write_gz_archive(gz_name, [{
            "event_type": "user_comment",
            "timestamp": 1000.0,
            "details": {"text": "archived machine learning note"},
        }])
        self._log.log_user_comment("live cooking note")
        result = self._log.search_relevant("machine learning", n=5)
        texts = [r["details"]["text"] for r in result]
        self.assertIn("archived machine learning note", texts)

    def test_include_archives_false_omits_gz(self):
        gz_name = os.path.basename(self._log.logfile) + ".20260101_000000.gz"
        self._write_gz_archive(gz_name, [{
            "event_type": "user_comment",
            "timestamp": 1000.0,
            "details": {"text": "only in archive machine learning"},
        }])
        result = self._log.search_relevant("machine learning", n=5,
                                           include_archives=False)
        self.assertEqual(result, [])


class SearchRelevantRobustnessTests(unittest.TestCase):
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
                "details": {"text": "machine learning here"},
            }) + "\n")
        result = self._log.search_relevant("machine learning")
        self.assertEqual(len(result), 1)

    def test_blank_lines_skipped(self):
        self._log.log_user_comment("machine learning")
        with open(self._log.logfile, "a") as f:
            f.write("\n\n")
        result = self._log.search_relevant("machine learning")
        self.assertEqual(len(result), 1)

    def test_missing_text_field_does_not_crash(self):
        _write_event(self._log.logfile, "user_comment", "machine learning")
        with open(self._log.logfile, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "event_type": "user_comment",
                "timestamp": time.time(),
                "details": {},
            }) + "\n")
        result = self._log.search_relevant("machine learning")
        self.assertEqual(len(result), 1)


if __name__ == "__main__":
    unittest.main()
