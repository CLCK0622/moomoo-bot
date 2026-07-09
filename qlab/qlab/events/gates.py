"""EVO-12 §3 门禁 — the four gates plus walk-forward, on a daily equity curve.

Gate 1 全样本, Gate 2 分年度一致性, Gate 3 滚动窗口稳定性, Gate 4 样本外/Walk-Forward.
Each returns the concrete numbers that drove the pass/fail (EVO-12: "任何一关报告
里都要给出导致不过的具体数字"). ``verdict`` mirrors the §3 summary rule:
候选通过 / 稳定性不足未过线 / 基线未达标.

The thresholds are the project's hard standard: CAGR ≥ 50%, MDD ≤ 20%, with the
per-gate tolerances EVO-12 specifies (per-year ≥ 35% floor & no negative year;
rolling median ≥ 50%, ≥ 70% of windows ≥ 50%, ≤ 10% negative, every window
MDD ≤ 20%).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .metrics import _cagr, _max_drawdown, TRADING_DAYS_PER_YEAR

CAGR_HURDLE = 0.50
MDD_CAP = 0.20
YEAR_CAGR_FLOOR = 0.35
ROLL_HIT_FRAC = 0.70
ROLL_NEG_FRAC_CAP = 0.10


def _sub_equity_stats(ret: np.ndarray, P: int) -> tuple[float, float]:
    """(CAGR, MDD) rebuilt from a slice of per-bar returns."""
    if len(ret) < 2:
        return 0.0, 0.0
    eq = np.cumprod(1.0 + ret)
    return _cagr(eq, P), _max_drawdown(eq)


def gate1_full_sample(equity: pd.DataFrame, P: int = TRADING_DAYS_PER_YEAR) -> dict:
    eq = equity["equity"].to_numpy(float)
    cagr = _cagr(eq, P)
    mdd = _max_drawdown(eq)
    return {"cagr": cagr, "mdd": mdd, "passed": bool(cagr >= CAGR_HURDLE and mdd <= MDD_CAP)}


def gate2_yearly(equity: pd.DataFrame, P: int = TRADING_DAYS_PER_YEAR) -> dict:
    if len(equity) == 0:
        return {"years": [], "worst_year_cagr": None, "combined_cagr": 0.0, "passed": False}
    e = equity.copy()
    e["year"] = pd.DatetimeIndex(e["date"]).year
    years = []
    ok = True
    for y, g in e.groupby("year"):
        cagr, mdd = _sub_equity_stats(g["ret"].to_numpy(float), P)
        full_year = len(g) >= int(0.6 * P)   # flag stub years (< ~60% of a year)
        row = {"year": int(y), "cagr": cagr, "mdd": mdd, "n_bars": int(len(g)), "full_year": full_year}
        years.append(row)
        if full_year:
            if cagr < YEAR_CAGR_FLOOR or cagr < 0 or mdd > MDD_CAP:
                ok = False
    combined = _cagr(equity["equity"].to_numpy(float), P)
    worst = min((r["cagr"] for r in years if r["full_year"]), default=None)
    return {"years": years, "worst_year_cagr": worst, "combined_cagr": combined,
            "passed": bool(ok and combined >= CAGR_HURDLE and len(years) > 0)}


def gate3_rolling(equity: pd.DataFrame, P: int = TRADING_DAYS_PER_YEAR,
                  window_months: int = 12, step_months: int = 1) -> dict:
    if len(equity) < P:
        return {"n_windows": 0, "passed": False, "reason": "sample_shorter_than_one_window"}
    e = equity.set_index(pd.DatetimeIndex(equity["date"]))
    start = e.index[0]
    end = e.index[-1]
    win = pd.DateOffset(months=window_months)
    step = pd.DateOffset(months=step_months)
    cagrs, mdds = [], []
    cursor = start
    while cursor + win <= end + pd.Timedelta(days=1):
        seg = e.loc[cursor:cursor + win]
        if len(seg) >= int(0.5 * P):
            c, m = _sub_equity_stats(seg["ret"].to_numpy(float), P)
            cagrs.append(c)
            mdds.append(m)
        cursor = cursor + step
    if not cagrs:
        return {"n_windows": 0, "passed": False, "reason": "no_full_windows"}
    arr = np.array(cagrs)
    hit = float(np.mean(arr >= CAGR_HURDLE))
    neg = float(np.mean(arr < 0))
    max_mdd = float(np.max(mdds))
    med = float(np.median(arr))
    passed = bool(med >= CAGR_HURDLE and hit >= ROLL_HIT_FRAC and
                  neg <= ROLL_NEG_FRAC_CAP and max_mdd <= MDD_CAP)
    return {
        "n_windows": len(cagrs),
        "cagr_min": float(arr.min()), "cagr_p25": float(np.quantile(arr, 0.25)),
        "cagr_median": med, "cagr_p75": float(np.quantile(arr, 0.75)),
        "cagr_max": float(arr.max()), "hit_frac": hit, "neg_frac": neg,
        "rolling_mdd_max": max_mdd, "passed": passed,
    }


def three_gate_verdict(g1: dict, g2: dict, g3: dict) -> str:
    if not g1["passed"]:
        return "基线未达标"
    if g2["passed"] and g3["passed"]:
        return "候选通过(关1-3;需关4样本外确认)"
    return "稳定性不足未过线"


def walk_forward(bt, *, train_months: int = 24, test_months: int = 6,
                 step_months: int = 6) -> dict:
    """Rolling walk-forward (EVO-12 §3 关4, main 口径).

    For each fold: fit the surprise thresholds on the *training* window's events
    only (quantile mode) and apply them to the disjoint test window (analyst mode
    needs no fit). The test windows' daily returns are stitched into one OOS
    equity curve, on which gates 1–3 are recomputed. No future information ever
    reaches a test window.
    """
    if not bt._prepared:
        bt.prepare()
    from .surprise import QuantileThresholds

    dates = [ev.announce_date for ev in bt._events]
    if not dates:
        return {"folds": 0, "passed": False, "reason": "no_events"}
    t0 = min(dates)
    tend = max(dates)

    oos_ret = {}          # date -> summed slot-weighted return (disjoint folds)
    oos_notional = {}
    folds = []
    cursor = t0
    train = pd.DateOffset(months=train_months)
    test = pd.DateOffset(months=test_months)
    step = pd.DateOffset(months=step_months)

    while cursor + train < tend + pd.Timedelta(days=1):
        train_lo, train_hi = cursor, cursor + train
        test_lo, test_hi = train_hi, train_hi + test
        train_idx = [i for i, d in enumerate(dates) if train_lo <= d < train_hi]
        test_idx = [i for i, d in enumerate(dates) if test_lo <= d < test_hi]
        cursor = cursor + step
        if not test_idx:
            continue
        thr = None
        if bt.surprise_mode == "quantile":
            thr = QuantileThresholds.fit([bt._reactions[i] for i in train_idx], bt.quantile)
        res = bt.run(event_idx=test_idx, thresholds=thr)
        eq = res["equity"]
        folds.append({"train": [str(train_lo.date()), str(train_hi.date())],
                      "test": [str(test_lo.date()), str(test_hi.date())],
                      "n_train": len(train_idx), "n_test": len(test_idx),
                      "n_admitted": res["diagnostics"]["n_admitted"]})
        if len(eq) == 0:
            continue
        for _, row in eq.iterrows():
            d = pd.Timestamp(row["date"])
            oos_ret[d] = oos_ret.get(d, 0.0) + float(row["ret"])
            oos_notional[d] = oos_notional.get(d, 0.0) + float(row["traded_notional"])

    if not oos_ret:
        return {"folds": len(folds), "fold_detail": folds, "passed": False,
                "reason": "no_out_of_sample_returns"}

    idx = pd.DatetimeIndex(sorted(oos_ret))
    ret = np.array([oos_ret[d] for d in idx])
    oos_equity = pd.DataFrame({
        "date": idx, "equity": np.cumprod(1.0 + ret), "ret": ret,
        "traded_notional": np.array([oos_notional[d] for d in idx]),
    })
    g1 = gate1_full_sample(oos_equity, bt.P)
    g2 = gate2_yearly(oos_equity, bt.P)
    g3 = gate3_rolling(oos_equity, bt.P)
    return {
        "folds": len(folds), "fold_detail": folds,
        "oos_gate1": g1, "oos_gate2": g2, "oos_gate3": g3,
        "oos_cagr": g1["cagr"], "oos_mdd": g1["mdd"],
        "passed": bool(g1["passed"] and g3["passed"]),
        "oos_equity": oos_equity,
    }
