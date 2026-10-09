from __future__ import annotations
import pandas as pd


def compute(df: pd.DataFrame, ema_fast: int = 9, ema_slow: int = 21, **kwargs) -> pd.DataFrame:
    df = df.copy()
    df["ema_fast_val"] = df["close"].ewm(span=ema_fast, adjust=False).mean()
    df["ema_slow_val"] = df["close"].ewm(span=ema_slow, adjust=False).mean()
    df["ema_bullish"] = df["ema_fast_val"] > df["ema_slow_val"]
    return df


def register_params(trial) -> dict:
    return {
        "use_ema_cross": trial.suggest_categorical("use_ema_cross", [True, False]),
        "ema_fast": trial.suggest_int("ema_fast", 5, 15),
        "ema_slow": trial.suggest_int("ema_slow", 15, 30),
    }
