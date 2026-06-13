"""
Unit tests for code_quality_metrics — complexity analysis using stdlib AST.
"""
import os
import sys
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from code_quality_metrics import (  # noqa: E402
    ComplexityMetrics,
    ComplexityLevel,
    CodeQualityGrade,
    CodeComplexityAnalyzer,
    CodeSmellDetector,
    FileMetrics,
)
from pathlib import Path


# --------------------------------------------------------------------------- #
# Helper functions used as analysis targets
# --------------------------------------------------------------------------- #

def _simple():
    return 1


def _branchy(x, y, z):
    if x:
        if y:
            return 1
        elif z:
            return 2
        else:
            return 3
    else:
        return 4


def _loop_heavy(items):
    total = 0
    for item in items:
        if item > 0:
            total += item
        elif item < -10:
            total -= item
    return total


# --------------------------------------------------------------------------- #
# ComplexityMetrics unit tests
# --------------------------------------------------------------------------- #

class ComplexityMetricsTests(unittest.TestCase):
    def _make(self, cyclomatic=1, cognitive=1, loc=10, crap=1.0):
        return ComplexityMetrics(
            name="f",
            cyclomatic_complexity=cyclomatic,
            cognitive_complexity=cognitive,
            halstead_volume=10.0,
            lines_of_code=loc,
            lines_logical=loc,
            crap_index=crap,
            nested_depth=0,
        )

    def test_simple_complexity_level(self):
        m = self._make(cyclomatic=3)
        self.assertEqual(m.complexity_level, ComplexityLevel.SIMPLE)

    def test_moderate_complexity_level(self):
        m = self._make(cyclomatic=7)
        self.assertEqual(m.complexity_level, ComplexityLevel.MODERATE)

    def test_high_complexity_level(self):
        m = self._make(cyclomatic=11)
        self.assertEqual(m.complexity_level, ComplexityLevel.VERY_HIGH)

    def test_is_high_complexity_true(self):
        m = self._make(cyclomatic=11)  # VERY_HIGH
        self.assertTrue(m.is_high_complexity)

    def test_is_high_complexity_false(self):
        m = self._make(cyclomatic=3)  # SIMPLE
        self.assertFalse(m.is_high_complexity)

    def test_is_high_crap_true(self):
        m = self._make(crap=31.0)
        self.assertTrue(m.is_high_crap)

    def test_is_high_crap_false(self):
        m = self._make(crap=10.0)
        self.assertFalse(m.is_high_crap)


# --------------------------------------------------------------------------- #
# CodeComplexityAnalyzer.analyze_function
# --------------------------------------------------------------------------- #

class AnalyzeFunctionTests(unittest.TestCase):
    def test_simple_function_low_complexity(self):
        m = CodeComplexityAnalyzer.analyze_function(_simple)
        self.assertIsInstance(m, ComplexityMetrics)
        self.assertLessEqual(m.cyclomatic_complexity, 3)

    def test_branchy_function_higher_complexity(self):
        m_simple = CodeComplexityAnalyzer.analyze_function(_simple)
        m_branchy = CodeComplexityAnalyzer.analyze_function(_branchy)
        self.assertGreater(m_branchy.cyclomatic_complexity, m_simple.cyclomatic_complexity)

    def test_loop_heavy_complexity(self):
        m = CodeComplexityAnalyzer.analyze_function(_loop_heavy)
        self.assertGreater(m.cyclomatic_complexity, 1)

    def test_result_has_name(self):
        m = CodeComplexityAnalyzer.analyze_function(_simple)
        self.assertEqual(m.name, "_simple")

    def test_lines_of_code_positive(self):
        m = CodeComplexityAnalyzer.analyze_function(_branchy)
        self.assertGreater(m.lines_of_code, 0)

    def test_builtin_returns_safe_defaults(self):
        m = CodeComplexityAnalyzer.analyze_function(len)
        self.assertIsInstance(m, ComplexityMetrics)
        self.assertEqual(m.cyclomatic_complexity, 1)


# --------------------------------------------------------------------------- #
# FileMetrics (constructed directly)
# --------------------------------------------------------------------------- #

class FileMetricsTests(unittest.TestCase):
    def _simple_file_metrics(self, grade_score=85.0):
        m1 = ComplexityMetrics(
            name="f", cyclomatic_complexity=2, cognitive_complexity=2,
            halstead_volume=20.0, lines_of_code=5, lines_logical=4,
            crap_index=2.0, nested_depth=1
        )
        return FileMetrics(
            filepath=Path("test.py"),
            functions={"f": m1},
            total_lines=10,
            blank_lines=1,
            comment_lines=1,
            maintainability_index=grade_score,
        )

    def test_quality_grade_a(self):
        fm = self._simple_file_metrics(grade_score=90)
        self.assertEqual(fm.quality_grade, CodeQualityGrade.A)

    def test_quality_grade_b(self):
        fm = self._simple_file_metrics(grade_score=75)
        self.assertEqual(fm.quality_grade, CodeQualityGrade.B)

    def test_quality_grade_f(self):
        fm = self._simple_file_metrics(grade_score=40)
        self.assertEqual(fm.quality_grade, CodeQualityGrade.F)

    def test_get_high_complexity_functions_empty_when_low(self):
        fm = self._simple_file_metrics()
        self.assertEqual(fm.get_high_complexity_functions(), [])

    def test_get_high_complexity_functions_returns_high(self):
        m_high = ComplexityMetrics(
            name="bad", cyclomatic_complexity=15, cognitive_complexity=15,
            halstead_volume=100.0, lines_of_code=50, lines_logical=40,
            crap_index=50.0, nested_depth=5
        )
        fm = FileMetrics(
            filepath=Path("test.py"), functions={"bad": m_high},
            total_lines=50, blank_lines=2, comment_lines=2,
            maintainability_index=40.0,
        )
        self.assertEqual(len(fm.get_high_complexity_functions()), 1)


# --------------------------------------------------------------------------- #
# CodeSmellDetector
# --------------------------------------------------------------------------- #

class CodeSmellDetectorTests(unittest.TestCase):
    def _metrics_with_loc(self, name, loc, cyclomatic=1):
        return ComplexityMetrics(
            name=name, cyclomatic_complexity=cyclomatic, cognitive_complexity=cyclomatic,
            halstead_volume=0.0, lines_of_code=loc, lines_logical=loc,
            crap_index=1.0, nested_depth=0
        )

    def _file_with(self, metrics_dict):
        total = sum(m.lines_of_code for m in metrics_dict.values())
        return FileMetrics(
            filepath=Path("t.py"), functions=metrics_dict,
            total_lines=total, blank_lines=0, comment_lines=0, maintainability_index=70.0,
        )

    def test_long_function_detected(self):
        m = self._metrics_with_loc("big", 100)
        fm = self._file_with({"big": m})
        smells = CodeSmellDetector.detect_long_functions(fm, threshold=50)
        self.assertEqual(len(smells), 1)

    def test_short_function_not_flagged(self):
        m = self._metrics_with_loc("small", 10)
        fm = self._file_with({"small": m})
        smells = CodeSmellDetector.detect_long_functions(fm, threshold=50)
        self.assertEqual(smells, [])

    def test_high_complexity_detected(self):
        m = self._metrics_with_loc("g", 20, cyclomatic=15)
        fm = self._file_with({"g": m})
        smells = CodeSmellDetector.detect_high_complexity(fm, threshold=10)
        self.assertEqual(len(smells), 1)


if __name__ == "__main__":
    unittest.main()
