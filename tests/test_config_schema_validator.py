"""
Stdlib-only regression tests for config_schema.py, config_validator.py,
paper_integrator.py, and content_aggregator cache_dir fix.

Run: python -m unittest tests.test_config_schema_validator -v
"""
import os
import sys
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)


class ConfigSchemaTests(unittest.TestCase):
    def test_imports_and_satin_config_exists(self):
        import config_schema
        self.assertTrue(hasattr(config_schema, "SatinConfig"))

    def test_satin_config_accepts_kwargs(self):
        from config_schema import SatinConfig
        # Must accept arbitrary kwargs without crashing (both pydantic and fallback paths)
        cfg = SatinConfig(version="2.0.0", foo="bar")
        self.assertIsNotNone(cfg)


class ConfigValidatorImportTests(unittest.TestCase):
    def test_imports_without_relative_error(self):
        # Previously crashed: 'attempted relative import with no known parent package'
        import config_validator
        self.assertTrue(hasattr(config_validator, "ConfigValidator"))


class PaperIntegratorTests(unittest.TestCase):
    def test_imports_and_has_expected_api(self):
        import paper_integrator as pi
        self.assertTrue(hasattr(pi, "PaperIntegrator"))
        self.assertTrue(hasattr(pi, "AcademicPaper"))

    def test_search_arxiv_returns_list_without_package(self):
        import paper_integrator as pi
        orig = pi._arxiv_lib
        pi._arxiv_lib = None  # simulate not installed
        try:
            results = pi.PaperIntegrator().search_arxiv("test")
            self.assertIsInstance(results, list)
            self.assertEqual(results, [])
        finally:
            pi._arxiv_lib = orig

    def test_academic_paper_to_dict(self):
        from paper_integrator import AcademicPaper
        from datetime import datetime
        p = AcademicPaper(
            paper_id="123",
            title="Test",
            abstract="abstract",
            authors=["Alice"],
            published_date=datetime(2024, 1, 1),
            url="http://example.com",
            source="arxiv",
        )
        d = p.to_dict()
        self.assertEqual(d["title"], "Test")
        self.assertIsInstance(d["published_date"], str)


class ContentAggregatorCacheDirTests(unittest.TestCase):
    def test_cache_dir_uses_path_not_string(self):
        # Previously crashed: str("cache/aggregator" / "youtube") → TypeError
        # because the local variable `cache_dir` (str) was used instead of self.cache_dir (Path)
        # We only test that the attribute assignment is reachable; full init needs API keys.
        import content_aggregator as ca
        from pathlib import Path
        # inspect the source to confirm self.cache_dir is used
        import inspect
        src = inspect.getsource(ca.ContentAggregator.__init__)
        self.assertIn("self.cache_dir", src)
        # 'cache_dir /' (bare variable) must NOT appear without self.
        lines = [l for l in src.splitlines() if "cache_dir /" in l or "cache_dir/" in l]
        for line in lines:
            stripped = line.strip()
            # All remaining references must be via self.cache_dir
            self.assertIn("self.cache_dir", stripped, f"bare cache_dir used: {stripped}")


if __name__ == "__main__":
    unittest.main()
