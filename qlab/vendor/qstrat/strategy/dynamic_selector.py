from __future__ import annotations
import pandas as pd
import numpy as np
from collections import defaultdict


class DynamicStockScorer:
    """Dynamically score stocks based on recent tradability metrics.
    Combines ATR expansion, relative volume, ADX trending, and rolling P&L history."""

    def __init__(self, params: dict):
        self.atr_ratio_min = params.get("dyn_atr_ratio_min", 1.1)
        self.rvol_min = params.get("dyn_rvol_min", 1.3)
        self.adx_threshold = params.get("adx_trend_threshold", 25.0)
        self.lookback_days = params.get("dyn_lookback_days", 20)
        self.min_trades = params.get("dyn_min_trades", 3)
        self.top_n = params.get("dyn_top_n", 20)
        # Rolling trade history per stock
        self.trade_history: dict[str, list[dict]] = defaultdict(list)

    def record_trade(self, symbol: str, pnl: float, date):
        self.trade_history[symbol].append({"pnl": pnl, "date": date})

    def score_stocks(
        self,
        day_data: dict[str, pd.DataFrame],
        prev_day_data: dict[str, pd.DataFrame],
        current_date,
    ) -> list[str]:
        scores = {}

        for symbol, df in day_data.items():
            score = 0.0

            # Factor 1: ATR expansion (5d ATR / 20d ATR > threshold)
            if symbol in prev_day_data and len(prev_day_data[symbol]) >= 20:
                pdf = prev_day_data[symbol]
                tr = pd.concat([
                    pdf["high"] - pdf["low"],
                    (pdf["high"] - pdf["close"].shift(1)).abs(),
                    (pdf["low"] - pdf["close"].shift(1)).abs(),
                ], axis=1).max(axis=1)
                atr_5 = tr.tail(5).mean()
                atr_20 = tr.tail(20).mean()
                atr_ratio = atr_5 / atr_20 if atr_20 > 0 else 1.0
                if atr_ratio >= self.atr_ratio_min:
                    score += 2.0
                else:
                    score += atr_ratio * 0.5

            # Factor 2: Relative volume
            if symbol in prev_day_data and len(prev_day_data[symbol]) > 0:
                pdf = prev_day_data[symbol]
                recent_vol = pdf.iloc[-1]["volume"] if len(pdf) > 0 else 0
                avg_vol = pdf["volume"].tail(20).mean()
                rvol = recent_vol / avg_vol if avg_vol > 0 else 1.0
                if rvol >= self.rvol_min:
                    score += 1.5
                else:
                    score += rvol * 0.3

            # Factor 3: ADX trending
            adx_val = df.iloc[-1].get("adx") if len(df) > 0 else None
            if adx_val is not None and not pd.isna(adx_val):
                if adx_val >= self.adx_threshold:
                    score += 2.0
                elif adx_val >= 20:
                    score += 0.5

            # Factor 4: Rolling strategy performance
            trades = self.trade_history.get(symbol, [])
            recent_trades = [t for t in trades if t.get("date") is not None][-self.lookback_days:]
            if len(recent_trades) >= self.min_trades:
                wins = sum(1 for t in recent_trades if t["pnl"] > 0)
                total_pnl = sum(t["pnl"] for t in recent_trades)
                win_rate = wins / len(recent_trades)
                if win_rate > 0.5 and total_pnl > 0:
                    score += 3.0
                elif win_rate > 0.4:
                    score += 1.0
                elif win_rate < 0.3:
                    score -= 2.0

            scores[symbol] = score

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [sym for sym, s in ranked[:self.top_n] if s > 0]
