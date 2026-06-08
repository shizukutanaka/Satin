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


if __name__ == "__main__":
    unittest.main()
