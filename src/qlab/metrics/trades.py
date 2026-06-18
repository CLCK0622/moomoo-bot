"""Closed-trade reconstruction and trade statistics — v1.0 §2.6-2.7.

A "trade" is one full round trip: a same-direction position built up from 0 and
brought back to 0 (v1.0 §2.6 建议口径). Realised P&L per round trip is the net cash
flow over the cycle, which already includes slippage (folded into the execution
price) and commission. Positions still open at the end of the backtest are excluded
(unrealised) — standard for win-rate / profit-factor.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from ..backtest.engine import Trade

_EPS = 1e-9


def closed_trade_pnls(trades: list[Trade]) -> list[float]:
    """Return realised net P&L for each flat-to-flat round trip.

    Handles a position that flips sign in a single fill by splitting it at zero:
    the part that returns to flat closes one trade, the remainder opens the next.
    """
    pnls: list[float] = []
    pos = 0.0
    cash_cycle = 0.0  # net cash flow accumulated within the current open cycle

    for t in trades:
        signed = t.shares if t.side == "BUY" else -t.shares
        flips = pos != 0.0 and (pos > 0) != (signed > 0)
        if flips and abs(signed) > abs(pos) + _EPS:
            # Split: first close existing position to zero, then open the remainder.
            close_qty = -pos  # signed delta needed to reach flat
            frac = abs(close_qty) / abs(signed)
            cash_cycle += -(close_qty * t.price) - t.commission * frac
            pnls.append(cash_cycle)
            cash_cycle = 0.0
            remainder = signed - close_qty
            cash_cycle += -(remainder * t.price) - t.commission * (1.0 - frac)
            pos = remainder
        else:
            cash_cycle += -(signed * t.price) - t.commission
            pos += signed
            if abs(pos) < _EPS:
                pnls.append(cash_cycle)
                cash_cycle = 0.0
                pos = 0.0
    return pnls


@dataclass
class TradeStats:
    n_closed_trades: int = 0
    win_rate: float = 0.0  # 胜率
    profit_loss_ratio: float = 0.0  # 盈亏比 = 平均盈利 / |平均亏损|
    profit_factor: float = 0.0  # 盈利因子 = 总盈利 / |总亏损|
    expectancy: float = 0.0  # 单笔期望

    def to_dict(self) -> dict:
        return asdict(self)


def trade_stats(pnls: list[float]) -> TradeStats:
    """胜率/盈亏比/盈利因子/期望 (v1.0 §2.6-2.7), 全部基于成本后每笔 P&L."""
    n = len(pnls)
    if n == 0:
        return TradeStats()
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]  # negative values
    win_rate = len(wins) / n
    avg_win = (sum(wins) / len(wins)) if wins else 0.0
    avg_loss = (-sum(losses) / len(losses)) if losses else 0.0  # positive magnitude
    gross_profit = sum(wins)
    gross_loss = -sum(losses)  # positive magnitude

    pl_ratio = (avg_win / avg_loss) if avg_loss > 0 else (float("inf") if avg_win > 0 else 0.0)
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    else:
        profit_factor = float("inf") if gross_profit > 0 else 0.0
    expectancy = win_rate * avg_win - (1.0 - win_rate) * avg_loss
    return TradeStats(
        n_closed_trades=n,
        win_rate=win_rate,
        profit_loss_ratio=pl_ratio,
        profit_factor=profit_factor,
        expectancy=expectancy,
    )
