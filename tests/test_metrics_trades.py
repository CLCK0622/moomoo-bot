"""Unit tests for closed-trade reconstruction + trade stats (v1.0 §2.6-2.7)."""

import unittest

from qlab.backtest.engine import Trade
from qlab.metrics.trades import closed_trade_pnls, trade_stats


def _t(side, shares, price, commission=0.0):
    return Trade(
        ts="2022-01-01", side=side, shares=shares, price=price,
        notional=shares * price, commission=commission, slippage=0.0,
    )


class TestClosedTrades(unittest.TestCase):
    def test_single_round_trip(self):
        # buy 100@10 (comm 5), sell 100@12 (comm 6) -> 1194 - 1005 = 189
        pnls = closed_trade_pnls([_t("BUY", 100, 10, 5), _t("SELL", 100, 12, 6)])
        self.assertEqual(len(pnls), 1)
        self.assertAlmostEqual(pnls[0], 189.0)

    def test_open_position_excluded(self):
        # never returns to flat -> no closed trade recorded
        self.assertEqual(closed_trade_pnls([_t("BUY", 100, 10)]), [])

    def test_flip_through_zero_splits(self):
        # long 100, then sell 150 (flip to short 50): closes the long, opens a short.
        pnls = closed_trade_pnls([_t("BUY", 100, 10), _t("SELL", 150, 12)])
        # First trade closes 100 long @12 vs entry 10 -> +200 realised.
        self.assertEqual(len(pnls), 1)
        self.assertAlmostEqual(pnls[0], 200.0)

    def test_two_round_trips(self):
        pnls = closed_trade_pnls(
            [_t("BUY", 10, 10), _t("SELL", 10, 11), _t("BUY", 10, 11), _t("SELL", 10, 10)]
        )
        self.assertEqual(len(pnls), 2)
        self.assertAlmostEqual(pnls[0], 10.0)   # +1 * 10 shares
        self.assertAlmostEqual(pnls[1], -10.0)  # -1 * 10 shares


class TestTradeStats(unittest.TestCase):
    def test_known(self):
        s = trade_stats([189.0, -50.0])
        self.assertEqual(s.n_closed_trades, 2)
        self.assertAlmostEqual(s.win_rate, 0.5)
        self.assertAlmostEqual(s.profit_loss_ratio, 189.0 / 50.0)
        self.assertAlmostEqual(s.profit_factor, 189.0 / 50.0)
        self.assertAlmostEqual(s.expectancy, 0.5 * 189.0 - 0.5 * 50.0)

    def test_empty(self):
        s = trade_stats([])
        self.assertEqual(s.n_closed_trades, 0)
        self.assertEqual(s.win_rate, 0.0)

    def test_all_wins_infinite_pf(self):
        s = trade_stats([10.0, 20.0])
        self.assertEqual(s.win_rate, 1.0)
        self.assertEqual(s.profit_factor, float("inf"))


if __name__ == "__main__":
    unittest.main()
