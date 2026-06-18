"""Tests for the paper broker, signal ingest, and the execution engine."""

import json
import os
import tempfile
import unittest

from qlab.config import RiskConfig
from qlab.execution.broker import PaperBroker
from qlab.execution.engine import ExecutionEngine
from qlab.execution.risk import RiskManager
from qlab.execution.signals import SignalSet, TargetSignal, load_signals, sanity_check


def _rm(**kw):
    base = dict(max_position_weight=0.25, max_gross_exposure=1.0, max_positions=5,
                intraday_loss_limit=0.05, drawdown_breaker=0.20, abnormal_move_pct=0.15,
                stale_quote_seconds=120.0)
    base.update(kw)
    return RiskManager(RiskConfig(**base))


class TestPaperBroker(unittest.TestCase):
    def test_buy_updates_cash_and_position(self):
        b = PaperBroker(100_000, slippage_bps=0, commission_per_trade=0)
        r = b.place_market_order("AAPL", "BUY", 100, 50.0)
        self.assertEqual(r.status, "filled")
        self.assertAlmostEqual(b.cash, 95_000.0)
        self.assertAlmostEqual(b.positions()["AAPL"].qty, 100)
        self.assertAlmostEqual(b.equity({"AAPL": 50.0}), 100_000.0)

    def test_sell_realizes_pnl(self):
        b = PaperBroker(100_000, slippage_bps=0, commission_per_trade=0)
        b.place_market_order("AAPL", "BUY", 100, 50.0)
        b.place_market_order("AAPL", "SELL", 100, 60.0)
        self.assertAlmostEqual(b.realized_pnl, 1000.0)  # (60-50)*100
        self.assertEqual(b.positions(), {})  # flat

    def test_rejects_bad_order(self):
        b = PaperBroker(100_000)
        self.assertEqual(b.place_market_order("AAPL", "BUY", 0, 50.0).status, "rejected")


class TestSignals(unittest.TestCase):
    def test_load_and_active(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "s.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"source": "t", "signals": [
                    {"symbol": "tsla", "target_weight": 0.2},
                    {"symbol": "nvda", "target_weight": 0.0},
                ]}, fh)
            ss = load_signals(path)
            self.assertEqual(ss.signals[0].symbol, "TSLA")  # upper-cased
            self.assertEqual(len(ss.active()), 1)

    def test_sanity_check_flags(self):
        ss = SignalSet(signals=[
            TargetSignal("AAA", 1.5),  # out of range
            TargetSignal("BBB", 0.2),
            TargetSignal("BBB", 0.2),  # duplicate
            TargetSignal("ZZZ", 0.2),  # not in universe
        ])
        issues = sanity_check(ss, universe=["AAA", "BBB"], max_positions=2, max_gross=1.0)
        joined = " ".join(issues)
        self.assertIn("out of", joined)
        self.assertIn("duplicate", joined)
        self.assertIn("not in declared universe", joined)

    def test_sanity_check_clean(self):
        ss = SignalSet(signals=[TargetSignal("AAA", 0.2), TargetSignal("BBB", 0.2)])
        self.assertEqual(sanity_check(ss, universe=["AAA", "BBB"], max_positions=5), [])


class TestEngine(unittest.TestCase):
    def setUp(self):
        self.sig = SignalSet(signals=[
            TargetSignal("AAPL", 0.2), TargetSignal("NVDA", 0.2),
        ])
        self.marks = {"AAPL": 100.0, "NVDA": 100.0}

    def test_paper_mode_fills(self):
        eng = ExecutionEngine(PaperBroker(100_000, slippage_bps=0, commission_per_trade=0), _rm(),
                              mode="paper")
        rec = eng.run_cycle(self.sig, self.marks)
        self.assertEqual(len(rec.filled), 2)
        self.assertIn("AAPL", rec.positions_after)
        self.assertAlmostEqual(rec.positions_after["AAPL"]["qty"], 200)  # 0.2*100k/100

    def test_dry_run_places_nothing(self):
        broker = PaperBroker(100_000)
        eng = ExecutionEngine(broker, _rm(), mode="dry_run")
        rec = eng.run_cycle(self.sig, self.marks)
        self.assertTrue(all(f["status"] == "dry_run" for f in rec.filled))
        self.assertEqual(broker.positions(), {})  # broker untouched

    def test_risk_rejects_oversized(self):
        eng = ExecutionEngine(PaperBroker(100_000), _rm(max_position_weight=0.1), mode="paper")
        rec = eng.run_cycle(self.sig, self.marks)  # 0.2 weight > 0.1 cap
        self.assertEqual(len(rec.filled), 0)
        self.assertTrue(all("position cap" in r["reason"] for r in rec.rejected))

    def test_halt_blocks_new_buys(self):
        rm = _rm()
        rm.halt("manual test halt")
        eng = ExecutionEngine(PaperBroker(100_000), rm, mode="paper")
        rec = eng.run_cycle(self.sig, self.marks)
        self.assertTrue(rec.halted)
        self.assertEqual(len(rec.filled), 0)
        self.assertEqual(len(rec.rejected), 2)

    def test_no_mark_skipped(self):
        eng = ExecutionEngine(PaperBroker(100_000), _rm(), mode="paper")
        rec = eng.run_cycle(self.sig, {"AAPL": 100.0})  # NVDA missing
        self.assertTrue(any(s["symbol"] == "NVDA" for s in rec.skipped))


if __name__ == "__main__":
    unittest.main()
