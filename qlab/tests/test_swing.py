"""Offline unit tests for the EVO-130 swing harness (signals, book, strategies, eval).

Deterministic, no gateway/SDK: synthetic frames pin the load-bearing accounting
(cost-after P&L, concurrency cap, no-look-ahead entry timing) and the S5 decay
statistics. The real full-depth runs live in reports/swing_*/report.json.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from qlab.swing.book import make_trade, simulate_book
from qlab.swing.evaluate import event_edge
from qlab.swing.signals import sma, wilder_rsi
from qlab.swing.strategies import s1_symbol_trades, s5_fomc_trades


# --------------------------------------------------------------------------- #
# signals
# --------------------------------------------------------------------------- #
def test_wilder_rsi_bounds_and_warmup():
    up = pd.Series([1, 2, 3, 4, 5, 6, 7, 8], dtype=float)
    rsi = wilder_rsi(up, 2)
    assert np.isnan(rsi.iloc[0]) and np.isnan(rsi.iloc[1])   # warmup
    assert rsi.dropna().max() <= 100.0 and rsi.dropna().min() >= 0.0
    assert rsi.iloc[-1] > 99.0                                # unbroken up-run -> ~100
    down = pd.Series([8, 7, 6, 5, 4, 3, 2, 1], dtype=float)
    assert wilder_rsi(down, 2).iloc[-1] < 1.0                 # unbroken down-run -> ~0


def test_sma_no_lookahead():
    s = sma(pd.Series([1, 2, 3, 4, 5], dtype=float), 3)
    assert np.isnan(s.iloc[0]) and np.isnan(s.iloc[1])
    assert s.iloc[2] == 2.0 and s.iloc[4] == 4.0


# --------------------------------------------------------------------------- #
# book: cost-after P&L accounting
# --------------------------------------------------------------------------- #
def test_make_trade_cost_after_pnl():
    dates = pd.DatetimeIndex(pd.bdate_range("2020-01-01", periods=5))
    close = np.array([100.0, 110.0, 121.0, 133.1, 146.41])   # +10%/bar
    side = 0.001
    tr = make_trade("X", dates, close, i_e=1, p_e=100.0, i_x=3, p_x=133.1,
                    side_frac=side)
    # gross: (1.1)(1.1)(1.1)-1 = 0.331 ; net pays side on entry+exit legs
    assert abs(tr.gross_return - 0.331) < 1e-9
    assert tr.net_return < tr.gross_return
    assert abs(tr.net_return - ((1 + 0.10 - side) * (1 + 0.10) * (1 + 0.10 - side) - 1)) < 1e-9
    assert set(tr.daily_returns) == {dates[1], dates[2], dates[3]}
    assert tr.hold_days == 2


def test_simulate_book_concurrency_cap():
    dates = pd.DatetimeIndex(pd.bdate_range("2020-01-01", periods=10))
    close = np.linspace(100, 120, 10)
    # two OVERLAPPING trades; cap=1 admits one, skips the other
    a = make_trade("A", dates, close, 1, close[1], 4, close[4], 0.0)
    b = make_trade("B", dates, close, 2, close[2], 5, close[5], 0.0)
    eq, diag, tl = simulate_book([a, b], list(dates), max_concurrent=1)
    assert diag["n_trades_admitted"] == 1 and diag["capacity_skipped"] == 1
    # non-overlapping pair both admitted
    c = make_trade("C", dates, close, 6, close[6], 8, close[8], 0.0)
    eq2, diag2, _ = simulate_book([a, c], list(dates), max_concurrent=1)
    assert diag2["n_trades_admitted"] == 2 and diag2["capacity_skipped"] == 0
    assert list(eq2.columns) == ["date", "ret", "equity", "traded_notional"]
    assert len(eq2) == 10 and eq2["equity"].iloc[-1] > 0


def test_simulate_book_equity_matches_single_trade():
    dates = pd.DatetimeIndex(pd.bdate_range("2020-01-01", periods=6))
    close = np.array([100.0, 102.0, 104.0, 103.0, 105.0, 106.0])
    tr = make_trade("X", dates, close, 1, 100.0, 4, 105.0, 0.0)
    eq, diag, tl = simulate_book([tr], list(dates), max_concurrent=1)
    # full weight (w=1): final equity == product of the trade's daily contributions
    expected = np.prod([1 + r for r in tr.daily_returns.values()])
    assert abs(eq["equity"].iloc[-1] - expected) < 1e-9
    assert diag["mean_active_positions"] > 0


# --------------------------------------------------------------------------- #
# strategies: entry/exit timing (no look-ahead)
# --------------------------------------------------------------------------- #
def test_s5_entry_is_close_before_decision_no_lookahead():
    dates = pd.bdate_range("2015-06-01", periods=20)
    close = np.linspace(200, 210, 20)
    df = pd.DataFrame({"date": dates, "open": close, "high": close + 1,
                       "low": close - 1, "close": close, "volume": 1e6})
    T = pd.Timestamp(dates[10])                     # a decision day inside the frame
    trades, rows = s5_fomc_trades(df, pd.DatetimeIndex([T]), side_frac=0.0, entry_offset=1)
    assert len(trades) == 1 and len(rows) == 1
    tr = trades[0]
    assert tr.entry_date == dates[9] and tr.exit_date == dates[10]   # T-1 -> T
    # gross event return == close[T]/close[T-1]-1
    assert abs(rows[0]["gross_return"] - (close[10] / close[9] - 1.0)) < 1e-9


def test_s1_entry_executes_after_signal_bar():
    # 200-bar uptrend so SMA200 (~100) sits WELL below price (~150): a brief 2-bar
    # dip then drives RSI2<10 while price stays above the long average (the whole
    # point of the SMA200 trend filter), then a bounce lifts RSI2>60.
    base = list(np.linspace(50.0, 150.0, 200))
    tail = [150.0, 148.0, 146.0, 149.0, 152.0, 155.0, 158.0]   # dip (146) then bounce
    close = np.array(base + tail, dtype=float)
    dip_i = len(base) + 2                       # index of the 146 bar (oversold)
    dates = pd.bdate_range("2019-01-01", periods=len(close))
    df = pd.DataFrame({"date": dates, "open": close, "high": close + 0.5,
                       "low": close - 0.5, "close": close, "volume": 1e6})
    trades = s1_symbol_trades("X", df, side_frac=0.0, rsi_period=2, rsi_entry=10.0,
                              rsi_exit=60.0, sma_len=200, max_hold=5)
    assert len(trades) >= 1
    tr = trades[0]
    entry_i = list(dates).index(tr.entry_date)
    assert entry_i > dip_i                       # entry strictly AFTER the signal bar (T+1)
    assert tr.exit_date > tr.entry_date


# --------------------------------------------------------------------------- #
# evaluate: event-edge significance direction
# --------------------------------------------------------------------------- #
def test_event_edge_detects_positive_and_null():
    pos = event_edge([0.01] * 30, n_boot=1000, seed=1)
    assert pos["significant_positive"] is True and pos["p_mean_le_0"] < 0.05
    null = event_edge([0.01, -0.01] * 15, n_boot=1000, seed=1)
    assert null["significant_positive"] is False
