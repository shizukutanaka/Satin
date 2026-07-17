"""
Unit tests for utils_batch.batch_process — parallel processing with failure isolation.
"""
import os
import sys
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from utils_batch import batch_process  # noqa: E402


class BatchProcessTests(unittest.TestCase):
    def test_simple_map_returns_all_results(self):
        results = batch_process(lambda x: x * 2, [1, 2, 3])
        self.assertEqual(sorted(results), [2, 4, 6])

    def test_empty_items_returns_empty_list(self):
        results = batch_process(lambda x: x, [])
        self.assertEqual(results, [])

    def test_exception_in_task_returns_none_for_that_item(self):
        def boom(x):
            raise ValueError("fail")
        results = batch_process(boom, [1])
        self.assertEqual(results, [None])

    def test_partial_failure_does_not_lose_other_results(self):
        def maybe_fail(x):
            if x == 2:
                raise RuntimeError("bad")
            return x * 10
        results = batch_process(maybe_fail, [1, 2, 3])
        non_none = [r for r in results if r is not None]
        self.assertIn(10, non_none)
        self.assertIn(30, non_none)
        self.assertIn(None, results)

    def test_single_worker_processes_sequentially(self):
        results = batch_process(lambda x: x + 1, [5, 6, 7], max_workers=1)
        self.assertCountEqual(results, [6, 7, 8])

    def test_returns_list_of_correct_length(self):
        items = list(range(10))
        results = batch_process(lambda x: x, items, max_workers=4)
        self.assertEqual(len(results), 10)

    def test_desc_param_accepted(self):
        # desc is forwarded to tqdm — should not raise even without tqdm
        results = batch_process(str, [1, 2], desc="testing")
        self.assertEqual(len(results), 2)


if __name__ == "__main__":
    unittest.main()
