"""
Unit tests for paper_integrator — AcademicPaper serialisation and
PaperIntegrator helper logic (no real network calls).

Tests cover:
  - AcademicPaper.to_dict()     (datetime serialisation, None passthrough)
  - PaperIntegrator.search_arxiv()        (missing lib → empty list)
  - PaperIntegrator.search_google_scholar() (missing lib + year filtering)
  - lookup helpers (get_paper_by_doi, get_paper_with_full_text)
"""
import os
import sys
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

import paper_integrator as _pi  # noqa: E402
from paper_integrator import AcademicPaper, PaperIntegrator  # noqa: E402


# ---------------------------------------------------------------------------
# AcademicPaper serialisation
# ---------------------------------------------------------------------------

class AcademicPaperToDictTests(unittest.TestCase):

    def _make(self, **kwargs):
        defaults = dict(
            paper_id="2401.00001",
            title="Test Paper",
            abstract="An abstract.",
            authors=["Alice", "Bob"],
            published_date=datetime(2024, 1, 15),
            url="https://example.com/paper",
            source="arxiv",
        )
        defaults.update(kwargs)
        return AcademicPaper(**defaults)

    def test_published_date_serialised_to_isoformat(self):
        p = self._make(published_date=datetime(2024, 1, 15, 12, 30))
        d = p.to_dict()
        self.assertIsInstance(d["published_date"], str)
        self.assertEqual(d["published_date"], "2024-01-15T12:30:00")

    def test_none_published_date_stays_none(self):
        p = self._make(published_date=None)
        d = p.to_dict()
        self.assertIsNone(d["published_date"])

    def test_scalar_fields_preserved(self):
        p = self._make()
        d = p.to_dict()
        self.assertEqual(d["paper_id"], "2401.00001")
        self.assertEqual(d["title"], "Test Paper")
        self.assertEqual(d["source"], "arxiv")
        self.assertEqual(d["abstract"], "An abstract.")

    def test_authors_list_preserved(self):
        p = self._make(authors=["Alice", "Bob", "Carol"])
        d = p.to_dict()
        self.assertEqual(d["authors"], ["Alice", "Bob", "Carol"])

    def test_keywords_default_empty_list(self):
        p = self._make()
        d = p.to_dict()
        self.assertEqual(d["keywords"], [])

    def test_keywords_list_preserved(self):
        p = self._make(keywords=["AI", "NLP"])
        d = p.to_dict()
        self.assertEqual(d["keywords"], ["AI", "NLP"])

    def test_citations_default_zero(self):
        p = self._make()
        d = p.to_dict()
        self.assertEqual(d["citations"], 0)

    def test_doi_default_none(self):
        p = self._make()
        d = p.to_dict()
        self.assertIsNone(d["doi"])

    def test_full_text_default_none(self):
        p = self._make()
        d = p.to_dict()
        self.assertIsNone(d["full_text"])

    def test_to_dict_returns_new_dict_each_call(self):
        p = self._make()
        d1 = p.to_dict()
        d2 = p.to_dict()
        self.assertIsNot(d1, d2)
        d1["title"] = "CHANGED"
        self.assertEqual(d2["title"], "Test Paper")


# ---------------------------------------------------------------------------
# PaperIntegrator — missing library fallback
# ---------------------------------------------------------------------------

class SearchArxivMissingLibTests(unittest.TestCase):

    def test_returns_empty_list_when_arxiv_unavailable(self):
        with patch.object(_pi, "_arxiv_lib", None):
            integrator = PaperIntegrator()
            result = integrator.search_arxiv("deep learning")
        self.assertEqual(result, [])

    def test_no_exception_when_arxiv_unavailable(self):
        with patch.object(_pi, "_arxiv_lib", None):
            integrator = PaperIntegrator()
            # Should not raise
            integrator.search_arxiv("any query")


class SearchScholarMissingLibTests(unittest.TestCase):

    def test_returns_empty_list_when_scholarly_unavailable(self):
        with patch.object(_pi, "_scholarly_lib", None):
            integrator = PaperIntegrator()
            result = integrator.search_google_scholar("transformer")
        self.assertEqual(result, [])

    def test_no_exception_when_scholarly_unavailable(self):
        with patch.object(_pi, "_scholarly_lib", None):
            integrator = PaperIntegrator()
            integrator.search_google_scholar("any query")


# ---------------------------------------------------------------------------
# PaperIntegrator — Google Scholar year filtering (mocked lib)
# ---------------------------------------------------------------------------

def _make_scholar_result(title: str, year=None, url_scholarbib=None, pub_url=""):
    """Build a minimal scholarly result dict."""
    bib = {"title": title, "abstract": "", "author": []}
    if year is not None:
        bib["pub_year"] = str(year)
    return {
        "bib": bib,
        "url_scholarbib": url_scholarbib or title,
        "pub_url": pub_url,
        "num_citations": 0,
    }


class ScholarYearFilterTests(unittest.TestCase):

    def _run(self, results_iter, **kwargs):
        mock_lib = MagicMock()
        mock_lib.search_pubs.return_value = iter(results_iter)
        with patch.object(_pi, "_scholarly_lib", mock_lib):
            return PaperIntegrator().search_google_scholar("q", **kwargs)

    def test_no_filter_returns_all(self):
        results = self._run([
            _make_scholar_result("Paper A", year=2019),
            _make_scholar_result("Paper B", year=2022),
            _make_scholar_result("Paper C", year=2025),
        ])
        self.assertEqual(len(results), 3)

    def test_year_low_excludes_older_papers(self):
        results = self._run([
            _make_scholar_result("Old", year=2018),
            _make_scholar_result("New", year=2022),
        ], year_low=2020)
        titles = [p.title for p in results]
        self.assertNotIn("Old", titles)
        self.assertIn("New", titles)

    def test_year_high_excludes_newer_papers(self):
        results = self._run([
            _make_scholar_result("Early", year=2019),
            _make_scholar_result("Late", year=2025),
        ], year_high=2023)
        titles = [p.title for p in results]
        self.assertIn("Early", titles)
        self.assertNotIn("Late", titles)

    def test_year_range_both_bounds(self):
        results = self._run([
            _make_scholar_result("Before", year=2018),
            _make_scholar_result("In range", year=2021),
            _make_scholar_result("After", year=2025),
        ], year_low=2020, year_high=2023)
        titles = [p.title for p in results]
        self.assertNotIn("Before", titles)
        self.assertIn("In range", titles)
        self.assertNotIn("After", titles)

    def test_boundary_year_low_inclusive(self):
        """Papers from exactly year_low must be included."""
        results = self._run([
            _make_scholar_result("Exact", year=2020),
        ], year_low=2020)
        self.assertEqual(len(results), 1)

    def test_boundary_year_high_inclusive(self):
        """Papers from exactly year_high must be included."""
        results = self._run([
            _make_scholar_result("Exact", year=2023),
        ], year_high=2023)
        self.assertEqual(len(results), 1)

    def test_paper_without_year_passes_year_filter(self):
        """Papers with no publication year pass through any year filter."""
        results = self._run([
            _make_scholar_result("No year"),
        ], year_low=2020, year_high=2023)
        # Current behaviour: no-year papers are NOT excluded by the year filter.
        self.assertEqual(len(results), 1)

    def test_max_results_respected(self):
        results = self._run([
            _make_scholar_result(f"Paper {i}", year=2020) for i in range(20)
        ], max_results=5)
        self.assertLessEqual(len(results), 5)

    def test_published_date_set_for_valid_year(self):
        results = self._run([_make_scholar_result("P", year=2022)])
        self.assertIsNotNone(results[0].published_date)
        self.assertEqual(results[0].published_date.year, 2022)

    def test_published_date_none_when_year_absent(self):
        results = self._run([_make_scholar_result("P")])
        self.assertIsNone(results[0].published_date)

    def test_published_date_none_for_year_zero(self):
        """year=0 is out of Python datetime range → published_date must be None."""
        results = self._run([_make_scholar_result("P", year=0)])
        self.assertIsNone(results[0].published_date)

    def test_invalid_year_string_does_not_crash(self):
        """Non-numeric pub_year must be handled gracefully."""
        raw = _make_scholar_result("P")
        raw["bib"]["pub_year"] = "unknown"
        results = self._run([raw])
        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0].published_date)

    def test_source_set_to_scholar(self):
        results = self._run([_make_scholar_result("P", year=2021)])
        self.assertEqual(results[0].source, "scholar")


# ---------------------------------------------------------------------------
# PaperIntegrator — trivial stubs
# ---------------------------------------------------------------------------

class TrivialStubTests(unittest.TestCase):

    def test_get_paper_by_doi_returns_none(self):
        p = PaperIntegrator()
        self.assertIsNone(p.get_paper_by_doi("10.1000/xyz123"))

    def test_get_paper_with_full_text_returns_same_paper(self):
        paper = AcademicPaper(
            paper_id="1", title="T", abstract="A", authors=[],
            published_date=None, url="", source="arxiv",
        )
        p = PaperIntegrator()
        result = p.get_paper_with_full_text(paper)
        self.assertIs(result, paper)


if __name__ == "__main__":
    unittest.main()
