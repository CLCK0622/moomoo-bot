from __future__ import annotations
import pandas as pd
import numpy as np


def compute(df: pd.DataFrame, rsi_period: int = 14, **kwargs) -> pd.DataFrame:
    df = df.copy()
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.rolling(window=rsi_period, min_periods=rsi_period).mean()
    avg_loss = loss.rolling(window=rsi_period, min_periods=rsi_period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))
    return df


def register_params(trial) -> dict:
    return {
        "use_rsi_filter": trial.suggest_categorical("use_rsi_filter", [True, False]),
        "rsi_period": trial.suggest_int("rsi_period", 6, 20),
        "rsi_overbought": trial.suggest_float("rsi_overbought", 65.0, 80.0),
        "rsi_oversold": trial.suggest_float("rsi_oversold", 20.0, 35.0),
    }
