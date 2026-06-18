import unittest

from qlab.backtest.engine import BacktestRunner
from qlab.config import BacktestConfig, CostConfig
from qlab.data.base import Bar
from qlab.strategy.base import Strategy


def _bars(closes):
    out = []
    for i, c in enumerate(closes):
        out.append(Bar(f"2022-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}", c, c, c, c))
    return out


class AlwaysLong(Strategy):
    name = "always_long"

    def target_weights(self, bars):
        return [1.0] * len(bars)


class Flat(Strategy):
    name = "flat"

    def target_weights(self, bars):
        return [0.0] * len(bars)


class TestEngine(unittest.TestCase):
    def setUp(self):
        self.cfg_bt = BacktestConfig(initial_cash=100_000, oos_fraction=0.3)
        self.cfg_cost = CostConfig(commission_rate=0.0, slippage_bps=0.0)

    def test_flat_keeps_cash(self):
        runner = BacktestRunner(self.cfg_cost, self.cfg_bt)
        res = runner.run("X", _bars([10.0] * 10), Flat())
        self.assertAlmostEqual(res.final_equity, 100_000, places=2)
        self.assertEqual(len(res.trades), 0)

    def test_long_tracks_price_no_costs(self):
        # Price doubles; fully-invested equity should ~double (minus rounding).
        runner = BacktestRunner(self.cfg_cost, self.cfg_bt)
        res = runner.run("X", _bars([10.0, 10.0, 20.0, 20.0]), AlwaysLong())
        # Buy happens at bar1 open (10); price then goes to 20 -> ~2x.
        self.assertGreater(res.final_equity, 180_000)

    def test_costs_reduce_equity(self):
        cost = CostConfig(commission_rate=0.001, slippage_bps=5.0)
        runner_cost = BacktestRunner(cost, self.cfg_bt)
        runner_free = BacktestRunner(self.cfg_cost, self.cfg_bt)
        bars = _bars([10.0, 11.0, 9.0, 12.0, 10.0, 11.0])
        with_cost = runner_cost.run("X", bars, AlwaysLong())
        free = runner_free.run("X", bars, AlwaysLong())
        self.assertLess(with_cost.final_equity, free.final_equity)
        self.assertGreater(with_cost.total_commission, 0)
        self.assertGreater(with_cost.total_slippage, 0)

    def test_oos_boundary_recorded(self):
        runner = BacktestRunner(self.cfg_cost, self.cfg_bt)
        bars = _bars([10.0 + i for i in range(20)])
        res = runner.run("X", bars, AlwaysLong())
        self.assertIsNotNone(res.oos_start_ts)
        self.assertIn(res.oos_start_ts, [b.ts for b in bars])

    def test_requires_min_bars(self):
        runner = BacktestRunner(self.cfg_cost, self.cfg_bt)
        with self.assertRaises(ValueError):
            runner.run("X", _bars([10.0]), AlwaysLong())


if __name__ == "__main__":
    unittest.main()
