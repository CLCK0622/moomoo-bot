from __future__ import annotations
import pandas as pd


def compute(df: pd.DataFrame, atr_pctl_lookback: int = 20, atr_pctl_threshold: float = 0.5, **kwargs) -> pd.DataFrame:
    df = df.copy()
    tr = pd.concat([
        df["high_15m"] - df["low_15m"],
        (df["high_15m"] - df["close_15m"].shift(1)).abs(),
        (df["low_15m"] - df["close_15m"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(window=atr_pctl_lookback, min_periods=1).mean()
    df["atr_percentile"] = atr.rolling(window=atr_pctl_lookback, min_periods=1).rank(pct=True)
    df["atr_high_vol"] = df["atr_percentile"] >= atr_pctl_threshold
    return df


def register_params(trial) -> dict:
    return {
        "use_atr_pctl_filter": trial.suggest_categorical("use_atr_pctl_filter", [True, False]),
        "atr_pctl_lookback": trial.suggest_int("atr_pctl_lookback", 10, 30),
        "atr_pctl_threshold": trial.suggest_float("atr_pctl_threshold", 0.4, 0.8),
    }
