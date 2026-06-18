from __future__ import annotations
import pandas as pd
import numpy as np


def compute(df: pd.DataFrame, adx_period: int = 14, **kwargs) -> pd.DataFrame:
    df = df.copy()
    high = df["high"]
    low = df["low"]
    close = df["close"]

    plus_dm = high.diff().clip(lower=0)
    minus_dm = (-low.diff()).clip(lower=0)
    # Only keep the larger directional move
    plus_dm[plus_dm < minus_dm] = 0
    minus_dm[minus_dm < plus_dm] = 0

    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)

    atr = tr.ewm(span=adx_period, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(span=adx_period, adjust=False).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(span=adx_period, adjust=False).mean() / atr)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    df["adx"] = dx.ewm(span=adx_period, adjust=False).mean()

    return df


def register_params(trial) -> dict:
    return {
        "adx_period": trial.suggest_int("adx_period", 10, 20),
        "adx_trend_threshold": trial.suggest_float("adx_trend_threshold", 20.0, 30.0),
    }
