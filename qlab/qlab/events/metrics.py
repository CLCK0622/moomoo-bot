"""EVO-12 §2 metrics, computed on a cost-after daily equity curve.

The vendored ``backtest/metrics.py`` is intraday-ORB specific and lacks the
geometric-CAGR / Sortino / drawdown-duration definitions EVO-12 pins down, so
this is a clean re-implementation to the EVO-12 §2 口径. Every metric is derived
from the *cost-after* per-bar return series ``r_t`` and net equity ``E_t``.

Input contract — ``equity`` is a DataFrame with columns:
    ``date`` (trading day), ``equity`` (E_t, cost-after), ``ret`` (r_t, cost-after),
    ``traded_notional`` (two-sided notional traded that bar, for turnover).
``trade_log`` is a list of per-trade dicts each with a ``pnl`` (cost-after).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252


def _cagr(equity: np.ndarray, P: int) -> float:
    """Geometric annualized return (EVO-12 §2.1). NOT arithmetic extrapolation."""
    n = len(equity)
    if n < 2 or equity[0] <= 0:
        return 0.0
    total = equity[-1] / equity[0]
    if total <= 0:
        return -1.0
    return float(total ** (P / n) - 1.0)


def _max_drawdown(equity: np.ndarray) -> float:
    """Per-bar max drawdown (EVO-12 §2.2), reported as a positive fraction."""
    if len(equity) == 0:
        return 0.0
    peak = equity[0]
    mdd = 0.0
    for e in equity:
        peak = max(peak, e)
        if peak > 0:
            mdd = min(mdd, e / peak - 1.0)
    return abs(mdd)


def _drawdown_duration(equity: np.ndarray) -> dict:
    """Longest / median underwater spell in bars, and unrecovered-tail flag (§2.3)."""
    if len(equity) == 0:
        return {"max_underwater_bars": 0, "median_underwater_bars": 0.0, "unrecovered": False}
    peak = equity[0]
    spells: list[int] = []
    cur = 0
    for e in equity:
        if e >= peak:
            if cur > 0:
                spells.append(cur)
            cur = 0
            peak = e
        else:
            cur += 1
    unrecovered = cur > 0
    if cur > 0:
        spells.append(cur)
    return {
        "max_underwater_bars": int(max(spells)) if spells else 0,
        "median_underwater_bars": float(np.median(spells)) if spells else 0.0,
        "unrecovered": bool(unrecovered),
    }


def _sharpe(x: np.ndarray, P: int) -> float:
    """Annualized Sharpe on excess returns (EVO-12 §2.4, sample std ddof=1)."""
    if len(x) < 2:
        return 0.0
    std = np.std(x, ddof=1)
    if std <= 0:
        return 0.0
    return float(np.mean(x) / std * np.sqrt(P))


def _sortino(x: np.ndarray, P: int, mar: float) -> float:
    """Annualized Sortino (EVO-12 §2.5, downside deviation only)."""
    if len(x) < 2:
        return 0.0
    downside = np.minimum(x - mar, 0.0)
    dd = np.sqrt(np.mean(downside ** 2))
    if dd <= 0:
        return 0.0
    return float((np.mean(x) - mar) / dd * np.sqrt(P))


def _trade_stats(trade_log: list[dict]) -> dict:
    n = len(trade_log)
    if n == 0:
        return {"num_trades": 0, "win_rate": 0.0, "profit_factor": 0.0,
                "avg_winner": 0.0, "avg_loser": 0.0, "expectancy": 0.0}
    pnls = [t["pnl"] for t in trade_log]
    winners = [p for p in pnls if p > 0]
    losers = [p for p in pnls if p <= 0]
    win_rate = len(winners) / n
    gross_profit = sum(winners) if winners else 0.0
    gross_loss = sum(abs(p) for p in losers) if losers else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    avg_winner = float(np.mean(winners)) if winners else 0.0
    avg_loser = float(np.mean([abs(p) for p in losers])) if losers else 0.0
    expectancy = win_rate * avg_winner - (1 - win_rate) * avg_loser
    return {"num_trades": n, "win_rate": win_rate, "profit_factor": profit_factor,
            "avg_winner": avg_winner, "avg_loser": avg_loser, "expectancy": float(expectancy)}


def evo12_metrics(equity: pd.DataFrame, trade_log: list[dict], *,
                  P: int = TRADING_DAYS_PER_YEAR, rf_annual: float = 0.0,
                  mar: float = 0.0) -> dict:
    """Compute the EVO-12 §2 metric block from a cost-after equity curve."""
    if equity is None or len(equity) == 0:
        base = {"cagr": 0.0, "max_drawdown": 0.0, "sharpe": 0.0, "sortino": 0.0,
                "annualized_turnover": 0.0, "n_bars": 0, "n_years": 0.0}
        base.update(_drawdown_duration(np.array([])))
        base.update(_trade_stats(trade_log))
        return base

    eq = equity["equity"].to_numpy(dtype=float)
    r = equity["ret"].to_numpy(dtype=float)
    rf_bar = rf_annual / P
    x = r - rf_bar

    # annualized two-sided turnover (EVO-12 §2.8): mean(per-bar turnover) × P
    if "traded_notional" in equity.columns:
        eq_prev = np.concatenate([[eq[0]], eq[:-1]])
        with np.errstate(divide="ignore", invalid="ignore"):
            per_bar_turnover = np.where(eq_prev > 0, equity["traded_notional"].to_numpy(float) / eq_prev, 0.0)
        annualized_turnover = float(np.mean(per_bar_turnover) * P)
    else:
        annualized_turnover = 0.0

    out = {
        "cagr": _cagr(eq, P),
        "max_drawdown": _max_drawdown(eq),
        "sharpe": _sharpe(x, P),
        "sortino": _sortino(x, P, mar),
        "annualized_turnover": annualized_turnover,
        "n_bars": int(len(eq)),
        "n_years": float(len(eq) / P),
    }
    out.update(_drawdown_duration(eq))
    out.update(_trade_stats(trade_log))
    return out
