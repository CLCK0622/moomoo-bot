from __future__ import annotations
import pandas as pd


def compute(df: pd.DataFrame, vol_spike_lookback: int = 20, vol_spike_mult: float = 2.0, **kwargs) -> pd.DataFrame:
    df = df.copy()
    vol_ma = df["volume"].rolling(window=vol_spike_lookback, min_periods=1).mean()
    df["volume_spike"] = df["volume"] > (vol_ma * vol_spike_mult)
    return df


def register_params(trial) -> dict:
    return {
        "use_volume_spike": trial.suggest_categorical("use_volume_spike", [True, False]),
        "vol_spike_lookback": trial.suggest_int("vol_spike_lookback", 10, 30),
        "vol_spike_mult": trial.suggest_float("vol_spike_mult", 1.5, 3.0),
    }
