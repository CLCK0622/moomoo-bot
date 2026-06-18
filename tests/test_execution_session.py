"""End-to-end paper session: signals → marks (fixture) → risk → paper broker."""

import unittest

from qlab.config import load_config
from qlab.execution.session import (
    MarketFrame,
    build_marks,
    run_execution,
    run_execution_path,
)
from qlab.execution.signals import SignalSet, TargetSignal


class TestPaperSession(unittest.TestCase):
    def setUp(self):
        self.sig = SignalSet(
            signals=[TargetSignal("TSLA", 0.2), TargetSignal("NVDA", 0.2)],
            source="test",
        )

    def test_marks_from_fixture(self):
        marks, prev = build_marks(["TSLA", "NVDA"], "fixtures")
        self.assertIn("TSLA", marks)
        self.assertGreater(marks["TSLA"], 0)
        self.assertIn("NVDA", prev)

    def test_paper_run_through(self):
        cfg = load_config({"QLAB_EXEC_MODE": "paper", "QLAB_EXEC_CASH": "100000"})
        rec = run_execution(self.sig, cfg, mode="paper")
        self.assertEqual(rec.mode, "paper")
        self.assertGreater(rec.equity_before, 0)
        # Either filled or risk-rejected, but the cycle ran and stayed observable.
        self.assertEqual(len(rec.filled) + len(rec.rejected) + len(rec.skipped), 2)

    def test_dry_run_mode(self):
        cfg = load_config({"QLAB_EXEC_MODE": "dry_run"})
        rec = run_execution(self.sig, cfg, mode="dry_run")
        self.assertEqual(rec.mode, "dry_run")


class TestRiskPathGates(unittest.TestCase):
    """The multi-period driver feeds real intraday P&L / equity series / quote ages, so
    the path-dependent breakers actually fire end-to-end (not just in RiskManager units).
    """

    def _cfg(self, **ov):
        base = {"QLAB_EXEC_CASH": "100000", "QLAB_EXEC_SLIPPAGE_BPS": "0",
                "QLAB_EXEC_COMMISSION": "0"}
        base.update(ov)
        return load_config(base)

    def test_fixture_path_is_multi_period(self):
        sig = SignalSet(signals=[TargetSignal("TSLA", 0.2), TargetSignal("NVDA", 0.2)])
        recs = run_execution_path(sig, self._cfg(), mode="paper")
        self.assertGreater(len(recs), 1)  # genuinely replays a series, not one snapshot
        self.assertTrue(all(r.mode == "paper" for r in recs))

    def test_intraday_loss_blocks_new_exposure(self):
        sig = SignalSet(signals=[TargetSignal("AAA", 0.2)])
        frames = [MarketFrame(marks={"AAA": 100.0})]
        # Baseline above current equity -> intraday P&L starts at ~-9% (< -5% limit),
        # so the increase is blocked by the intraday-loss gate via the driver.
        recs = run_execution_path(
            sig, self._cfg(), mode="paper", frames=frames, baseline_equity=110_000.0
        )
        self.assertEqual(len(recs[0].filled), 0)
        self.assertTrue(any("intraday" in r["reason"] for r in recs[0].rejected))

    def test_drawdown_breaker_trips_on_equity_path(self):
        sig = SignalSet(signals=[TargetSignal("AAA", 1.0)])
        cfg = self._cfg(QLAB_MAX_POSITION_WEIGHT="1.0", QLAB_MAX_GROSS="1.0",
                        QLAB_DRAWDOWN_BREAKER="0.20")
        # Equity rides 100->120 (peak) then drops to 90: -25% from peak -> breaker latches.
        frames = [MarketFrame(marks={"AAA": p}) for p in (100.0, 120.0, 90.0)]
        recs = run_execution_path(sig, cfg, mode="paper", frames=frames)
        self.assertTrue(recs[-1].halted)
        self.assertIn("drawdown", recs[-1].halt_reason)

    def test_stale_quote_halts_and_blocks(self):
        sig = SignalSet(signals=[TargetSignal("AAA", 0.2)])
        frames = [MarketFrame(marks={"AAA": 100.0}, quote_ages={"AAA": 9999.0})]
        recs = run_execution_path(sig, self._cfg(), mode="paper", frames=frames)
        self.assertTrue(recs[0].halted)
        self.assertIn("stale", recs[0].halt_reason)
        self.assertTrue(any("stale" in r["reason"] for r in recs[0].rejected))


if __name__ == "__main__":
    unittest.main()
