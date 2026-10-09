from __future__ import annotations
import pandas as pd
import numpy as np


def compute(df: pd.DataFrame, kc_period: int = 20, kc_atr_mult: float = 1.5, **kwargs) -> pd.DataFrame:
    df = df.copy()

    close = df["close_15m"]
    high = df["high_15m"]
    low = df["low_15m"]

    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)

    df["kc_atr"] = tr.rolling(window=kc_period, min_periods=kc_period).mean()
    df["kc_middle"] = close.rolling(window=kc_period, min_periods=kc_period).mean()
    df["kc_upper"] = df["kc_middle"] + kc_atr_mult * df["kc_atr"]
    df["kc_lower"] = df["kc_middle"] - kc_atr_mult * df["kc_atr"]

    return df


def register_params(trial) -> dict:
    return {
        "kc_period": trial.suggest_int("kc_period", 10, 30),
        "kc_atr_mult": trial.suggest_float("kc_atr_mult", 1.0, 3.0),
        "use_kc_trend": trial.suggest_categorical("use_kc_trend", [True, False]),
        "use_anti_chase": trial.suggest_categorical("use_anti_chase", [True, False]),
    }
