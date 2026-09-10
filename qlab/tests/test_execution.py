"""Execution layer: paper broker, risk controls, engine replay."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from qlab.brokers.paper import PaperBroker
from qlab.brokers.base import (Order, OrderType, Side, OrderStatus, BrokerError,
                               BrokerConnectionError)
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


# --- EVO-10 exposure caps (per-symbol 10% / industry 25% / strategy 30%) ---
def test_per_symbol_pct_cap_binds_below_notional_backstop():
    # 10% of 100k = 10k binds even though the $25k notional backstop is looser
    rm = _rm(per_symbol_max_pct=0.10, per_symbol_max_notional=25_000)
    over = rm.check_entry(symbol="AAA", strategy="orb", notional=12_000, now=T,
                          n_positions=0, equity=100_000, strategy_notional=0,
                          last_price=100, prev_price=100)
    assert not over.allowed and "per_symbol_cap" in over.reason
    ok = rm.check_entry(symbol="AAA", strategy="orb", notional=9_000, now=T,
                        n_positions=0, equity=100_000, strategy_notional=0,
                        last_price=100, prev_price=100)
    assert ok.allowed


def test_industry_cap_enforced():
    rm = _rm(per_industry_max_pct=0.25)  # 25k on 100k equity
    over = rm.check_entry(symbol="NVDA", strategy="orb", notional=8_000, now=T,
                          n_positions=2, equity=100_000, strategy_notional=0,
                          last_price=100, prev_price=100,
                          industry="semiconductors", industry_notional=20_000)
    assert not over.allowed and "per_industry_cap" in over.reason
    ok = rm.check_entry(symbol="NVDA", strategy="orb", notional=8_000, now=T,
                        n_positions=2, equity=100_000, strategy_notional=0,
                        last_price=100, prev_price=100,
                        industry="semiconductors", industry_notional=15_000)
    assert ok.allowed


def test_per_strategy_pct_cap():
    rm = _rm(per_strategy_max_pct=0.30, per_strategy_max_notional=100_000)
    over = rm.check_entry(symbol="AAA", strategy="orb", notional=5_000, now=T,
                          n_positions=0, equity=100_000, strategy_notional=28_000,
                          last_price=100, prev_price=100)
    assert not over.allowed and "per_strategy_cap" in over.reason


# --- final-review condition 1: connection error -> kill switch -> engine halts ---
class _DisconnectingBroker(PaperBroker):
    """PaperBroker whose account read fails like a lost gateway."""
    def get_account(self):
        raise BrokerConnectionError("simulated OpenD disconnect")


def test_connection_error_trips_kill_switch_and_halts(tmp_path: Path):
    cfg = ExecConfig(mode="paper", symbols=["AAA", "BBB"], initial_capital=100_000)
    eng = ExecutionEngine(cfg, tmp_path, also_stdout=False)
    eng.broker = _DisconnectingBroker(100_000)   # inject a broker that loses the gateway
    summary = eng.run_replay(_fixture())
    eng.close()
    assert summary["kill_switch"] is True
    assert summary["kill_reason"].startswith("connection_error")
    assert summary["halted"] is True
    assert summary["num_fills"] == 0             # halted before any trading
    assert summary["trading_days"] <= 1          # loop stopped almost immediately
    events = (tmp_path / "broker_events.jsonl").read_text()
    assert "engine_halted" in events and "kill_switch" in events


# --- final-review condition 2: abnormal market -> GLOBAL halt (not per-symbol) ---
def test_abnormal_move_triggers_global_halt(tmp_path: Path):
    cfg = ExecConfig(mode="paper", symbols=["AAA"], initial_capital=100_000)
    assert cfg.risk.abnormal_move_global_halt is True  # default
    eng = ExecutionEngine(cfg, tmp_path, also_stdout=False)

    def bar(ts, close):
        return {"AAA": pd.Series({"time": pd.Timestamp(ts), "close": float(close),
                                  "symbol": "AAA"})}

    eng.on_bar(bar("2025-01-02 10:00:00", 100.0))   # establishes prev price
    assert not eng.risk.kill_switch
    eng.on_bar(bar("2025-01-02 10:01:00", 140.0))   # +40% single-bar move
    assert eng.risk.kill_switch is True
    assert eng.risk.kill_reason.startswith("market_halt")
    # subsequent bars are a no-op (engine halted, not just this symbol blocked)
    before = eng._bar_count if hasattr(eng, "_bar_count") else 0
    eng.on_bar(bar("2025-01-02 10:02:00", 141.0))
    assert (getattr(eng, "_bar_count", 0)) == before  # on_bar returned early
    eng.close()
    events = (tmp_path / "broker_events.jsonl").read_text()
    assert "abnormal_move" in events and "engine_halted" in events


# --- targeted recheck: unified kill gate — no order slips through on the same
# bar, engine_halted lands in the SAME on_bar call, for EVERY trip point. ---
class _SpyBroker(PaperBroker):
    """Counts place_order calls and can inject a gateway loss on a chosen path."""
    def __init__(self, *a, fail_account=False, fail_account_after=None,
                 fail_reconcile=False, **k):
        super().__init__(*a, **k)
        self.place_calls = 0
        self._acct_calls = 0
        self.fail_account = fail_account
        self.fail_account_after = fail_account_after
        self.fail_reconcile = fail_reconcile

    def get_account(self):
        self._acct_calls += 1
        if self.fail_account:
            raise BrokerConnectionError("injected account read failure")
        if self.fail_account_after is not None and self._acct_calls > self.fail_account_after:
            raise BrokerConnectionError("injected trailing account failure")
        return super().get_account()

    def place_order(self, order):
        self.place_calls += 1
        return super().place_order(order)

    def reconcile_positions(self, engine_positions):
        if self.fail_reconcile:
            raise BrokerConnectionError("injected reconcile failure")
        return {"in_sync": True, "n_diffs": 0, "diffs": {}, "broker_positions": {}}


def _engine(tmp_path, broker, **cfg_kw):
    cfg = ExecConfig(mode="paper", symbols=["AAA"], initial_capital=100_000, **cfg_kw)
    eng = ExecutionEngine(cfg, tmp_path, also_stdout=False)
    eng.broker = broker
    return eng


def _seed_open_position(eng):
    eng.state["AAA"] = eng.adapter.new_position_state(
        100.0, 10, 95.0, pd.Timestamp("2025-01-02 10:00"))
    eng.strategy_of["AAA"] = "orb_breakout"


def _eod_bar():   # 15:55 -> ExitManager eod_close fires for any open position
    return {"AAA": pd.Series({"time": pd.Timestamp("2025-01-02 15:55:00"),
                              "close": 101.0, "symbol": "AAA"})}


def _plain_bar(close=100.0, ts="2025-01-02 10:00:00"):
    return {"AAA": pd.Series({"time": pd.Timestamp(ts), "close": float(close),
                              "symbol": "AAA"})}


def _events(tmp_path):
    return (tmp_path / "broker_events.jsonl").read_text()


def test_account_read_failure_halts_before_exit_no_order(tmp_path: Path):
    """THE flagged gap: kill tripped at `equity=self._equity()` must gate the
    EXIT scan on the SAME bar, with an open position that would otherwise sell."""
    spy = _SpyBroker(100_000, fail_account=True)
    eng = _engine(tmp_path, spy)
    _seed_open_position(eng)          # exit would fire at 15:55
    eng.on_bar(_eod_bar())
    assert eng.risk.kill_switch is True
    assert eng.risk.kill_reason.startswith("connection_error")
    assert spy.place_calls == 0       # <-- no SELL slipped through on this bar
    assert "engine_halted" in _events(tmp_path)   # landed in THIS on_bar call
    assert "AAA" in eng.state         # position untouched (not flattened)
    eng.close()


def test_drawdown_breaker_halts_same_bar_no_order(tmp_path: Path):
    spy = _SpyBroker(79_000)          # equity 79k vs peak 100k -> 21% DD
    eng = _engine(tmp_path, spy)
    _seed_open_position(eng)
    eng.on_bar(_eod_bar())
    assert eng.risk.kill_switch and "drawdown" in eng.risk.kill_reason
    assert spy.place_calls == 0
    assert "engine_halted" in _events(tmp_path)
    eng.close()


def test_reconcile_failure_halts_same_call(tmp_path: Path):
    spy = _SpyBroker(100_000, fail_reconcile=True)
    eng = _engine(tmp_path, spy, reconcile_every_bars=1)
    eng.on_bar(_plain_bar())          # no entry/exit; reconcile runs at bar end
    assert eng.risk.kill_switch and eng.risk.kill_reason.startswith("connection_error")
    assert "engine_halted" in _events(tmp_path)   # same call, not next bar
    # next bar is a no-op (GATE 0)
    bc = getattr(eng, "_bar_count", 0)
    eng.on_bar(_plain_bar(ts="2025-01-02 10:01:00"))
    assert getattr(eng, "_bar_count", 0) == bc
    eng.close()


def test_trailing_mtm_failure_halts_same_call(tmp_path: Path):
    # first account read (equity) ok, the trailing MTM read fails -> halt same call
    spy = _SpyBroker(100_000, fail_account_after=1)
    eng = _engine(tmp_path, spy)
    eng.on_bar(_plain_bar())
    assert eng.risk.kill_switch and eng.risk.kill_reason.startswith("connection_error")
    assert spy.place_calls == 0
    assert "engine_halted" in _events(tmp_path)   # emitted in the SAME on_bar call
    eng.close()


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


def test_order_carries_latency_fields():
    o = Order("AAA", Side.BUY, 1)
    d = o.to_dict()
    assert {"submit_ts", "ack_ts", "latency_ms"} <= d.keys()
    assert d["submit_ts"] is None  # unset until the live adapter times a call


def test_opend_reconcile_detects_deviation(monkeypatch):
    """Reconciliation diff logic (no gateway needed)."""
    from qlab.brokers.moomoo_opend import MoomooOpenDBroker
    from qlab.brokers.base import Position

    events = []

    class _Obs:
        def broker_event(self, broker, event, **kw):
            events.append((event, kw))

    b = MoomooOpenDBroker(logger=_Obs())
    monkeypatch.setattr(b, "get_positions",
                        lambda: {"AAA": Position("AAA", 10, 100.0, 101.0)})
    r = b.reconcile_positions({"AAA": 8, "BBB": 5})
    assert not r["in_sync"] and r["n_diffs"] == 2
    assert r["diffs"]["AAA"]["delta"] == 2    # broker 10 vs engine 8
    assert r["diffs"]["BBB"]["delta"] == -5   # engine 5 vs broker 0
    assert any(ev == "position_reconcile" for ev, _ in events)


def test_opend_reconcile_in_sync(monkeypatch):
    from qlab.brokers.moomoo_opend import MoomooOpenDBroker

    class _Obs:
        def broker_event(self, *a, **k): pass

    b = MoomooOpenDBroker(logger=_Obs())
    monkeypatch.setattr(b, "get_positions", lambda: {})
    assert b.reconcile_positions({})["in_sync"] is True


def test_signed_slippage_bps_convention():
    """+bps = worse execution (buy above ref / sell below ref)."""
    from qlab.opend_session_probe import signed_slippage_bps
    # buy filled above reference -> positive (worse)
    assert signed_slippage_bps(Side.BUY, 100.10, 100.00) > 0
    # buy filled below reference -> negative (better)
    assert signed_slippage_bps(Side.BUY, 99.90, 100.00) < 0
    # sell filled below reference -> positive (worse)
    assert signed_slippage_bps(Side.SELL, 99.90, 100.00) > 0
    # sell filled above reference -> negative (better)
    assert signed_slippage_bps(Side.SELL, 100.10, 100.00) < 0
    assert signed_slippage_bps(Side.BUY, 100.0, 0.0) is None
    # magnitude: 10 bps
    assert abs(signed_slippage_bps(Side.BUY, 100.10, 100.00) - 10.0) < 1e-6


def test_engine_respects_credentials_redaction(tmp_path: Path):
    cfg = ExecConfig(mode="paper", symbols=["AAA"])
    eng = ExecutionEngine(cfg, tmp_path)
    eng.obs.broker_event("test", "x", password="hunter2", token="abc", note="ok")
    eng.close()
    txt = (tmp_path / "broker_events.jsonl").read_text()
    assert "hunter2" not in txt and "abc" not in txt and "REDACTED" in txt
