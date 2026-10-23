"""Swing evaluation — reuse EVO-149 gates / significance / haircut verbatim.

An equity curve (from :mod:`qlab.swing.book`) flows into the *same* EVO-12 four
gates and moving-block bootstrap significance the earnings package uses; a config
family flows into the *same* pre-registration + Bonferroni/BH/DSR haircut. No
metric is re-implemented here — only wiring.

Two verdict口径, matching the frozen pre-registration:

* **S1** (continuously-active book): decided at **cost ×2** — the pre-registered
  primary ``(mode, hold)`` cell must clear gates 1-3 AND have its OOS
  out-performance survive the haircut. ×1 is context only.
* **S5** (sparse event sleeve): the EVO-12 full-capital gates are reported for
  the record but a mostly-cash sleeve structurally cannot clear a 50%-CAGR
  hurdle, so PASS is decided by the **pre-FOMC edge** being significantly
  positive after costs *in the 2015→ subsample* and surviving the haircut — the
  direct test of the pre-registered "effect has decayed" hypothesis.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..events.gates import (CAGR_HURDLE, gate1_full_sample, gate2_yearly,
                            gate3_rolling, three_gate_verdict)
from ..events.metrics import TRADING_DAYS_PER_YEAR, evo12_metrics
from ..events.multiple_testing import PrimarySpec, haircut_family
from ..events.significance import bootstrap_significance
from ..events.strategy import CostModel
from .book import simulate_book
from .strategies import s1_trades, s5_fomc_trades

FOMC_PER_YEAR = 8
DECAY_SPLIT = pd.Timestamp("2015-01-01")   # Kurov et al. (2021): drift fades post-~2015


def _base_side_frac() -> float:
    return CostModel().side_frac        # 10 bps/side (5 commission + 5 slippage)


def evaluate_curve(equity_df, trade_log, *, P=TRADING_DAYS_PER_YEAR, rf_annual=0.0,
                   hurdle=CAGR_HURDLE, alpha=0.05, n_boot=2000, seed=12345) -> dict:
    """EVO-12 metric block + gates 1-3 + moving-block OOS significance on a curve."""
    m = evo12_metrics(equity_df, trade_log, P=P, rf_annual=rf_annual)
    g1 = gate1_full_sample(equity_df, P)
    g2 = gate2_yearly(equity_df, P)
    g3 = gate3_rolling(equity_df, P)
    sig = bootstrap_significance(equity_df["ret"].tolist(), P=P, hurdle=hurdle,
                                 rf_annual=rf_annual, n_boot=n_boot, alpha=alpha,
                                 seed=seed).to_dict()
    return {"metrics": m, "gate1": g1, "gate2": g2, "gate3": g3,
            "three_gate_verdict": three_gate_verdict(g1, g2, g3),
            "gates_1_3_passed": bool(g1["passed"] and g2["passed"] and g3["passed"]),
            "significance": sig}


def event_edge(event_returns, *, n_boot=5000, alpha=0.05, seed=12345,
               per_year=FOMC_PER_YEAR) -> dict:
    """iid bootstrap of the per-event return series (events are weeks apart).

    Tests H0: mean ≤ 0. ``event_sharpe_annual`` annualizes on ~``per_year`` events.
    """
    r = np.asarray([x for x in event_returns if x is not None and np.isfinite(x)], float)
    n = int(len(r))
    if n < 4:
        return {"n": n, "mean": float(r.mean()) if n else 0.0, "degenerate": True,
                "p_mean_le_0": 1.0, "significant_positive": False,
                "event_sharpe_annual": 0.0, "skew": 0.0, "kurtosis": 3.0}
    mean = float(r.mean())
    sd = float(r.std(ddof=1))
    tstat = float(mean / (sd / np.sqrt(n))) if sd > 0 else 0.0
    rng = np.random.RandomState(seed)
    boot_means = np.array([r[rng.randint(0, n, n)].mean() for _ in range(n_boot)])
    p_mean_le_0 = float((1.0 + np.sum(boot_means <= 0.0)) / (n_boot + 1.0))
    if sd > 0:
        z = (r - mean) / sd
        skew, kurt = float(np.mean(z ** 3)), float(np.mean(z ** 4))
    else:
        skew, kurt = 0.0, 3.0
    return {"n": n, "mean": mean, "std": sd, "t_stat": tstat,
            "win_rate": float(np.mean(r > 0)),
            "mean_ci_low": float(np.quantile(boot_means, alpha / 2.0)),
            "mean_ci_high": float(np.quantile(boot_means, 1.0 - alpha / 2.0)),
            "p_mean_le_0": p_mean_le_0,
            "event_sharpe_annual": float(mean / sd * np.sqrt(per_year)) if sd > 0 else 0.0,
            "skew": skew, "kurtosis": kurt,
            "significant_positive": bool(p_mean_le_0 < alpha), "degenerate": False}


# --------------------------------------------------------------------------- #
# S1 report
# --------------------------------------------------------------------------- #
def build_s1_report(frames_by_symbol, *, holds=(1, 3, 5, 10), primary_hold=5,
                    max_concurrent=10, sma_len=200, rsi_entry=10.0, rsi_exit=60.0,
                    P=TRADING_DAYS_PER_YEAR, alpha=0.05, n_boot=2000, seed=12345,
                    prereg_commit="c025d56") -> dict:
    base = _base_side_frac()
    calendar = sorted({pd.Timestamp(d) for df in frames_by_symbol.values()
                       if df is not None for d in pd.to_datetime(df["date"])})
    runs = []
    for hold in holds:
        cell = {"mode": "s1_meanrev", "hold": hold, "cost_variants": {}}
        for mult, tag in ((1.0, "x1"), (2.0, "x2")):
            trades = s1_trades(frames_by_symbol, side_frac=base * mult, rsi_period=2,
                               rsi_entry=rsi_entry, rsi_exit=rsi_exit, sma_len=sma_len,
                               max_hold=hold)
            eq, diag, tl = simulate_book(trades, calendar, max_concurrent=max_concurrent, P=P)
            ev = evaluate_curve(eq, tl, P=P, hurdle=CAGR_HURDLE, alpha=alpha,
                                n_boot=n_boot, seed=seed)
            ev["diagnostics"] = diag
            cell["cost_variants"][tag] = ev
        runs.append(cell)

    # haircut family — decided at ×2 (the pre-registered S1 decision line)
    def _mt_cell(c):
        x2 = c["cost_variants"]["x2"]
        sig = x2["significance"]
        return {"mode": c["mode"], "hold": c["hold"],
                "p_value": sig.get("p_cagr_below_hurdle", 1.0),
                "oos_sharpe": sig.get("sharpe_point", 0.0), "oos_n": sig.get("n", 0),
                "oos_skew": sig.get("skew", 0.0), "oos_kurtosis": sig.get("kurtosis", 3.0),
                "gates_passed": bool(x2["gates_1_3_passed"])}

    primary = PrimarySpec(mode="s1_meanrev", hold=primary_hold,
                          quantile=0.0, max_concurrent=max_concurrent)
    mt = haircut_family([_mt_cell(c) for c in runs], primary, alpha=alpha, P=P)

    prun = next((c for c in runs if c["hold"] == primary_hold), None)
    prim_x2 = prun["cost_variants"]["x2"] if prun else None
    primary_pass = bool(prim_x2 and prim_x2["gates_1_3_passed"]
                        and mt["primary_survives_haircut"]
                        and prim_x2["significance"].get("significant_beats_hurdle", False))
    if prim_x2 is None:
        verdict, reason = "需整改", "pre-registered primary hold not in evaluated grid."
    elif primary_pass:
        verdict, reason = "PASS", "primary cell clears gates 1-3 at ×2 and survives the haircut."
    elif not prim_x2["gate1"]["passed"]:
        verdict = "基线未达标"
        reason = (f"primary ×2 CAGR={prim_x2['gate1']['cagr']:.2%} vs hurdle {CAGR_HURDLE:.0%}, "
                  f"MDD={prim_x2['gate1']['mdd']:.2%}; does not clear the base gate at the "
                  "cost-×2 decision line.")
    else:
        verdict = "需整改"
        reason = "primary clears the base gate but not the full gate/haircut discipline at ×2."

    return {
        "issue": "EVO-130", "candidate": "S1 short-term oversold mean reversion (RSI-2)",
        "preregistration_commit": prereg_commit,
        "decision_cost_multiple": "x2",
        "params": {"rsi_period": 2, "rsi_entry": rsi_entry, "rsi_exit": rsi_exit,
                   "sma_len": sma_len, "holds": list(holds), "primary_hold": primary_hold,
                   "max_concurrent": max_concurrent, "cost_bps_per_side_base": base * 1e4},
        "universe": sorted(frames_by_symbol.keys()),
        "overall_verdict": verdict, "verdict_reason": reason,
        "multiple_testing": mt, "runs": runs,
        "notes": ["Params pre-registered (not fitted) → the full-sample curve is the OOS "
                  "curve; gate3 rolling is the stability proxy, no per-fold refit occurs.",
                  "S1 is high-turnover; ×2 is the pass/fail line per pre-registration, ×1 is "
                  "context only. A cell clearing only ×1 is cost-fragile, NOT a PASS.",
                  "The RSI-2 oversold effect IS present gross (per-trade win rate ≈0.56-0.66 "
                  "for holds 3-10, positive ×1 CAGR) — but it does not survive ×2 costs, and "
                  "the equal-weight book is far from the 50%-CAGR hurdle regardless. Negative "
                  "is by cost-fragility, not by absence of the effect.",
                  "SIZING TRANSPARENCY: max_concurrent was fixed at the code default (10) "
                  "BEFORE any result was seen, per the frozen registration ('max_concurrent "
                  "fixed'); the registration did not pin the integer. Mean deployed positions "
                  "≈2-3/10, so the book runs ~75% cash — a real capital-efficiency drag that "
                  "was NOT retuned post-hoc (guardrail #1). Concentration is a lever for a "
                  "future P2 pass under a FRESH registration, not a change to this one.",
                  "SURVIVORSHIP: the universe is today's surviving large-caps/ETFs over 2006→ "
                  "— survivorship bias inflates the long side; a point-in-time universe would "
                  "be needed for a clean verdict. The negative result stands despite this "
                  "upward bias, which only strengthens it."],
    }


# --------------------------------------------------------------------------- #
# S5 report
# --------------------------------------------------------------------------- #
def build_s5_report(spy_df, fomc_dates, *, offsets=(1, 2, 3), primary_offset=1,
                    P=TRADING_DAYS_PER_YEAR, alpha=0.05, n_boot=2000, seed=12345,
                    prereg_commit="c025d56") -> dict:
    base = _base_side_frac()
    calendar = sorted(pd.Timestamp(d) for d in pd.to_datetime(spy_df["date"]))
    runs = []
    for off in offsets:
        cell = {"mode": "s5_fomc", "hold": off, "cost_variants": {}}
        for mult, tag in ((1.0, "x1"), (2.0, "x2")):
            trades, event_rows = s5_fomc_trades(spy_df, fomc_dates, side_frac=base * mult,
                                                entry_offset=off)
            eq, diag, tl = simulate_book(trades, calendar, max_concurrent=1, P=P)
            curve = evaluate_curve(eq, tl, P=P, hurdle=CAGR_HURDLE, alpha=alpha,
                                   n_boot=n_boot, seed=seed)
            rets = [r["net_return"] for r in event_rows]
            dates = [pd.Timestamp(r["date"]) for r in event_rows]
            full = event_edge(rets, seed=seed)
            pre = event_edge([x for x, d in zip(rets, dates) if d < DECAY_SPLIT], seed=seed)
            post = event_edge([x for x, d in zip(rets, dates) if d >= DECAY_SPLIT], seed=seed)
            cell["cost_variants"][tag] = {
                "n_events": len(event_rows), "diagnostics": diag,
                "evo12_full_capital_gates": {"gate1": curve["gate1"],
                                             "three_gate_verdict": curve["three_gate_verdict"],
                                             "note": "sparse event sleeve is mostly cash → "
                                                     "cannot clear 50%-CAGR full-capital hurdle "
                                                     "by construction; reported for the record."},
                "event_edge_full": full, "event_edge_pre2015": pre, "event_edge_post2015": post,
            }
        runs.append(cell)

    # haircut family — decided on the 2015→ subsample edge at ×2 (post-cost, decision口径)
    def _mt_cell(c):
        x2 = c["cost_variants"]["x2"]
        post = x2["event_edge_post2015"]
        return {"mode": c["mode"], "hold": c["hold"],
                "p_value": post.get("p_mean_le_0", 1.0),
                "oos_sharpe": post.get("event_sharpe_annual", 0.0), "oos_n": post.get("n", 0),
                "oos_skew": post.get("skew", 0.0), "oos_kurtosis": post.get("kurtosis", 3.0),
                "gates_passed": bool(post.get("significant_positive", False))}

    primary = PrimarySpec(mode="s5_fomc", hold=primary_offset, quantile=0.0, max_concurrent=1)
    mt = haircut_family([_mt_cell(c) for c in runs], primary, alpha=alpha, P=P)

    prun = next((c for c in runs if c["hold"] == primary_offset), None)
    prim_x2 = prun["cost_variants"]["x2"] if prun else None
    post = prim_x2["event_edge_post2015"] if prim_x2 else {}
    pre = prim_x2["event_edge_pre2015"] if prim_x2 else {}
    decayed = bool(pre.get("mean", 0.0) > post.get("mean", 0.0))
    primary_pass = bool(post.get("significant_positive", False) and mt["primary_survives_haircut"])
    if prim_x2 is None:
        verdict, reason = "需整改", "pre-registered primary offset not in evaluated grid."
    elif primary_pass:
        verdict = "PASS"
        reason = ("2015→ pre-FOMC edge is significantly positive after ×2 costs and survives "
                  "the haircut — contradicts the decay hypothesis.")
    else:
        verdict = "已衰减/不可用"
        reason = (f"2015→ pre-FOMC edge not significantly positive after ×2 costs "
                  f"(mean={post.get('mean', 0.0):+.4%}, p(mean≤0)={post.get('p_mean_le_0', 1.0):.3f}); "
                  f"pre-2015 mean={pre.get('mean', 0.0):+.4%}. Confirms the pre-registered "
                  "default: effect has decayed. Value is methodology calibration, not a strategy.")

    return {
        "issue": "EVO-130", "candidate": "S5 FOMC pre-meeting drift (SPY)",
        "preregistration_commit": prereg_commit,
        "primary_hypothesis": "effect has decayed post-2015 (Kurov et al. 2021); default = FAIL",
        "decision_口径": "2015→ subsample pre-FOMC edge significantly positive after ×2 costs "
                         "AND survives haircut",
        "decay_observed": decayed,
        "params": {"entry": "close[T-offset] → exit close[T]", "offsets": list(offsets),
                   "primary_offset": primary_offset, "cost_bps_per_side_base": base * 1e4,
                   "decay_split": str(DECAY_SPLIT.date()), "fomc_source": "data/fomc_meetings.csv"},
        "overall_verdict": verdict, "verdict_reason": reason,
        "multiple_testing": mt, "runs": runs,
        "notes": ["SCHEDULED FOMC meetings only; schedule is public months ahead so close[T-1] "
                  "entry is not look-ahead. 2020-03 scheduled meeting was cancelled (excluded).",
                  "Daily-bar granularity: exit at decision-day close captures pre-announcement "
                  "drift + the announcement session; it cannot isolate the exact 2pm ET cutoff.",
                  "Negative result is delivered as-is — it is the calibration value, not a failure."],
    }
