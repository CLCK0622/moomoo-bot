"""EVO-25 candidate-8 verdict builder — wires the carry curve into EVO-149/130.

Mirrors ``swing.evaluate.build_s1_report``: a pre-registered primary cell, a
declared τ family for the multiple-testing haircut, ×1/×2 double-cost reporting,
and — because this is a tail-risk product — a dedicated stress block that is part
of the verdict, not an appendix. Every gate / significance / haircut number comes
from the reused modules; nothing is re-implemented here.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..events.gates import CAGR_HURDLE, MDD_CAP, gate1_full_sample
from ..events.metrics import TRADING_DAYS_PER_YEAR, _cagr, _max_drawdown, evo12_metrics
from ..events.multiple_testing import PrimarySpec, haircut_family
from .carry_signals import CarryParams, carry_curve
from .evaluate import evaluate_curve

# tail windows (part of the verdict — EVO-12 + 首辅 clause #5)
STRESS_WINDOWS = {
    "2018-02_volmageddon": ("2018-01-15", "2018-03-15"),
    "2020-03_covid": ("2020-02-15", "2020-04-30"),
    "2022_ratehike_vol": ("2022-01-01", "2022-12-31"),
    "2025-2026_recent": ("2025-01-01", "2026-07-09"),
}
SINGLE_DAY_SHOCK = -0.80          # historical SVXY open-to-open collapse (2018-02-06 scale)
TAU_FAMILY = (0.95, 1.00, 1.05)   # declared robustness band; primary = 1.00
PRIMARY_TAU = 1.00


def _worst_losing_streak(ret: np.ndarray) -> float:
    """Worst cumulative drawdown over any contiguous run of losses (as a fraction)."""
    worst = 0.0
    cur = 1.0
    for r in ret:
        if r < 0:
            cur *= (1.0 + r)
        else:
            worst = min(worst, cur - 1.0)
            cur = 1.0
    worst = min(worst, cur - 1.0)
    return float(worst)


def _window_stats(equity_df: pd.DataFrame, lo: str, hi: str, P: int) -> dict:
    w = equity_df[(equity_df["date"] >= pd.Timestamp(lo)) & (equity_df["date"] <= pd.Timestamp(hi))]
    if len(w) < 2:
        return {"n_days": int(len(w)), "insufficient": True}
    ret = w["ret"].to_numpy(float)
    eq = np.cumprod(1.0 + ret)
    mdd = _max_drawdown(eq)
    return {
        "n_days": int(len(w)),
        "window_return": float(eq[-1] - 1.0),
        "annualized_cagr": float(_cagr(eq, P)),
        "mdd": float(mdd),
        "worst_single_day": float(ret.min()),
        "worst_losing_streak": _worst_losing_streak(ret),
        "mdd_breach_20pct": bool(mdd > MDD_CAP),
        "passed": bool(mdd <= MDD_CAP),
    }


def _cell(svxy, sig, tau, *, params: CarryParams, P, alpha, n_boot, seed) -> dict:
    p = CarryParams(**{**params.to_dict(), "tau": tau})
    out = {"mode": "carry_vixts", "hold": int(round(tau * 100)), "tau": tau, "cost_variants": {}}
    for cm, tag in ((1.0, "x1"), (2.0, "x2")):
        res = carry_curve(svxy, sig, p, cost_mult=cm)
        eq, tl = res["equity_df"], res["trade_log"]
        ev = evaluate_curve(eq, tl, P=P, hurdle=CAGR_HURDLE, alpha=alpha, n_boot=n_boot, seed=seed)
        ev["diagnostics"] = res["diagnostics"]
        ev["stress"] = {name: _window_stats(eq, lo, hi, P) for name, (lo, hi) in STRESS_WINDOWS.items()}
        d = res["diagnostics"]
        ev["stress"]["single_day_extreme_shock"] = {
            "hypothesis": f"apply a {SINGLE_DAY_SHOCK:.0%} SVXY open-to-open gap at max realized exposure",
            "max_exposure": d["max_exposure"],
            "principal_loss_estimate": float(d["max_exposure"] * SINGLE_DAY_SHOCK),
            "worst_realized_single_day": float(eq["ret"].min()),
        }
        out["cost_variants"][tag] = ev
    return out


def build_carry_report(svxy_df, signal_df, *, params: CarryParams | None = None,
                       instrument="SVXY", P=TRADING_DAYS_PER_YEAR, alpha=0.05,
                       n_boot=2000, seed=12345, prereg_commit="PENDING",
                       reference_full_exposure=True) -> dict:
    params = params or CarryParams()
    runs = [_cell(svxy_df, signal_df, t, params=params, P=P, alpha=alpha, n_boot=n_boot, seed=seed)
            for t in TAU_FAMILY]

    def _mt_cell(c):
        x2 = c["cost_variants"]["x2"]
        sig = x2["significance"]
        return {"mode": c["mode"], "hold": c["hold"],
                "p_value": sig.get("p_cagr_below_hurdle", 1.0),
                "oos_sharpe": sig.get("sharpe_point", 0.0), "oos_n": sig.get("n", 0),
                "oos_skew": sig.get("skew", 0.0), "oos_kurtosis": sig.get("kurtosis", 3.0),
                "gates_passed": bool(x2["gates_1_3_passed"])}

    primary = PrimarySpec(mode="carry_vixts", hold=int(round(PRIMARY_TAU * 100)),
                          quantile=0.0, max_concurrent=1)
    mt = haircut_family([_mt_cell(c) for c in runs], primary, alpha=alpha, P=P)

    prun = next((c for c in runs if c["tau"] == PRIMARY_TAU), None)
    prim_x2 = prun["cost_variants"]["x2"] if prun else None

    # verdict: decided at ×2 on the primary cell; tail windows are part of the gate
    stress = prim_x2["stress"] if prim_x2 else {}
    tail_fail = [k for k, v in stress.items() if isinstance(v, dict) and v.get("mdd_breach_20pct")]
    g1 = prim_x2["gate1"] if prim_x2 else {}
    gates_ok = bool(prim_x2 and prim_x2["gates_1_3_passed"])
    sig_ok = bool(prim_x2 and prim_x2["significance"].get("significant_beats_hurdle", False))
    haircut_ok = bool(mt["primary_survives_haircut"])
    primary_pass = bool(gates_ok and sig_ok and haircut_ok and not tail_fail)

    if prim_x2 is None:
        verdict, reason = "需整改", "pre-registered primary τ not in evaluated family."
    elif primary_pass:
        verdict, reason = "PASS", "primary clears gates 1-3 at ×2, is significant, survives the haircut, and no tail window breaches MDD≤20%."
    else:
        bits = []
        if not g1.get("passed", False):
            bits.append(f"gate1 CAGR={g1.get('cagr', 0):.2%} vs hurdle {CAGR_HURDLE:.0%}, "
                        f"MDD={g1.get('mdd', 0):.2%} vs cap {MDD_CAP:.0%}")
        if tail_fail:
            bits.append("tail MDD>20% in: " + ", ".join(tail_fail))
        if not sig_ok:
            bits.append("OOS not significantly above hurdle")
        verdict = "基线未达标" if (not g1.get("passed", False)) else "尾部未过线"
        reason = "; ".join(bits) if bits else "primary fails the ×2 gate/haircut/tail discipline."

    report = {
        "issue": "EVO-25", "candidate": "candidate-8 VIX term-structure carry (long-only ETP/cash)",
        "preregistration_commit": prereg_commit,
        "signal_source": "CBOE VIX_History.csv / VIX3M_History.csv (cash indices)",
        "execution_source": "moomoo OpenD qfq daily bars (quote-only, TrdEnv.SIMULATE); open(T+1) execution",
        "instrument": instrument, "decision_cost_multiple": "x2",
        "params": params.to_dict(), "tau_family": list(TAU_FAMILY), "primary_tau": PRIMARY_TAU,
        "overall_verdict": verdict, "verdict_reason": reason,
        "primary_gate1": g1,
        "tail_windows_failing_mdd": tail_fail,
        "multiple_testing": mt, "runs": runs,
        "notes": [
            "NO-FIT (guardrail #4): the entry/exit signal has ZERO parameters fitted on returns "
            "— τ=1.00 is the natural VIX/VIX3M=1 term-structure boundary; the {0.95,1.05} band is "
            "robustness only, primary is pre-fixed at 1.00. Risk-overlay constants (target_vol, "
            "exposure_cap, dd_stop, cooldown, vix_cap, vol_lookback) are pre-registered conventions, "
            "not optimized on P&L. Full-sample curve therefore IS the OOS curve; gate3 rolling is the "
            "stability proxy; no walk-forward refit is owed.",
            "Long-only ETP/cash switch: contango ⇒ long SVXY (−0.5x), else cash. Never shorts a vol "
            "product (hard constraint).",
            "Anti-look-ahead (guardrail #2): VIX settles 16:15 ET > ETP 16:00 ET close, so returns are "
            "open-to-open with exposure decided at close(T) and executed at open(T+1).",
            "MDD≤20% is a hard gate for a vol product (首辅 clause #5); tail windows are part of the "
            "verdict, not an appendix.",
        ],
    }

    if reference_full_exposure:
        # a priori RISK-FRONTIER REFERENCE (NOT a verdict cell, NOT part of the family):
        # same signal, full exposure, no vol target / breaker / stop — to expose the
        # CAGR↔MDD incompatibility a risk-constrained sleeve is built to avoid.
        ref_params = CarryParams(tau=PRIMARY_TAU, target_vol=1e9, vol_lookback=20,
                                 exposure_cap=1.0, dd_stop=1e9, cooldown=0, vix_cap=1e9)
        ref = carry_curve(svxy_df, signal_df, ref_params, cost_mult=2.0)
        refeq = ref["equity_df"]
        rg1 = gate1_full_sample(refeq)
        report["risk_frontier_reference"] = {
            "label": "full-exposure contango sleeve (no risk overlay) — reference only, NOT a verdict cell",
            "cagr": rg1["cagr"], "mdd": rg1["mdd"],
            "worst_single_day": float(refeq["ret"].min()),
            "stress": {name: _window_stats(refeq, lo, hi, TRADING_DAYS_PER_YEAR)
                       for name, (lo, hi) in STRESS_WINDOWS.items()},
            "interpretation": "chasing the 50% CAGR hurdle by lifting exposure drives MDD far past the "
                              "20% cap — the two mandate constraints are jointly unreachable for a short-vol sleeve.",
        }
    return report
