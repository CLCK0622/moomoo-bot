"""S1 (short-term oversold mean reversion) and S5 (FOMC pre-drift) trade builders.

Both emit ``SwingTrade`` lists consumed by :mod:`qlab.swing.book`. Signals are
evaluated as of a bar's CLOSE and executed on a later bar, so no value that a
trade prices against was unknown when the signal fired:

* **S1** — RSI(2) < ``rsi_entry`` while ``close > SMA(sma_len)`` (long-only,
  above the long-term trend). Signal on ``close[t]`` → enter ``open[t+1]``; exit
  ``open[u+1]`` when ``RSI(2) > rsi_exit`` on ``close[u]``, or after ``max_hold``
  bars. One position per symbol at a time (no pyramiding).
* **S5** — enter ``close[T-offset]`` and exit ``close[T]`` around each *scheduled*
  FOMC decision day ``T``. The FOMC schedule is public months ahead, so a
  ``close[T-1]`` entry is not look-ahead. Emits the per-event return series that
  the decay test (pre-2015 vs 2015→) consumes.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .book import SwingTrade, make_trade
from .signals import sma, wilder_rsi


def load_fomc_calendar(path: str | Path) -> pd.DatetimeIndex:
    """Load committed, source-cited scheduled FOMC decision dates (data/fomc_meetings.csv)."""
    df = pd.read_csv(path)
    dates = pd.to_datetime(df["decision_date"]).dt.normalize()
    return pd.DatetimeIndex(sorted(dates.unique()))


# --------------------------------------------------------------------------- #
# S1 — short-term oversold mean reversion (RSI-2)
# --------------------------------------------------------------------------- #
def s1_symbol_trades(symbol: str, df: pd.DataFrame, *, side_frac: float,
                     rsi_period: int = 2, rsi_entry: float = 10.0,
                     rsi_exit: float = 60.0, sma_len: int = 200,
                     max_hold: int = 5) -> list:
    """All non-overlapping S1 trades for one symbol's daily frame."""
    df = df.sort_values("date").reset_index(drop=True)
    dates = pd.DatetimeIndex(df["date"])
    close = df["close"].to_numpy(float)
    open_ = df["open"].to_numpy(float)
    rsi = wilder_rsi(pd.Series(close), rsi_period).to_numpy(float)
    sm = sma(pd.Series(close), sma_len).to_numpy(float)
    n = len(df)
    trades: list = []
    i = sma_len
    while i < n - 1:
        entry = (not np.isnan(rsi[i]) and not np.isnan(sm[i])
                 and rsi[i] < rsi_entry and close[i] > sm[i])
        if not entry:
            i += 1
            continue
        i_e = i + 1                          # execute at next open (T+1)
        p_e = open_[i_e]
        i_x = None
        for u in range(i_e, min(i_e + max_hold, n)):
            if not np.isnan(rsi[u]) and rsi[u] > rsi_exit:
                i_x = u + 1 if u + 1 < n else n - 1     # exit next open (or last bar)
                break
        if i_x is None:                      # time stop
            i_x = i_e + max_hold if i_e + max_hold < n else n - 1
        p_x = open_[i_x]
        trades.append(make_trade(symbol, dates, close, i_e, p_e, i_x, p_x, side_frac,
                                 reason=f"rsi2_oversold hold<= {max_hold}"))
        i = i_x                              # no overlap on the same symbol
    return trades


def s1_trades(frames_by_symbol: dict, *, side_frac: float, **kw) -> list:
    trades: list = []
    for sym, df in frames_by_symbol.items():
        if df is None or len(df) <= kw.get("sma_len", 200) + 1:
            continue
        trades.extend(s1_symbol_trades(sym, df, side_frac=side_frac, **kw))
    return trades


# --------------------------------------------------------------------------- #
# S5 — FOMC pre-meeting drift (SPY)
# --------------------------------------------------------------------------- #
def s5_fomc_trades(spy_df: pd.DataFrame, fomc_dates: pd.DatetimeIndex, *,
                   side_frac: float, entry_offset: int = 1, symbol: str = "SPY") -> tuple:
    """Enter ``close[T-offset]`` → exit ``close[T]`` for each scheduled decision ``T``.

    Returns ``(trades, event_rows)`` where each event row is
    ``{date, net_return, gross_return}`` — the per-event edge series the decay
    test splits at 2015.
    """
    df = spy_df.sort_values("date").reset_index(drop=True)
    dates = pd.DatetimeIndex(df["date"])
    close = df["close"].to_numpy(float)
    idx_of = {d: k for k, d in enumerate(dates)}
    trades: list = []
    event_rows: list = []
    for T in fomc_dates:
        T = pd.Timestamp(T).normalize()
        k = idx_of.get(T)
        if k is None:            # decision day not a trading day in this data window
            continue
        i_e = k - entry_offset
        if i_e < 1:
            continue
        tr = make_trade(symbol, dates, close, i_e, close[i_e], k, close[k], side_frac,
                        reason=f"fomc {T.date()} offset={entry_offset}")
        trades.append(tr)
        event_rows.append({"date": T, "net_return": tr.net_return,
                           "gross_return": tr.gross_return})
    return trades, event_rows
