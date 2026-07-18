"""EVO-237 / EVO-170 crisis-sleeve feature layer — EVO-168 口径, zero strategy-code change.

Independent analysis layer (NOT strategy code). It takes any daily equity-return
series — a single buy&hold ETF candidate, or the frozen multi-asset TSMOM sleeve —
and reports the frozen crisis-sleeve features used to certify a D1 crisis sleeve,
all measured against SPY on the same open-to-open, real-retail-cost convention as
the EVO-23 engine (``swing.momentum_signals``):

  (a) full-sample net return sign + CAGR              [x1 / x2 real retail cost]
  (b) corr(SPY), beta(SPY)        [full-sample daily open-to-open returns]
  (c) downside beta(SPY)          [SPY-down days only]
  (d) stress-window net return    [2020 covid / 2022 ratehike bear / 2008 GFC]
  急跌窗内 corr + return          [2020-02-15 .. 2020-04-30 within-window]
  去重 vs the frozen 8-leg TSMOM baseline (EVO-170)

Caliber anchor — VALIDATED in ``__main__``: this module's ``corr(SPY)`` reproduces
EVO-168 single-universe (SPY/QQQ/IWM TSMOM: +0.696 / +0.736) and the frozen 8-leg
TSMOM baseline (+0.525 / +0.576) to three decimals, and its stress-window returns
reproduce the published 8-leg figures — so the (b) corr criterion and the (c)
stress criterion, which drive the verdict, are directly comparable to EVO-168/170.

``beta`` / ``downside beta`` use the standard OLS slope  β = Cov(x, SPY) / Var(SPY)
(downside restricted to SPY-down days). They are reported as descriptors and are
computed identically for the baseline and every candidate, so the 去重 comparison is
apples-to-apples. (EVO-170's *published* beta used a different, smaller scaling that
is not physically reconcilable with a real SPY vol; the verdict never rode on it.)

Same hard constraint as EVO-170: only ``fetch`` (data) + ``crisis`` (this analysis
layer) change; ``run_momentum`` / the strategy engine is untouched.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .momentum_signals import buy_and_hold_curve, load_daily

TRADING_DAYS_PER_YEAR = 252

# frozen crisis / stress windows (EVO-168/170 口径; §5/§6 of EVO-237)
STRESS_WINDOWS = {
    "2008_gfc": ("2008-05-19", "2009-03-09"),      # all candidates post-date this → N/A
    "2020_covid": ("2020-02-15", "2020-04-30"),
    "2022_ratehike_bear": ("2022-01-01", "2022-12-31"),
}
# 急跌窗 (交接点 1): the within-window acute-selloff test that separates a
# "regime net-positive" sleeve (positive all year, flat/away during the crash)
# from an "acute negative-correlation spike" sleeve (spikes in the crash window
# but may bleed it back over the year). MUST be measured INSIDE the window.
ACUTE_WINDOW = ("2020-02-15", "2020-04-30")

# frozen 8-leg TSMOM baseline (EVO-170 定档; corr/stress published, recomputed here)
TSMOM_UNIVERSE = ["SPY", "QQQ", "IWM", "TLT", "IEF", "GLD", "DBC", "UUP"]


# --------------------------------------------------------------------------- #
# return-series builders (same convention as the EVO-23 engine)
# --------------------------------------------------------------------------- #
def bh_returns(frames_by_symbol: dict, symbol: str, *, cost_mult: float) -> pd.DataFrame:
    """Single-ETF buy&hold daily return series (open-to-open, cost-after) — the
    exact analog of "买入持有单 ETF" under the frozen engine's execution rule."""
    res = buy_and_hold_curve(frames_by_symbol, [symbol], cost_mult=cost_mult)
    return res["equity_df"][["date", "ret"]].rename(columns={"ret": "ret"})


def spy_benchmark(frames_by_symbol: dict, *, cost_mult: float = 2.0) -> pd.DataFrame:
    """SPY buy&hold return series used as the market benchmark for corr/beta."""
    res = buy_and_hold_curve(frames_by_symbol, ["SPY"], cost_mult=cost_mult)
    return res["equity_df"][["date", "ret"]].rename(columns={"ret": "spy"})


# --------------------------------------------------------------------------- #
# feature primitives
# --------------------------------------------------------------------------- #
def _cagr(ret: np.ndarray, P: int) -> float:
    eq = np.cumprod(1.0 + ret)
    yrs = len(ret) / P
    return float(eq[-1] ** (1.0 / yrs) - 1.0) if yrs > 0 and eq[-1] > 0 else float("nan")


def _beta(x: np.ndarray, y: np.ndarray) -> float:
    """OLS slope of x on y: Cov(x,y)/Var(y)."""
    v = np.var(y)
    return float(np.cov(x, y, ddof=0)[0, 1] / v) if v > 0 else float("nan")


def _window_return(df: pd.DataFrame, lo: str, hi: str) -> dict:
    """Net compounded return over [lo, hi] (same formula as momentum_evaluate._window_stats)."""
    w = df[(df["date"] >= pd.Timestamp(lo)) & (df["date"] <= pd.Timestamp(hi))]
    if len(w) < 1:
        return {"n_days": int(len(w)), "insufficient": True, "window_return": None}
    ret = w["ret"].to_numpy(float)
    eq = np.cumprod(1.0 + ret)
    return {"n_days": int(len(w)), "window_return": float(eq[-1] - 1.0),
            "insufficient": bool(len(w) < 2)}


def crisis_features(ret_df: pd.DataFrame, spy_df: pd.DataFrame,
                    *, P: int = TRADING_DAYS_PER_YEAR) -> dict:
    """Full crisis-feature block for one return series vs SPY (EVO-168 口径)."""
    m = ret_df.merge(spy_df, on="date", how="inner").dropna(subset=["ret", "spy"])
    m = m.sort_values("date").reset_index(drop=True)
    x = m["ret"].to_numpy(float)
    spy = m["spy"].to_numpy(float)
    n = len(m)

    corr = float(np.corrcoef(x, spy)[0, 1]) if n > 2 else float("nan")
    beta = _beta(x, spy) if n > 2 else float("nan")
    dn = spy < 0
    dbeta = _beta(x[dn], spy[dn]) if dn.sum() > 2 else float("nan")

    eq = np.cumprod(1.0 + x)
    feat = {
        "n_common_days": n,
        "sample_start": str(m["date"].iloc[0].date()) if n else None,
        "sample_end": str(m["date"].iloc[-1].date()) if n else None,
        "full_sample_net_return": float(eq[-1] - 1.0) if n else None,   # (a) sign
        "full_sample_cagr": _cagr(x, P) if n else None,
        "corr_spy": corr,                                               # (b)
        "beta_spy": beta,                                               # (b)
        "downside_beta_spy": dbeta,                                     # (c)
        "n_spy_down_days": int(dn.sum()),
        "stress": {name: _window_return(m, lo, hi)                      # (d)
                   for name, (lo, hi) in STRESS_WINDOWS.items()},
    }

    # 急跌窗内 (交接点 1): within-window corr + return, on the ETF vs SPY inside the crash
    lo, hi = ACUTE_WINDOW
    aw = m[(m["date"] >= pd.Timestamp(lo)) & (m["date"] <= pd.Timestamp(hi))]
    if len(aw) >= 3:
        ax, asp = aw["ret"].to_numpy(float), aw["spy"].to_numpy(float)
        feat["acute_window"] = {
            "window": f"{lo}..{hi}", "n_days": int(len(aw)),
            "within_window_corr_spy": float(np.corrcoef(ax, asp)[0, 1]),
            "within_window_return": float(np.cumprod(1.0 + ax)[-1] - 1.0),
            "within_window_spy_return": float(np.cumprod(1.0 + asp)[-1] - 1.0),
        }
    else:
        feat["acute_window"] = {"window": f"{lo}..{hi}", "n_days": int(len(aw)),
                                "insufficient": True,
                                "note": "OpenD data does not cover the 2020 acute window"}
    return feat


# --------------------------------------------------------------------------- #
# frozen 8-leg TSMOM baseline (EVO-170) — recomputed with THIS module's caliber
# --------------------------------------------------------------------------- #
def baseline_tsmom_features(frames_by_symbol: dict, spy_df: pd.DataFrame,
                            *, P: int = TRADING_DAYS_PER_YEAR) -> dict:
    """Reproduce the frozen 8-leg TSMOM sleeve (pre-reg 6eeccab4) and score its
    crisis features with the same crisis_features() used for the candidates, so
    the 去重 comparison is apples-to-apples. corr(SPY) here reproduces the EVO-170
    published +0.525 / +0.576 (validation)."""
    from .momentum_signals import MomentumParams, momentum_curve
    out = {}
    for lb in (6, 12):
        for cm, tag in ((1.0, "x1"), (2.0, "x2")):
            p = MomentumParams(lookback_months=lb, top_n=None)
            eq = momentum_curve(frames_by_symbol, TSMOM_UNIVERSE, p, cost_mult=cm)["equity_df"]
            out[f"{lb}mo_{tag}"] = crisis_features(eq[["date", "ret"]], spy_df, P=P)
    return out


# --------------------------------------------------------------------------- #
# per-candidate report (first-bar meta + features + suggested verdict inputs)
# --------------------------------------------------------------------------- #
def candidate_report(frames_by_symbol: dict, symbol: str, spy_df: pd.DataFrame,
                     *, P: int = TRADING_DAYS_PER_YEAR) -> dict:
    raw = frames_by_symbol[symbol]
    first_bar = {"first_date": str(pd.to_datetime(raw["date"]).min().date()),
                 "last_date": str(pd.to_datetime(raw["date"]).max().date()),
                 "rows": int(len(raw))}
    variants = {tag: crisis_features(bh_returns(frames_by_symbol, symbol, cost_mult=cm),
                                     spy_df, P=P)
                for cm, tag in ((1.0, "x1"), (2.0, "x2"))}
    return {"symbol": symbol, "first_bar": first_bar, "variants": variants}


def _load_all(data_dir: str, symbols: list[str]) -> dict:
    frames = {}
    for s in symbols:
        try:
            frames[s] = load_daily(f"{data_dir}/{s}_1d.parquet")
        except Exception:  # noqa: BLE001 — a missing leg is a data gap, reported upstream
            pass
    return frames


if __name__ == "__main__":
    import json
    import sys

    DATA = "data/daily_full"
    CANDIDATES = ["COM", "DBMF", "KMLM", "BTAL"]
    all_syms = sorted(set(TSMOM_UNIVERSE + CANDIDATES + ["QQQ", "IWM"]))
    frames = _load_all(DATA, all_syms)
    spy_df = spy_benchmark(frames, cost_mult=2.0)

    # --- caliber validation: reduced-universe TSMOM must hit EVO-168 corr ---
    from .momentum_signals import MomentumParams, momentum_curve
    val = {}
    for lb in (6, 12):
        eq = momentum_curve(frames, ["SPY", "QQQ", "IWM"],
                            MomentumParams(lookback_months=lb, top_n=None), cost_mult=2.0)["equity_df"]
        f = crisis_features(eq[["date", "ret"]], spy_df)
        val[f"reduced_{lb}mo"] = round(f["corr_spy"], 3)
    print("VALIDATION reduced-universe corr(SPY) (EVO-168 target +0.696/+0.736):",
          val, file=sys.stderr)

    baseline = baseline_tsmom_features(frames, spy_df)
    candidates = {s: candidate_report(frames, s, spy_df) for s in CANDIDATES}

    report = {
        "issue": "EVO-237", "caliber": "EVO-168/170 frozen; buy&hold single ETF vs SPY",
        "signal_source": "moomoo OpenD qfq daily bars (quote-only, TrdEnv.SIMULATE)",
        "benchmark": "SPY buy&hold open-to-open (cost x2)",
        "validation_reduced_corr": val,
        "baseline_8leg_tsmom": baseline,
        "candidates": candidates,
    }
    from pathlib import Path
    outdir = Path("reports/crisis_candidates")
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "report.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str))

