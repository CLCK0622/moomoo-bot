"""Signal-agnostic swing portfolio simulator: trades -> daily equity curve.

A :class:`SwingTrade` is a resolved single-name long with its cost-after per-day
return already attributed (mirroring ``events.strategy.EventTrade``). The book
runs an equal-weight sleeve of at most ``max_concurrent`` concurrent positions,
each sized ``1/max_concurrent`` of capital; unused capital sits in cash (``rf``).
Over-capacity entries are *capacity-skipped* (recorded, not silently dropped),
admitted by interval scheduling exactly like the event backtester's heap.

The output equity frame carries the columns the EVO-12 stack expects verbatim —
``date, equity, ret, traded_notional`` — so it flows straight into
``events.metrics.evo12_metrics`` and ``events.gates`` with no adaptation.

Execution realism (EVO-12 §4): entries/exits price at an explicit execution
price on an explicit bar (the strategy decides open[T+1] vs close), never a bar
the signal itself could not have traded; each side pays ``side_frac`` cost.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class SwingTrade:
    """One resolved single-name long, cost-after per-day contribution attributed."""

    symbol: str
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    daily_returns: dict = field(default_factory=dict)   # Timestamp -> cost-after ret
    net_return: float = 0.0
    gross_return: float = 0.0
    hold_days: int = 0
    reason: str = ""


def make_trade(symbol: str, dates, close, i_e: int, p_e: float, i_x: int, p_x: float,
               side_frac: float, reason: str = "") -> SwingTrade:
    """Attribute a long from execution ``(i_e, p_e)`` to ``(i_x, p_x)`` per day.

    ``dates`` is the symbol's ``DatetimeIndex`` and ``close`` its close array.
    Entry pays ``side_frac`` on the entry bar, exit pays ``side_frac`` on the exit
    bar; middle bars are plain close-to-close. Costs are embedded in
    ``daily_returns`` so the book never re-charges them.
    """
    close = np.asarray(close, dtype=float)
    daily: dict = {}
    if i_x <= i_e:
        # same-bar round trip (degenerate; kept for completeness)
        daily[dates[i_e]] = p_x / p_e - 1.0 - 2.0 * side_frac
    else:
        daily[dates[i_e]] = close[i_e] / p_e - 1.0 - side_frac           # entry leg
        for j in range(i_e + 1, i_x):
            daily[dates[j]] = close[j] / close[j - 1] - 1.0              # hold legs
        daily[dates[i_x]] = p_x / close[i_x - 1] - 1.0 - side_frac       # exit leg
    net = float(np.prod([1.0 + r for r in daily.values()]) - 1.0)
    # gross = same path without the two cost deductions
    gross_daily = dict(daily)
    if i_x <= i_e:
        gross_daily[dates[i_e]] = p_x / p_e - 1.0
    else:
        gross_daily[dates[i_e]] = close[i_e] / p_e - 1.0
        gross_daily[dates[i_x]] = p_x / close[i_x - 1] - 1.0
    gross = float(np.prod([1.0 + r for r in gross_daily.values()]) - 1.0)
    return SwingTrade(symbol=symbol, entry_date=dates[i_e], exit_date=dates[i_x],
                      daily_returns=daily, net_return=net, gross_return=gross,
                      hold_days=int(i_x - i_e), reason=reason)


def _admit(trades, max_concurrent: int):
    """Interval-schedule admission under a concurrency cap (heap of exit dates).

    A slot frees strictly before a new entry (``exit_date < entry_date``) — a
    deliberately conservative handoff rule that can never over-deploy capital.
    Returns ``(admitted, capacity_skipped)``.
    """
    order = sorted(trades, key=lambda t: (t.entry_date, t.exit_date, t.symbol))
    open_exits: list = []
    admitted, skipped = [], 0
    for tr in order:
        while open_exits and open_exits[0] < tr.entry_date:
            heapq.heappop(open_exits)
        if len(open_exits) < max_concurrent:
            heapq.heappush(open_exits, tr.exit_date)
            admitted.append(tr)
        else:
            skipped += 1
    return admitted, skipped


def simulate_book(trades, calendar, *, max_concurrent: int,
                  rf_annual: float = 0.0, P: int = 252) -> tuple:
    """Aggregate admitted trades into a daily equity curve over ``calendar``.

    ``calendar`` is the full sequence of trading days to mark (cash on idle days).
    Returns ``(equity_df, diagnostics)`` where ``equity_df`` has columns
    ``date, ret, equity, traded_notional`` (EVO-12 contract).
    """
    admitted, skipped = _admit(trades, max_concurrent)
    w = 1.0 / max_concurrent
    cal = sorted(pd.Timestamp(d) for d in calendar)
    ret_by_date = {d: 0.0 for d in cal}
    notional_by_date = {d: 0.0 for d in cal}
    active_by_date = {d: 0 for d in cal}

    for tr in admitted:
        for d, r in tr.daily_returns.items():
            d = pd.Timestamp(d)
            if d in ret_by_date:
                ret_by_date[d] += w * r
                active_by_date[d] += 1
        for d in (pd.Timestamp(tr.entry_date), pd.Timestamp(tr.exit_date)):
            if d in notional_by_date:
                notional_by_date[d] += w      # one side (buy on entry, sell on exit)

    rf_bar = rf_annual / P
    rows = []
    eq = 1.0
    for d in cal:
        deployed = min(1.0, w * active_by_date[d])
        r = ret_by_date[d] + (1.0 - deployed) * rf_bar
        eq *= (1.0 + r)
        rows.append((d, r, eq, notional_by_date[d]))
    equity_df = pd.DataFrame(rows, columns=["date", "ret", "equity", "traded_notional"])

    trade_log = [{"pnl": tr.net_return, "symbol": tr.symbol,
                  "entry": str(pd.Timestamp(tr.entry_date).date()),
                  "exit": str(pd.Timestamp(tr.exit_date).date()),
                  "hold_days": tr.hold_days} for tr in admitted]
    diagnostics = {
        "n_trades_generated": len(trades),
        "n_trades_admitted": len(admitted),
        "capacity_skipped": skipped,
        "max_concurrent": max_concurrent,
        "sleeve_weight": w,
        "n_calendar_days": len(cal),
        "n_active_days": int(sum(1 for d in cal if active_by_date[d] > 0)),
        "mean_active_positions": float(np.mean([active_by_date[d] for d in cal])) if cal else 0.0,
    }
    return equity_df, diagnostics, trade_log
