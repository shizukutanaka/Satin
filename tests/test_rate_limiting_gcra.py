"""
Regression test: GCRALimiter must reject a non-positive emission_interval
instead of crashing later with ZeroDivisionError.

emission_interval is used as 1/emission_interval and as a divisor in
check_rate_limit (lines computing current_rate / remaining_requests). A value
of 0 previously sailed through __init__ and blew up on the first call.

Run: python -m unittest tests.test_rate_limiting_gcra -v
"""
import asyncio
import os
import sys
import unittest

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
sys.path.insert(0, _MAIN)

from advanced_rate_limiting import GCRALimiter  # noqa: E402


class GCRAValidationTests(unittest.TestCase):
    def test_zero_emission_interval_rejected(self):
        with self.assertRaises(ValueError):
            GCRALimiter(emission_interval=0, capacity=10)

    def test_negative_emission_interval_rejected(self):
        with self.assertRaises(ValueError):
            GCRALimiter(emission_interval=-1.0, capacity=10)

    def test_valid_interval_constructs_and_checks(self):
        limiter = GCRALimiter(emission_interval=0.1, capacity=5)

        async def scenario():
            status = await limiter.check_rate_limit(1)
            return status

        status = asyncio.run(scenario())
        self.assertTrue(status.allowed)
        # current_rate = 1 / emission_interval = 10.0, no ZeroDivisionError
        self.assertAlmostEqual(status.current_rate, 10.0)


if __name__ == "__main__":
    unittest.main()
