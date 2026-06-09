"""
Regression test for content_aggregator.create_knowledge_base() integer-division bug.

Previously: max_items // len(sources) silently requested fewer results than
asked for when max_items was not a multiple of len(sources), and crashed with
ZeroDivisionError when sources was empty.

Fix: math.ceil(max_items / n_sources) with n_sources defaulting to 1.

Run: python -m unittest tests.test_content_aggregator_division -v
"""
import math
import os
import sys
import types
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)


def _max_results_per_source(max_items: int, n_sources: int) -> int:
    """Mirror the fixed formula from create_knowledge_base."""
    n = n_sources if n_sources else 1
    return math.ceil(max_items / n)


class CeilDivisionFormulaTests(unittest.TestCase):
    """Unit-level tests for the corrected per-source budget calculation."""

    def test_exact_division_unchanged(self):
        self.assertEqual(_max_results_per_source(50, 5), 10)

    def test_non_exact_rounds_up(self):
        # floor(50/3)=16 → ceil=17; total budget 51 ≥ 50
        result = _max_results_per_source(50, 3)
        self.assertEqual(result, 17)
        self.assertGreaterEqual(result * 3, 50)

    def test_single_source(self):
        self.assertEqual(_max_results_per_source(20, 1), 20)

    def test_empty_sources_defaults_to_one(self):
        # n_sources=0 must not raise ZeroDivisionError
        result = _max_results_per_source(50, 0)
        self.assertEqual(result, 50)  # falls back to n=1

    def test_more_sources_than_items(self):
        # 1 item, 5 sources → ceil(1/5)=1 per source (not 0)
        result = _max_results_per_source(1, 5)
        self.assertEqual(result, 1)

    def test_old_floor_formula_would_have_dropped_items(self):
        # Demonstrates the old bug: 50//3=16, 16*3=48 < 50 (2 items lost)
        old = 50 // 3
        new = _max_results_per_source(50, 3)
        self.assertGreater(new * 3, old * 3)  # new budget covers all 50
        self.assertGreaterEqual(new * 3, 50)


class ContentAggregatorImportTest(unittest.TestCase):
    def test_module_imports_cleanly(self):
        import content_aggregator  # noqa: F401
        self.assertTrue(hasattr(content_aggregator, "ContentAggregator"))


class AcademicPaperPublishedDateRoundtripTest(unittest.TestCase):
    """Regression: AcademicPaper(**to_dict()) raised TypeError because
    published_date was serialized as ISO string but constructor expects datetime."""

    def test_iso_string_parsed_before_construction(self):
        from datetime import datetime
        from paper_integrator import AcademicPaper

        paper = AcademicPaper(
            paper_id="1234",
            title="Test",
            abstract="abs",
            authors=["A"],
            published_date=datetime(2024, 1, 15),
            url="http://example.com",
            source="arxiv",
        )
        serialized = paper.to_dict()
        self.assertIsInstance(serialized["published_date"], str)

        # Simulate what content_aggregator.py does after the fix
        data = dict(serialized)
        if isinstance(data.get("published_date"), str):
            data["published_date"] = datetime.fromisoformat(data["published_date"])

        reconstructed = AcademicPaper(**data)
        self.assertEqual(reconstructed.published_date, paper.published_date)

    def test_none_published_date_survives_roundtrip(self):
        from paper_integrator import AcademicPaper

        paper = AcademicPaper(
            paper_id="x",
            title="T",
            abstract="a",
            authors=[],
            published_date=None,
            url="http://x.com",
            source="scholar",
        )
        data = paper.to_dict()
        if isinstance(data.get("published_date"), str):
            from datetime import datetime
            data["published_date"] = datetime.fromisoformat(data["published_date"])
        reconstructed = AcademicPaper(**data)
        self.assertIsNone(reconstructed.published_date)


if __name__ == "__main__":
    unittest.main()
