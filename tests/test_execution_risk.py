"""Unit tests for the execution-layer risk guardrails (EVO-13 §4)."""

import unittest

from qlab.brokers.guardrails import KillSwitch
from qlab.config import RiskConfig
from qlab.execution.risk import Quote, RiskManager


def _rm(**kw):
    base = dict(
        max_position_weight=0.25, max_gross_exposure=1.0, max_positions=5,
        intraday_loss_limit=0.05, drawdown_breaker=0.20, abnormal_move_pct=0.15,
        stale_quote_seconds=120.0,
    )
    base.update(kw)
    return RiskManager(RiskConfig(**base))


class TestPositionCaps(unittest.TestCase):
    def test_position_weight_cap(self):
        rm = _rm()
        d = rm.pretrade_check(
            increases_exposure=True, symbol_weight_after=0.30,
            gross_after=0.30, n_positions_after=1, intraday_pnl_pct=0.0,
        )
        self.assertFalse(d.allowed)
        self.assertIn("position cap", d.reason)

    def test_gross_cap(self):
        rm = _rm()
        d = rm.pretrade_check(
            increases_exposure=True, symbol_weight_after=0.2,
            gross_after=1.2, n_positions_after=3, intraday_pnl_pct=0.0,
        )
        self.assertFalse(d.allowed)
        self.assertIn("gross", d.reason)

    def test_max_positions(self):
        rm = _rm()
        d = rm.pretrade_check(
            increases_exposure=True, symbol_weight_after=0.1,
            gross_after=0.6, n_positions_after=6, intraday_pnl_pct=0.0,
        )
        self.assertFalse(d.allowed)
        self.assertIn("max positions", d.reason)

    def test_allowed_within_caps(self):
        rm = _rm()
        d = rm.pretrade_check(
            increases_exposure=True, symbol_weight_after=0.2,
            gross_after=0.8, n_positions_after=4, intraday_pnl_pct=-0.01,
        )
        self.assertTrue(d.allowed)


class TestIntradayLoss(unittest.TestCase):
    def test_blocks_new_exposure(self):
        rm = _rm()
        d = rm.pretrade_check(
            increases_exposure=True, symbol_weight_after=0.1,
            gross_after=0.5, n_positions_after=2, intraday_pnl_pct=-0.06,
        )
        self.assertFalse(d.allowed)
        self.assertIn("intraday", d.reason)

    def test_still_allows_derisk(self):
        rm = _rm()
        d = rm.pretrade_check(
            increases_exposure=False, symbol_weight_after=0.0,
            gross_after=0.0, n_positions_after=0, intraday_pnl_pct=-0.06,
        )
        self.assertTrue(d.allowed)  # selling to de-risk is allowed


class TestDrawdownBreaker(unittest.TestCase):
    def test_trips_and_latches(self):
        rm = _rm()
        rm.register_equity(100_000)
        d = rm.register_equity(79_000)  # -21%
        self.assertFalse(d.allowed)
        self.assertTrue(rm.halted)
        # new exposure blocked while halted
        blk = rm.pretrade_check(
            increases_exposure=True, symbol_weight_after=0.1,
            gross_after=0.3, n_positions_after=1, intraday_pnl_pct=0.0,
        )
        self.assertFalse(blk.allowed)
        # de-risk still allowed
        ok = rm.pretrade_check(
            increases_exposure=False, symbol_weight_after=0.0,
            gross_after=0.0, n_positions_after=0, intraday_pnl_pct=0.0,
        )
        self.assertTrue(ok.allowed)

    def test_no_trip_above_threshold(self):
        rm = _rm()
        rm.register_equity(100_000)
        d = rm.register_equity(85_000)  # -15% < 20%
        self.assertTrue(d.allowed)
        self.assertFalse(rm.halted)


class TestAbnormalMarket(unittest.TestCase):
    def test_abnormal_move_halts(self):
        rm = _rm()
        d = rm.check_market(Quote("TSLA", price=120, prev_close=100))  # +20%
        self.assertFalse(d.allowed)
        self.assertTrue(rm.halted)

    def test_stale_quote_halts(self):
        rm = _rm()
        d = rm.check_market(Quote("TSLA", price=100, prev_close=100, age_seconds=300))
        self.assertFalse(d.allowed)

    def test_normal_quote_ok(self):
        rm = _rm()
        d = rm.check_market(Quote("TSLA", price=101, prev_close=100, age_seconds=5))
        self.assertTrue(d.allowed)


class TestKillSwitchIntegration(unittest.TestCase):
    def test_kill_switch_blocks_all(self):
        ks = KillSwitch()
        ks.trip("ops halt")
        rm = _rm()
        rm.kill = ks
        d = rm.pretrade_check(
            increases_exposure=False, symbol_weight_after=0.0,
            gross_after=0.0, n_positions_after=0, intraday_pnl_pct=0.0,
        )
        self.assertFalse(d.allowed)  # kill switch blocks even de-risk
        self.assertTrue(rm.halted)


if __name__ == "__main__":
    unittest.main()
