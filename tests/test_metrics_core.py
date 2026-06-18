"""Unit tests for the v1.0 §2 metric algorithms (hand-computed expected values)."""

import unittest

from qlab.metrics.core import (
    annualized_turnover,
    drawdown_durations,
    geometric_cagr,
    max_drawdown,
    returns_from_equity,
    sharpe,
    sortino,
)


class TestReturns(unittest.TestCase):
    def test_returns_from_equity(self):
        out = returns_from_equity([100, 110, 99])
        self.assertEqual(len(out), 2)
        self.assertAlmostEqual(out[0], 0.1)
        self.assertAlmostEqual(out[1], -0.1)

    def test_empty(self):
        self.assertEqual(returns_from_equity([100]), [])


class TestCagr(unittest.TestCase):
    def test_p1_is_total_return(self):
        # n = 1 period, P = 1 -> CAGR == total return.
        self.assertAlmostEqual(geometric_cagr([100, 200], 1), 1.0)

    def test_annualization_exponent(self):
        # ratio 2 over n=1 period with P=2 -> 2^(2/1) - 1 = 3.0
        self.assertAlmostEqual(geometric_cagr([100, 200], 2), 3.0)

    def test_multi_period(self):
        # ratio 2 over n=3 periods, P=3 -> 2^(3/3) - 1 = 1.0
        self.assertAlmostEqual(geometric_cagr([100, 130, 160, 200], 3), 1.0)

    def test_wipeout(self):
        self.assertEqual(geometric_cagr([100, 0], 1), -1.0)

    def test_too_short(self):
        self.assertEqual(geometric_cagr([100], 252), 0.0)


class TestMaxDrawdown(unittest.TestCase):
    def test_known(self):
        # peak 120 then 90 -> 90/120 - 1 = -0.25
        self.assertAlmostEqual(max_drawdown([100, 120, 90, 150]), 0.25)

    def test_monotonic_up_zero(self):
        self.assertAlmostEqual(max_drawdown([100, 110, 120]), 0.0)


class TestDrawdownDuration(unittest.TestCase):
    def test_recovery_and_unrecovered(self):
        # peak@idx1=120, dip, recover@idx3 (len 2), new peak 130, then underwater to end.
        dd = drawdown_durations([100, 120, 90, 130, 110, 100])
        self.assertEqual(dd.longest_underwater_bars, 2)
        self.assertEqual(dd.median_underwater_bars, 2.0)
        self.assertTrue(dd.has_unrecovered)
        self.assertEqual(dd.unrecovered_bars, 2)

    def test_no_drawdown(self):
        dd = drawdown_durations([100, 110, 120])
        self.assertFalse(dd.has_unrecovered)
        self.assertEqual(dd.longest_underwater_bars, 0)


class TestSharpeSortino(unittest.TestCase):
    def test_sharpe_known(self):
        r = [0.01, 0.02, 0.01, 0.02]
        self.assertAlmostEqual(sharpe(r, 1), 2.59808, places=4)

    def test_sharpe_zero_vol(self):
        self.assertEqual(sharpe([0.01, 0.01, 0.01], 252), 0.0)

    def test_sortino_known(self):
        r = [0.02, -0.01, 0.02, -0.01]
        self.assertAlmostEqual(sortino(r, 1), 0.70711, places=4)

    def test_sortino_no_downside(self):
        self.assertEqual(sortino([0.01, 0.02], 252), 0.0)


class TestTurnover(unittest.TestCase):
    def test_annualized(self):
        # mean per-bar turnover 0.1, P=252 -> 25.2
        self.assertAlmostEqual(annualized_turnover([0.1, 0.1, 0.1], 252), 25.2)

    def test_empty(self):
        self.assertEqual(annualized_turnover([], 252), 0.0)


if __name__ == "__main__":
    unittest.main()
