from __future__ import annotations
import numpy as np


def compute_metrics(trade_log: list[dict], daily_pnl: list[dict]) -> dict:
    num_trades = len(trade_log)
    if num_trades == 0:
        win_rate = 0.0; profit_factor = 0.0; avg_winner = 0.0; avg_loser = 0.0
    else:
        winners = [t["pnl"] for t in trade_log if t["pnl"] > 0]
        losers = [t["pnl"] for t in trade_log if t["pnl"] <= 0]
        win_rate = len(winners) / num_trades
        gross_profit = sum(winners) if winners else 0.0
        gross_loss = sum(abs(l) for l in losers) if losers else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
        avg_winner = float(np.mean(winners)) if winners else 0.0
        avg_loser = float(np.mean([abs(l) for l in losers])) if losers else 0.0

    equities = [d["equity"] for d in daily_pnl]
    daily_returns = [d["daily_return"] for d in daily_pnl if d["daily_return"] != 0]

    total_return_pct = (equities[-1] - equities[0]) / equities[0] if len(equities) >= 2 else 0.0

    if len(daily_returns) >= 2:
        returns_arr = np.array(daily_returns) / equities[0]
        std = np.std(returns_arr, ddof=1)
        sharpe_ratio = float(np.mean(returns_arr) / std * np.sqrt(252)) if std > 0 else 0.0
    else:
        sharpe_ratio = 0.0

    peak = equities[0] if equities else 0
    max_dd = 0.0
    for eq in equities:
        peak = max(peak, eq)
        dd = (peak - eq) / peak
        max_dd = max(max_dd, dd)

    return {
        "sharpe_ratio": sharpe_ratio, "total_return_pct": total_return_pct,
        "win_rate": win_rate, "profit_factor": profit_factor,
        "max_drawdown_pct": max_dd, "num_trades": num_trades,
        "avg_winner": avg_winner, "avg_loser": avg_loser,
    }
