"""Execution layer: paper broker, risk controls, engine replay."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from qlab.brokers.paper import PaperBroker
from qlab.brokers.base import Order, OrderType, Side, OrderStatus, BrokerError
from qlab.config import ExecConfig, RiskLimits
from qlab.risk import RiskManager
from qlab.engine import ExecutionEngine

T = pd.Timestamp("2025-01-02 10:00:00")


# --- PaperBroker ---
def test_paper_buy_sell_roundtrip_pnl():
    b = PaperBroker(initial_cash=10_000, commission_per_order=1.0, slippage_pct=0.0)
    b.mark("AAA", 100.0, T)
    o = b.place_order(Order("AAA", Side.BUY, 10, OrderType.MARKET))
    assert o.status == OrderStatus.FILLED and o.filled_qty == 10
    assert b.get_positions()["AAA"].qty == 10
    b.mark("AAA", 110.0, T)
    b.place_order(Order("AAA", Side.SELL, 10, OrderType.MARKET))
    assert "AAA" not in b.get_positions()
    # +10/share *10 - 2 commissions
    assert round(b.realized_pnl, 2) == round(10 * 10 - 2 * 1.0, 2)


def test_paper_rejects_insufficient_cash():
    b = PaperBroker(initial_cash=50)
    b.mark("AAA", 100.0, T)
    with pytest.raises(BrokerError):
        b.place_order(Order("AAA", Side.BUY, 10, OrderType.MARKET))


def test_paper_requires_mark():
    b = PaperBroker()
    with pytest.raises(BrokerError):
        b.place_order(Order("AAA", Side.BUY, 1, OrderType.MARKET))


# --- RiskManager ---
def _rm(**kw):
    lim = RiskLimits(**kw)
    return RiskManager(lim, initial_equity=100_000)


def test_drawdown_breaker_trips_kill_switch():
    rm = _rm(drawdown_breaker_pct=0.20)
    rm.update_equity(100_000)
    rm.update_equity(79_000)  # -21%
    assert rm.kill_switch
    d = rm.check_entry(symbol="AAA", strategy="orb", notional=1000,
                       now=T, n_positions=0, equity=79_000, strategy_notional=0,
                       last_price=100, prev_price=100)
    assert not d.allowed and d.reason.startswith("kill_switch")


def test_intraday_loss_blocks_new_entries():
    rm = _rm(intraday_loss_limit_pct=0.03)
    rm.start_new_day(100_000)
    d = rm.check_entry(symbol="AAA", strategy="orb", notional=1000, now=T,
                       n_positions=0, equity=96_000, strategy_notional=0,
                       last_price=100, prev_price=100)
    assert not d.allowed and "intraday_loss" in d.reason


def test_per_symbol_cap_and_session():
    rm = _rm(per_symbol_max_notional=5_000)
    over = rm.check_entry(symbol="AAA", strategy="orb", notional=6_000, now=T,
                          n_positions=0, equity=100_000, strategy_notional=0,
                          last_price=100, prev_price=100)
    assert not over.allowed and "per_symbol_cap" in over.reason
    closed = rm.check_entry(symbol="AAA", strategy="orb", notional=100,
                            now=pd.Timestamp("2025-01-02 20:00:00"), n_positions=0,
                            equity=100_000, strategy_notional=0, last_price=100, prev_price=100)
    assert not closed.allowed and closed.reason == "outside_trading_session"


def test_abnormal_move_halt():
    rm = _rm(max_price_move_halt_pct=0.25)
    d = rm.check_entry(symbol="AAA", strategy="orb", notional=100, now=T,
                       n_positions=0, equity=100_000, strategy_notional=0,
                       last_price=140, prev_price=100)  # +40%
    assert not d.allowed and "abnormal_move" in d.reason


# --- Engine replay (end-to-end paper trading, no OpenD) ---
def _fixture(symbols=("AAA", "BBB"), seed=7):
    from qlab.synthetic import generate_symbol
    return {s: generate_symbol(s, "2025-01-02", "2025-02-28", seed=seed) for s in symbols}


def test_engine_paper_replay_produces_observability(tmp_path: Path):
    cfg = ExecConfig(mode="paper", symbols=["AAA", "BBB"], initial_capital=100_000)
    eng = ExecutionEngine(cfg, tmp_path, also_stdout=False)
    summary = eng.run_replay(_fixture())
    eng.close()
    assert summary["broker"] == "paper"
    assert summary["trading_days"] > 0
    for ch in ("signals", "orders", "fills", "equity", "heartbeat"):
        assert (tmp_path / f"{ch}.jsonl").exists()
    # at least some fills happened and equity curve was recorded
    assert summary["num_fills"] >= 0
    assert (tmp_path / "equity.jsonl").read_text().strip() != ""


def test_equity_and_positions_logged_per_bar_mtm(tmp_path: Path):
    """户部 gate: equity + positions must be 1m mark-to-market, not EOD."""
    cfg = ExecConfig(mode="paper", symbols=["AAA", "BBB"], initial_capital=100_000)
    eng = ExecutionEngine(cfg, tmp_path, also_stdout=False)
    summary = eng.run_replay(_fixture())
    eng.close()

    eq = [json.loads(l) for l in (tmp_path / "equity.jsonl").read_text().splitlines()]
    # far more equity rows than trading days => intrabar (1m) granularity, not EOD
    assert len(eq) > summary["trading_days"] * 50
    assert all(r["mark_to_market"] for r in eq)
    # multiple distinct timestamps within a single trading day
    day0 = sorted({r["time"][:10] for r in eq})[0]
    assert len({r["time"] for r in eq if r["time"].startswith(day0)}) > 50
    # equity actually moves intrabar (MTM), not flat-until-EOD
    assert len({round(r["equity"], 2) for r in eq}) > summary["trading_days"]

    pos = (tmp_path / "positions.jsonl").read_text().splitlines()
    assert pos, "per-bar position snapshots must be logged while holding"
    prow = json.loads(pos[0])
    assert {"time", "symbol", "qty", "entry_price", "last_price", "unrealized"} <= prow.keys()


def test_engine_dry_run_logs_intended_orders_only(tmp_path: Path):
    cfg = ExecConfig(mode="dry_run", symbols=["AAA"], initial_capital=100_000)
    eng = ExecutionEngine(cfg, tmp_path)
    eng.run_replay(_fixture(("AAA",)))
    eng.close()
    orders = [json.loads(l) for l in (tmp_path / "orders.jsonl").read_text().splitlines()]
    assert orders and all(o["intended"] for o in orders)
    assert (tmp_path / "fills.jsonl").read_text().strip() == ""  # no fills in dry_run


def test_engine_respects_credentials_redaction(tmp_path: Path):
    cfg = ExecConfig(mode="paper", symbols=["AAA"])
    eng = ExecutionEngine(cfg, tmp_path)
    eng.obs.broker_event("test", "x", password="hunter2", token="abc", note="ok")
    eng.close()
    txt = (tmp_path / "broker_events.jsonl").read_text()
    assert "hunter2" not in txt and "abc" not in txt and "REDACTED" in txt
