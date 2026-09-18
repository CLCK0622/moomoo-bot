from __future__ import annotations
import pandas as pd


def compute(df: pd.DataFrame, **kwargs) -> pd.DataFrame:
    df = df.copy()
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    tp_vol = typical_price * df["volume"]

    df["vwap"] = float("nan")
    for date, group in df.groupby("date"):
        idx = group.index
        cum_tp_vol = tp_vol.loc[idx].cumsum()
        cum_vol = df.loc[idx, "volume"].cumsum()
        df.loc[idx, "vwap"] = cum_tp_vol / cum_vol

    return df


def register_params(trial) -> dict:
    return {}
