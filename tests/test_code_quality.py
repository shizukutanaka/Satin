"""
Stdlib-only regression tests for the Tier-1 fixes in main/code_quality_metrics.py.

Run: python -m unittest tests.test_code_quality -v
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main.code_quality_metrics import CodeComplexityAnalyzer  # noqa: E402

SAMPLE = '''
class Foo:
    def method_a(self, x):
        if x > 0:
            for i in range(x):
                if i % 2 == 0:
                    pass
        def nested():
            if True:
                return 1
        return nested

class Bar:
    def method_a(self):
        return 1

def top_level(a, b):
    return a + b * 2 - 1
'''


class CodeQualityTests(unittest.TestCase):
    def setUp(self):
        fd, path = tempfile.mkstemp(suffix=".py")
        os.close(fd)
        self.path = Path(path)
        self.path.write_text(SAMPLE)
        self.metrics = CodeComplexityAnalyzer.analyze_file(self.path)

    def tearDown(self):
        self.path.unlink(missing_ok=True)

    def test_classes_are_detected(self):
        # Previously metrics.classes was ALWAYS empty (node.parent never set).
        self.assertIn("Foo", self.metrics.classes)
        self.assertIn("Bar", self.metrics.classes)

    def test_methods_namespaced_no_collision(self):
        # Foo.method_a and Bar.method_a must both survive (no bare-name clobber).
        self.assertIn("method_a", self.metrics.classes["Foo"])
        self.assertIn("method_a", self.metrics.classes["Bar"])
        self.assertEqual(self.metrics.classes["Foo"]["method_a"].name, "Foo.method_a")

    def test_nested_function_not_leaked_into_functions(self):
        self.assertIn("top_level", self.metrics.functions)
        self.assertNotIn("nested", self.metrics.functions)
        self.assertNotIn("method_a", self.metrics.functions)

    def test_complexity_not_double_counted(self):
        # base 1 + (if) + (for) + (inner if) = 4; the nested function's `if True`
        # must NOT be added to the parent (that would make it 5).
        self.assertEqual(self.metrics.classes["Foo"]["method_a"].cyclomatic_complexity, 4)

    def test_halstead_volume_is_positive(self):
        # Previously always 0.0 due to an int*str bug; now V = N*log2(n) > 0.
        self.assertGreater(self.metrics.functions["top_level"].halstead_volume, 0.0)


if __name__ == "__main__":
    unittest.main()
