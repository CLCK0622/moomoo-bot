"""EVO-238 · D1 crisis-sleeve PORTFOLIO-level backtest — analysis/portfolio layer.

Runs the 吏部-frozen (2026-07-18) pre-registration spec for装入 the DBMF/KMLM/BTAL
crisis sleeve into the single-component 8-leg TSMOM net-positive base, and judges the
组合层 50/20 joint gate.  This is a PURE analysis/portfolio layer:  ``run_momentum`` /
the strategy engine are untouched (same hard constraint as EVO-170/237).  Legs are
rebuilt from committed OpenD daily bars via the frozen ``momentum_curve`` /
``buy_and_hold_curve``; stats reuse ``events.metrics`` / ``events.gates``.

Frozen spec (this module implements it verbatim, nothing tuned after seeing results):

  * Components:   BASE = 8-leg multi-asset TSMOM 12mo equity (the sole certified
                  net-positive base, N=1 first-check).  Sleeve = DBMF(main) +
                  KMLM(cross-val, short sample only) + BTAL(with/without arms).
  * Weighting:    inverse-volatility (∝ 1/σ_i), σ = trailing 63-trading-day realized
                  daily-return vol, computed CAUSALLY at each rebalance close (no
                  PnL fit, no look-ahead).
  * Rebalance:    monthly (main) — month-end decision close → next-open execution,
                  open-to-open, cost 10/20 bps/side (×cost_mult).  Weights drift
                  between rebalances.
  * Leverage:     1.0× (no leverage) is the ONLY PASS caliber.
  * BTAL cap:     with-BTAL arm gross ≤ 15% — if inverse-vol BTAL weight > 15%, snap
                  to 15% and re-normalize the rest by inverse-vol proportion.
  * Matrix 2×2:   {with-BTAL, no-BTAL} × {short (KMLM 2020-12→, avoids 2020 crash),
                  drop-KMLM long (BASE+DBMF, 2019-05→, incl 2020 covid + 2022)}.
  * PASS cell:    ONLY {no-BTAL × drop-KMLM long} = {BASE + DBMF} (main_pass_cell).
                  Other 3 cells are robustness附证; best-of-4 PASS ⇒ Bonferroni ×4.
  * Gate B:       组合日收益 stationary block bootstrap (Politis-Romano, mean block
                  ≈21, N=5000).  PASS = CAGR 5% lower bound ≥ 50% AND MDD 95% upper
                  bound ≤ 20%.  point-over-threshold but CI crossing = NOT pass.
  * Axis:         all present components + SPY inner-join single trading-day axis;
                  every n / corr / bootstrap / fold on that same axis.
  * fold:         weighting has no PnL-fit param → formal train/test re-fit N/A +
                  no-fit declaration; real regime folds F1(2006–2019) / F2(2019-05+) /
                  F3(2020-12+); stress 2020(02-15..04-30) / 2022 full year; 2008 N/A.

Boundaries (inherited, 一票否决): real retail cost ×1/×2 · SIMULATE-only (quote-only,
no order path touched) · account-level long-only · zero external data · zero engine
change · no options history.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .momentum_signals import (MomentumParams, buy_and_hold_curve, load_daily,
                               momentum_curve, _rebalance_mask)
from ..events.metrics import (_cagr, _max_drawdown, _sharpe, _sortino,
                              _drawdown_duration, TRADING_DAYS_PER_YEAR)
from ..events.gates import gate2_yearly

# frozen 8-leg TSMOM base universe (EVO-170 定档)
TSMOM_UNIVERSE = ["SPY", "QQQ", "IWM", "TLT", "IEF", "GLD", "DBC", "UUP"]
VOL_LOOKBACK = 63                       # trailing trading days for realized vol
BTAL_CAP = 0.15                         # with-BTAL arm gross cap (frozen §5)
STRESS_WINDOWS = {
    "2008_gfc": ("2008-05-19", "2009-03-09"),      # all sleeves post-date → N/A
    "2020_covid": ("2020-02-15", "2020-04-30"),
    "2022_ratehike_bear": ("2022-01-01", "2022-12-31"),
}
REGIME_FOLDS = {                        # real regime folds (no-fit; regime coverage)
    "F1_2006_2019": ("2006-01-01", "2018-12-31"),
    "F2_2019_05_plus": ("2019-05-01", "2026-12-31"),
    "F3_2020_12_plus": ("2020-12-01", "2026-12-31"),
}


# --------------------------------------------------------------------------- #
# component return-series builders (each on its own daily axis, cost-after)
# --------------------------------------------------------------------------- #
def base_component(frames: dict, *, cost_mult: float) -> pd.DataFrame:
    """8-leg TSMOM 12mo combined equity → daily (date, BASE) return series."""
    eq = momentum_curve(frames, TSMOM_UNIVERSE,
                        MomentumParams(lookback_months=12, top_n=None),
                        cost_mult=cost_mult)["equity_df"]
    return eq[["date", "ret"]].rename(columns={"ret": "BASE"})


def sleeve_component(frames: dict, symbol: str, *, cost_mult: float) -> pd.DataFrame:
    """Single-ETF buy&hold → daily (date, <symbol>) return series."""
    eq = buy_and_hold_curve(frames, [symbol], cost_mult=cost_mult)["equity_df"]
    return eq[["date", "ret"]].rename(columns={"ret": symbol})


def spy_series(frames: dict, *, cost_mult: float) -> pd.DataFrame:
    eq = buy_and_hold_curve(frames, ["SPY"], cost_mult=cost_mult)["equity_df"]
    return eq[["date", "ret"]].rename(columns={"ret": "spy"})


# --------------------------------------------------------------------------- #
# inverse-vol weighting with BTAL cap (frozen §2 / §5)
# --------------------------------------------------------------------------- #
def _inv_vol_target(sigma: np.ndarray, names: list[str], *,
                    btal_cap: float | None) -> np.ndarray:
    """Causal inverse-vol target weights; if with-BTAL and BTAL > cap, snap & renorm."""
    finite = np.isfinite(sigma) & (sigma > 0)
    if not finite.any():
        return np.full(len(sigma), 1.0 / len(sigma))
    inv = np.where(finite, 1.0 / np.where(sigma > 0, sigma, np.nan), 0.0)
    inv = np.nan_to_num(inv, nan=0.0)
    w = inv / inv.sum()
    if btal_cap is not None and "BTAL" in names:
        j = names.index("BTAL")
        if w[j] > btal_cap:
            others = [i for i in range(len(w)) if i != j]
            oinv = inv[others]
            w = w.copy()
            w[j] = btal_cap
            if oinv.sum() > 0:
                w[others] = (1.0 - btal_cap) * oinv / oinv.sum()
            else:                                    # degenerate: split evenly
                w[others] = (1.0 - btal_cap) / len(others)
    return w


# --------------------------------------------------------------------------- #
# portfolio construction on the unified inner-join axis
# --------------------------------------------------------------------------- #
def build_portfolio(components: dict[str, pd.DataFrame], spy: pd.DataFrame, *,
                    cost_mult: float, rebalance: str = "monthly",
                    btal_cap: float | None = None,
                    vol_lookback: int = VOL_LOOKBACK) -> dict:
    """Combine per-component daily return series into one portfolio equity curve.

    Inverse-vol weights are decided at each month-end close on the trailing
    ``vol_lookback`` returns (causal) and take effect the NEXT trading day
    (open-to-open); between rebalances weights drift with realized returns; a
    ``cost_mult × 10bps`` per-side turnover cost is charged on the cross-component
    rebalance. Returns the portfolio ``equity_df`` + aligned SPY + diagnostics.
    """
    names = list(components)
    merged = None
    for df in components.values():
        merged = df if merged is None else merged.merge(df, on="date", how="inner")
    merged = (merged.merge(spy, on="date", how="inner")
              .dropna().sort_values("date").reset_index(drop=True))
    if len(merged) < vol_lookback + 5:
        raise ValueError("axis shorter than vol lookback + margin")
    dates = pd.DatetimeIndex(merged["date"])
    R = merged[names].to_numpy(float)                 # n × k component returns
    spy_ret = merged["spy"].to_numpy(float)
    n, k = R.shape
    reb = _rebalance_mask(dates, "weekly" if rebalance == "weekly" else "monthly")
    side = 0.001 * cost_mult

    p_ret = np.full(n, np.nan)
    w = None                                          # current (drifting) weights
    pending = None                                    # target decided at close, applied next day
    active_from = None
    for t in range(n):
        cost_today = 0.0
        if pending is not None:                       # execute the decided rebalance at open t
            turnover = float(np.abs(pending - (w if w is not None else np.zeros(k))).sum())
            cost_today = side * turnover
            w = pending
            pending = None
            if active_from is None:
                active_from = t
        if w is not None:
            gross = float(np.dot(w, R[t]))
            p_ret[t] = gross - cost_today
            growth = w * (1.0 + R[t])                 # drift to end-of-day
            s = growth.sum()
            w = growth / s if s > 0 else w
        # decide next target at a month-end close, using returns through t (causal)
        if reb[t] and t >= vol_lookback:
            sigma = R[t - vol_lookback + 1:t + 1].std(axis=0, ddof=1)
            pending = _inv_vol_target(sigma, names, btal_cap=btal_cap)

    if active_from is None:
        raise ValueError("no rebalance ever deployed (insufficient history)")
    act = slice(active_from, n)
    pr = p_ret[act]
    eq_df = pd.DataFrame({"date": dates[act], "ret": pr})
    eq_df["equity"] = np.cumprod(1.0 + pr)
    spy_df = pd.DataFrame({"date": dates[act], "spy": spy_ret[act]})
    diag = {"components": names, "n_days": int(len(pr)),
            "sample_start": str(dates[active_from].date()),
            "sample_end": str(dates[-1].date()),
            "cost_mult": cost_mult, "rebalance": rebalance,
            "btal_cap": btal_cap, "vol_lookback": vol_lookback,
            "n_rebalances": int(reb[active_from:].sum())}
    return {"equity_df": eq_df[["date", "ret", "equity"]], "spy": spy_df, "diagnostics": diag}


# --------------------------------------------------------------------------- #
# metrics + corr(SPY) + stress + base-vs-portfolio delta
# --------------------------------------------------------------------------- #
def _corr_spy(ret: np.ndarray, spy: np.ndarray) -> float:
    if len(ret) < 3:
        return float("nan")
    return float(np.corrcoef(ret, spy)[0, 1])


def _window_return(dates: pd.DatetimeIndex, ret: np.ndarray, lo: str, hi: str) -> dict:
    m = (dates >= pd.Timestamp(lo)) & (dates <= pd.Timestamp(hi))
    w = ret[m]
    if len(w) < 1:
        return {"n_days": 0, "window_return": None, "insufficient": True}
    eq = np.cumprod(1.0 + w)
    return {"n_days": int(len(w)), "window_return": float(eq[-1] - 1.0),
            "window_mdd": float(_max_drawdown(eq)), "insufficient": bool(len(w) < 2)}


def portfolio_metrics(port: dict, *, P: int = TRADING_DAYS_PER_YEAR) -> dict:
    eq_df = port["equity_df"]
    ret = eq_df["ret"].to_numpy(float)
    eq = eq_df["equity"].to_numpy(float)
    spy = port["spy"]["spy"].to_numpy(float)
    dates = pd.DatetimeIndex(eq_df["date"])
    dd = _drawdown_duration(eq)
    yearly = gate2_yearly(eq_df[["date", "ret", "equity"]], P)
    return {
        "n_days": int(len(ret)),
        "sample_start": str(dates[0].date()), "sample_end": str(dates[-1].date()),
        "cagr": _cagr(eq, P), "max_drawdown": _max_drawdown(eq),
        "sharpe": _sharpe(ret, P), "sortino": _sortino(ret, P, 0.0),
        "corr_spy": _corr_spy(ret, spy),
        "max_underwater_bars": dd["max_underwater_bars"],
        "median_underwater_bars": dd["median_underwater_bars"],
        "unrecovered": dd["unrecovered"],
        "stress": {nm: _window_return(dates, ret, lo, hi)
                   for nm, (lo, hi) in STRESS_WINDOWS.items()},
        "yearly": [{"year": r["year"], "cagr": r["cagr"], "mdd": r["mdd"],
                    "n_bars": r["n_bars"], "full_year": r["full_year"]}
                   for r in yearly["years"]],
    }


# --------------------------------------------------------------------------- #
# Gate B — stationary block bootstrap (Politis-Romano), CAGR-LB + MDD-UB
# --------------------------------------------------------------------------- #
def _stationary_block_indices(n: int, mean_block: float,
                              rng: np.random.RandomState) -> np.ndarray:
    """Politis-Romano stationary bootstrap index vector (geometric block lengths,
    mean block ``mean_block``; circular wrap)."""
    p = 1.0 / max(mean_block, 1.0)
    idx = np.empty(n, dtype=int)
    idx[0] = rng.randint(0, n)
    coin = rng.random_sample(n)
    for i in range(1, n):
        idx[i] = rng.randint(0, n) if coin[i] < p else (idx[i - 1] + 1) % n
    return idx


def gate_b_bootstrap(ret: np.ndarray, *, P: int = TRADING_DAYS_PER_YEAR,
                     mean_block: float = 21.0, n_boot: int = 5000,
                     cagr_floor: float = 0.50, mdd_cap: float = 0.20,
                     seed: int = 238238) -> dict:
    """Frozen EVO-149-B: stationary block bootstrap of the portfolio daily return
    series; PASS = CAGR 5% lower bound ≥ cagr_floor AND MDD 95% upper bound ≤ mdd_cap.
    A point estimate over-threshold but with the CI crossing the gate is NOT a pass."""
    r = np.asarray([x for x in ret if x is not None and np.isfinite(x)], float)
    n = int(len(r))
    if n < 30:
        return {"degenerate": True, "n": n, "n_boot": 0,
                "note": "series too short for a meaningful bootstrap", "passed": False}
    rng = np.random.RandomState(seed)
    eq_pt = np.cumprod(1.0 + r)
    cagr_pt, mdd_pt = _cagr(eq_pt, P), _max_drawdown(eq_pt)
    cagr_b = np.empty(n_boot); mdd_b = np.empty(n_boot)
    for b in range(n_boot):
        rs = r[_stationary_block_indices(n, mean_block, rng)]
        e = np.cumprod(1.0 + rs)
        cagr_b[b] = _cagr(e, P); mdd_b[b] = _max_drawdown(e)
    cagr_lb = float(np.quantile(cagr_b, 0.05))
    mdd_ub = float(np.quantile(mdd_b, 0.95))
    cagr_ok = bool(cagr_lb >= cagr_floor)
    mdd_ok = bool(mdd_ub <= mdd_cap)
    return {
        "degenerate": False, "n": n, "n_boot": n_boot,
        "mean_block": mean_block, "seed": seed,
        "cagr_point": cagr_pt, "cagr_5pct_lb": cagr_lb,
        "cagr_median": float(np.median(cagr_b)),
        "mdd_point": mdd_pt, "mdd_95pct_ub": mdd_ub,
        "mdd_median": float(np.median(mdd_b)),
        "cagr_floor": cagr_floor, "mdd_cap": mdd_cap,
        "cagr_lb_passes": cagr_ok, "mdd_ub_passes": mdd_ok,
        "passed": bool(cagr_ok and mdd_ok),
        "note": ("point over threshold but CI crosses gate → NOT pass"
                 if (cagr_pt >= cagr_floor or mdd_pt <= mdd_cap) and not (cagr_ok and mdd_ok)
                 else "gate B evaluated on frozen stationary-block bootstrap"),
    }


# --------------------------------------------------------------------------- #
# base-alone reference (加 sleeve 前) on the SAME axis → 对照差
# --------------------------------------------------------------------------- #
def base_reference_on_axis(frames: dict, port_axis: pd.DatetimeIndex, *,
                           cost_mult: float, P: int = TRADING_DAYS_PER_YEAR) -> dict:
    """8-leg TSMOM base alone, restricted to the portfolio's active axis, so the
    加-sleeve-前 vs 加-sleeve-后 delta is apples-to-apples on one axis."""
    base = base_component(frames, cost_mult=cost_mult)
    spy = spy_series(frames, cost_mult=cost_mult)
    m = base.merge(spy, on="date", how="inner")
    m = m[m["date"].isin(port_axis)].sort_values("date").reset_index(drop=True)
    ret = m["BASE"].to_numpy(float); spyr = m["spy"].to_numpy(float)
    eq = np.cumprod(1.0 + ret)
    return {"n_days": int(len(m)), "cagr": _cagr(eq, P),
            "max_drawdown": _max_drawdown(eq), "corr_spy": _corr_spy(ret, spyr),
            "sharpe": _sharpe(ret, P)}


# --------------------------------------------------------------------------- #
# regime folds (no-fit; regime coverage) — per fold on present components
# --------------------------------------------------------------------------- #
def regime_folds(frames: dict, *, cost_mult: float,
                 P: int = TRADING_DAYS_PER_YEAR) -> dict:
    """Real regime folds (weighting has NO PnL-fit param → formal train/test re-fit
    is N/A; these are regime-coverage folds, not a fitted-OOS test)."""
    out = {"no_fit_declaration":
           "portfolio weighting = causal inverse-vol (trailing 63d realized σ); it "
           "has NO PnL-fit / optimized parameter, so a formal train/test re-fit is "
           "N/A. Folds below are regime-coverage checks on the frozen rule.",
           "folds": {}}
    for nm, (lo, hi) in REGIME_FOLDS.items():
        comps = {"BASE": base_component(frames, cost_mult=cost_mult)}
        if nm != "F1_2006_2019":
            comps["DBMF"] = sleeve_component(frames, "DBMF", cost_mult=cost_mult)
        if nm == "F3_2020_12_plus" and frames.get("KMLM") is not None:
            comps["KMLM"] = sleeve_component(frames, "KMLM", cost_mult=cost_mult)
        # restrict every component to the fold window before combining
        comps = {c: d[(d["date"] >= pd.Timestamp(lo)) & (d["date"] <= pd.Timestamp(hi))]
                 for c, d in comps.items()}
        spy = spy_series(frames, cost_mult=cost_mult)
        try:
            port = build_portfolio(comps, spy, cost_mult=cost_mult, rebalance="monthly")
            mt = portfolio_metrics(port, P=P)
            out["folds"][nm] = {"window": f"{lo}..{hi}", "components": list(comps),
                                "n_days": mt["n_days"], "cagr": mt["cagr"],
                                "max_drawdown": mt["max_drawdown"], "corr_spy": mt["corr_spy"]}
        except Exception as e:                       # noqa: BLE001 — short fold reported honestly
            out["folds"][nm] = {"window": f"{lo}..{hi}", "components": list(comps),
                                "insufficient": True, "note": str(e)}
    return out


# --------------------------------------------------------------------------- #
# one matrix cell  (arm × cohort)
# --------------------------------------------------------------------------- #
def run_cell(frames: dict, *, arm: str, cohort: str, cost_mult: float,
             is_pass_cell: bool, P: int = TRADING_DAYS_PER_YEAR) -> dict:
    comps = {"BASE": base_component(frames, cost_mult=cost_mult),
             "DBMF": sleeve_component(frames, "DBMF", cost_mult=cost_mult)}
    if cohort == "short":
        comps["KMLM"] = sleeve_component(frames, "KMLM", cost_mult=cost_mult)
    if arm == "with_btal":
        comps["BTAL"] = sleeve_component(frames, "BTAL", cost_mult=cost_mult)
    btal_cap = BTAL_CAP if arm == "with_btal" else None
    spy = spy_series(frames, cost_mult=cost_mult)
    port = build_portfolio(comps, spy, cost_mult=cost_mult, rebalance="monthly",
                           btal_cap=btal_cap)
    mt = portfolio_metrics(port, P=P)
    base_ref = base_reference_on_axis(frames, pd.DatetimeIndex(port["equity_df"]["date"]),
                                      cost_mult=cost_mult, P=P)
    delta = {"d_cagr": mt["cagr"] - base_ref["cagr"],
             "d_mdd": mt["max_drawdown"] - base_ref["max_drawdown"],
             "mdd_reduction": base_ref["max_drawdown"] - mt["max_drawdown"],
             "d_corr": mt["corr_spy"] - base_ref["corr_spy"]}
    cell = {"arm": arm, "cohort": cohort, "is_pass_cell": is_pass_cell,
            "diagnostics": port["diagnostics"], "metrics": mt,
            "base_alone_on_axis": base_ref, "sleeve_delta": delta,
            "joint_gate_point": {"cagr_ge_50": bool(mt["cagr"] >= 0.50),
                                 "mdd_le_20": bool(mt["max_drawdown"] <= 0.20),
                                 "point_pass": bool(mt["cagr"] >= 0.50 and mt["max_drawdown"] <= 0.20)}}
    if is_pass_cell:
        cell["gate_b"] = gate_b_bootstrap(port["equity_df"]["ret"].to_numpy(float), P=P)
        cell["PASS"] = bool(cell["gate_b"].get("passed", False))
    return cell


# --------------------------------------------------------------------------- #
# full run (matrix × cost) + folds + report
# --------------------------------------------------------------------------- #
def _load_all(data_dir: str, symbols: list[str]) -> dict:
    frames = {}
    for s in symbols:
        try:
            frames[s] = load_daily(f"{data_dir}/{s}_1d.parquet")
        except Exception:                            # noqa: BLE001 — missing leg = data gap
            pass
    return frames


def build_report(data_dir: str = "data/daily_full") -> dict:
    all_syms = sorted(set(TSMOM_UNIVERSE + ["DBMF", "KMLM", "BTAL"]))
    frames = _load_all(data_dir, all_syms)
    missing = [s for s in all_syms if s not in frames]
    matrix = {}
    for cm, tag in ((1.0, "x1"), (2.0, "x2")):
        cells = {}
        for arm in ("no_btal", "with_btal"):
            for cohort in ("long", "short"):
                is_pass = (tag == "x2" and arm == "no_btal" and cohort == "long")
                key = f"{arm}__{cohort}"
                cells[key] = run_cell(frames, arm=arm, cohort=cohort,
                                      cost_mult=cm, is_pass_cell=is_pass)
        matrix[tag] = cells
    folds = regime_folds(frames, cost_mult=2.0)
    pass_cell = matrix["x2"]["no_btal__long"]
    return {
        "issue": "EVO-238", "layer": "portfolio (analysis-only, zero engine change)",
        "frozen_spec": "吏部 2026-07-18; main_pass_cell = no-BTAL × drop-KMLM long "
                       "= {8-leg TSMOM + DBMF}; gate B stationary-block bootstrap "
                       "block~21 N=5000; CAGR 5% LB >=50% AND MDD 95% UB <=20%",
        "data_dir": data_dir, "missing_legs": missing,
        "matrix": matrix, "regime_folds": folds,
        "main_cell_PASS": bool(pass_cell.get("PASS", False)),
        "verdict": ("PASS (向 50/20 达标)" if pass_cell.get("PASS", False)
                    else "NEGATIVE (未达 50/20 联合门)"),
    }


if __name__ == "__main__":
    import json
    from pathlib import Path
    rep = build_report("data/daily_full")
    outdir = Path("reports/crisis_portfolio")
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "report.json").write_text(json.dumps(rep, indent=2, default=str))
    print(json.dumps(rep, indent=2, default=str))
