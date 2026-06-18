from __future__ import annotations
import pandas as pd
import numpy as np


class StockInPlaySelector:
    """Select 'stocks in play' using gap% and early volume surge."""

    def __init__(self, params: dict):
        self.top_n = params.get("stocks_in_play_n", 20)
        self.min_gap_pct = params.get("min_gap_pct", 0.005)

    def select(
        self, day_data: dict[str, pd.DataFrame], prev_day_data: dict[str, pd.DataFrame],
        orb_minutes: int
    ) -> list[str]:
        scores = {}
        for symbol, df in day_data.items():
            if len(df) < orb_minutes or symbol not in prev_day_data:
                continue

            prev_df = prev_day_data[symbol]
            if prev_df.empty:
                continue

            # Gap: today's open vs yesterday's close
            today_open = df.iloc[0]["open"]
            prev_close = prev_df.iloc[-1]["close"]
            gap_pct = abs(today_open - prev_close) / prev_close

            # Early volume surge: first orb_minutes volume vs prev day avg
            orb_volume = df.iloc[:orb_minutes]["volume"].sum()
            prev_avg_vol = prev_df["volume"].mean() * orb_minutes
            vol_ratio = orb_volume / prev_avg_vol if prev_avg_vol > 0 else 1.0

            if gap_pct >= self.min_gap_pct:
                scores[symbol] = gap_pct * vol_ratio
            else:
                scores[symbol] = vol_ratio * 0.1

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [sym for sym, _ in ranked[:self.top_n]]


class RegimeDetector:
    """Detect market regime using ATR-based volatility (proxy for VIX)."""

    def __init__(self, params: dict):
        self.lookback = params.get("regime_lookback", 20)

    def detect(self, daily_atr_history: list[float]) -> str:
        """Returns 'high_vol', 'low_vol', or 'neutral'."""
        if len(daily_atr_history) < self.lookback:
            return "neutral"

        recent = daily_atr_history[-self.lookback:]
        current = recent[-1]
        pctl = sum(1 for x in recent if x <= current) / len(recent)

        if pctl >= 0.67:
            return "high_vol"
        elif pctl <= 0.33:
            return "low_vol"
        return "neutral"
