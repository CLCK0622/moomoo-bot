from __future__ import annotations
import pandas as pd


def compute(df: pd.DataFrame, macd_fast: int = 12, macd_slow: int = 26, macd_signal: int = 9, **kwargs) -> pd.DataFrame:
    df = df.copy()
    ema_fast = df["close"].ewm(span=macd_fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=macd_slow, adjust=False).mean()
    df["macd_line"] = ema_fast - ema_slow
    df["macd_signal_line"] = df["macd_line"].ewm(span=macd_signal, adjust=False).mean()
    df["macd_histogram"] = df["macd_line"] - df["macd_signal_line"]
    return df


def register_params(trial) -> dict:
    return {
        "use_macd_filter": trial.suggest_categorical("use_macd_filter", [True, False]),
        "macd_fast": trial.suggest_int("macd_fast", 8, 16),
        "macd_slow": trial.suggest_int("macd_slow", 20, 30),
        "macd_signal": trial.suggest_int("macd_signal", 6, 12),
    }
