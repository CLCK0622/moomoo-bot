"""EVO-23 candidate-1+2 verdict builder — wires the momentum curve into EVO-149/130.

Mirrors ``swing.carry_evaluate.build_carry_report`` / ``swing.evaluate.build_s1_report``:
a pre-registered primary cell, a declared lookback family for the multiple-testing
haircut, ×1/×2 double-cost reporting, and a dedicated tail-stress block that is part
of the verdict (not an appendix). Every gate / significance / haircut number comes
from the reused EVO-149/EVO-130 modules; nothing is re-implemented here.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..events.gates import CAGR_HURDLE, MDD_CAP, gate1_full_sample
from ..events.metrics import TRADING_DAYS_PER_YEAR, _cagr, _max_drawdown
from ..events.multiple_testing import PrimarySpec, haircut_family
from .evaluate import evaluate_curve
from .momentum_signals import (MomentumParams, buy_and_hold_curve, momentum_curve)

# tail windows (part of the verdict — pre-registration §7)
STRESS_WINDOWS = {
    "2018-02_volmageddon": ("2018-01-15", "2018-03-15"),
    "2020-03_covid": ("2020-02-15", "2020-04-30"),
    "2022_ratehike_bear": ("2022-01-01", "2022-12-31"),
    "2025-2026_recent": ("2025-01-01", "2026-07-09"),
}

# frozen universes (pre-registration §2 / §3)
TSMOM_UNIVERSE = ["SPY", "QQQ", "IWM", "TLT", "IEF", "GLD", "DBC", "UUP"]
SECTOR_UNIVERSE = ["XLY", "XLI", "XLK", "XLF", "XLV", "XLP", "XLU", "XLE", "XLB", "XLRE", "XLC"]

# declared families (haircut, robustness only); primary pre-fixed
TSMOM_FAMILY = (6, 12)          # lookback months; primary = 12
TSMOM_PRIMARY_LB = 12
SECTOR_FAMILY = (3, 6, 12)      # lookback months at top-3; primary = 12
SECTOR_PRIMARY_LB = 12
SECTOR_TOP_N = 3


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
        "mdd_breach_20pct": bool(mdd > MDD_CAP),
        "passed": bool(mdd <= MDD_CAP),
    }


def _cell(frames, universe, lookback, top_n, *, P, alpha, n_boot, seed) -> dict:
    p = MomentumParams(lookback_months=lookback, top_n=top_n)
    out = {"mode": "tsmom" if top_n is None else f"rs_top{top_n}",
           "hold": lookback, "lookback_months": lookback, "cost_variants": {}}
    for cm, tag in ((1.0, "x1"), (2.0, "x2")):
        res = momentum_curve(frames, universe, p, cost_mult=cm)
        eq, tl = res["equity_df"], res["trade_log"]
        ev = evaluate_curve(eq, tl, P=P, hurdle=CAGR_HURDLE, alpha=alpha, n_boot=n_boot, seed=seed)
        ev["diagnostics"] = res["diagnostics"]
        ev["stress"] = {name: _window_stats(eq, lo, hi, P) for name, (lo, hi) in STRESS_WINDOWS.items()}
        out["cost_variants"][tag] = ev
    return out


def _mt_cell(c):
    x2 = c["cost_variants"]["x2"]
    sig = x2["significance"]
    return {"mode": c["mode"], "hold": c["hold"],
            "p_value": sig.get("p_cagr_below_hurdle", 1.0),
            "oos_sharpe": sig.get("sharpe_point", 0.0), "oos_n": sig.get("n", 0),
            "oos_skew": sig.get("skew", 0.0), "oos_kurtosis": sig.get("kurtosis", 3.0),
            "gates_passed": bool(x2["gates_1_3_passed"])}


def _benchmarks(frames, universe, *, P) -> dict:
    """EVO-12 §4 benchmarks (context only). Missing data ⇒ N/A (data gap)."""
    out = {}
    # SPY buy&hold
    if frames.get("SPY") is not None and len(frames["SPY"]):
        ref = buy_and_hold_curve(frames, ["SPY"], cost_mult=2.0)
        g = gate1_full_sample(ref["equity_df"], P)
        out["SPY_buy_and_hold"] = {"cagr": g["cagr"], "mdd": g["mdd"]}
    else:
        out["SPY_buy_and_hold"] = "N/A (data gap)"
    # equal-weight universe buy&hold (present symbols)
    present = [s for s in universe if frames.get(s) is not None and len(frames.get(s))]
    if present:
        ref = buy_and_hold_curve(frames, universe, cost_mult=2.0)
        g = gate1_full_sample(ref["equity_df"], P)
        out["equal_weight_buy_and_hold"] = {"cagr": g["cagr"], "mdd": g["mdd"],
                                            "present_symbols": present}
    else:
        out["equal_weight_buy_and_hold"] = "N/A (data gap)"
    # 60/40 needs bonds
    has_bond = any(frames.get(b) is not None and len(frames.get(b)) for b in ("IEF", "TLT"))
    out["60_40"] = "N/A (data gap: no bond ETF present)" if not has_bond else "computed"
    out["cash_shy"] = {"cagr": 0.0, "mdd": 0.0} if frames.get("SHY") is None else "present"
    return out


def build_momentum_report(frames_by_symbol, sleeve="tsmom", *,
                          P=TRADING_DAYS_PER_YEAR, alpha=0.05, n_boot=2000, seed=12345,
                          prereg_commit="PENDING") -> dict:
    """Full verdict for one sleeve ('tsmom' → candidate 1; 'sector_rs' → candidate 2)."""
    if sleeve == "tsmom":
        universe, family, primary_lb, top_n = TSMOM_UNIVERSE, TSMOM_FAMILY, TSMOM_PRIMARY_LB, None
        cand = "candidate-1 multi-asset ETF time-series (absolute) momentum (long-only/cash)"
        primary_hold = TSMOM_PRIMARY_LB
    elif sleeve == "sector_rs":
        universe, family, primary_lb, top_n = SECTOR_UNIVERSE, SECTOR_FAMILY, SECTOR_PRIMARY_LB, SECTOR_TOP_N
        cand = "candidate-2 sector ETF relative-strength rotation (top-3, long-only/cash)"
        primary_hold = SECTOR_PRIMARY_LB
    else:
        raise ValueError(f"unknown sleeve {sleeve!r}")

    present = [s for s in universe if frames_by_symbol.get(s) is not None
               and len(frames_by_symbol.get(s))]
    missing = [s for s in universe if s not in present]
    data_complete = not missing

    # if NOT a single universe symbol is present, we cannot even run the engine
    if not present:
        return {
            "issue": "EVO-23", "candidate": cand, "sleeve": sleeve,
            "preregistration_commit": prereg_commit,
            "overall_verdict": "数据不足-无法评估",
            "verdict_reason": f"0/{len(universe)} frozen universe symbols have real OpenD bars; "
                              "engine is reproducible but no verdict can be formed.",
            "data_complete": False, "universe_frozen": universe,
            "universe_present": present, "universe_missing": missing,
            "runs": [], "benchmarks": {},
        }

    runs = [_cell(frames_by_symbol, universe, lb, top_n, P=P, alpha=alpha, n_boot=n_boot, seed=seed)
            for lb in family]

    primary = PrimarySpec(mode=("tsmom" if top_n is None else f"rs_top{top_n}"),
                          hold=primary_hold, quantile=0.0, max_concurrent=len(universe))
    mt = haircut_family([_mt_cell(c) for c in runs], primary, alpha=alpha, P=P)

    prun = next((c for c in runs if c["hold"] == primary_lb), None)
    prim_x2 = prun["cost_variants"]["x2"] if prun else None

    stress = prim_x2["stress"] if prim_x2 else {}
    tail_fail = [k for k, v in stress.items() if isinstance(v, dict) and v.get("mdd_breach_20pct")]
    g1 = prim_x2["gate1"] if prim_x2 else {}
    gates_ok = bool(prim_x2 and prim_x2["gates_1_3_passed"])
    sig_ok = bool(prim_x2 and prim_x2["significance"].get("significant_beats_hurdle", False))
    haircut_ok = bool(mt["primary_survives_haircut"])
    primary_pass = bool(gates_ok and sig_ok and haircut_ok and not tail_fail)

    if prim_x2 is None:
        verdict, reason = "需整改", "pre-registered primary lookback not in evaluated family."
    elif not data_complete:
        # engine ran on a reduced (data-insufficient) universe ⇒ NEVER达标; report honestly
        verdict = "数据不足-仅工程可复跑"
        reason = (f"only {len(present)}/{len(universe)} frozen universe symbols have real OpenD "
                  f"bars (present={present}; missing={missing}). The reduced-universe run below is "
                  f"engineering evidence, NOT a verdict against the frozen universe. Primary ×2 on "
                  f"the reduced universe: CAGR={g1.get('cagr', 0):.2%}, MDD={g1.get('mdd', 0):.2%} "
                  f"(most slots are cash by data gap, so this understates the frozen design and "
                  f"cannot be reported as达标).")
    elif primary_pass:
        verdict, reason = "PASS", ("primary clears gates 1-3 at ×2, is significant, survives the "
                                   "haircut, and no tail window breaches MDD≤20%.")
    else:
        bits = []
        if not g1.get("passed", False):
            bits.append(f"gate1 CAGR={g1.get('cagr', 0):.2%} vs hurdle {CAGR_HURDLE:.0%}, "
                        f"MDD={g1.get('mdd', 0):.2%} vs cap {MDD_CAP:.0%}")
        if tail_fail:
            bits.append("tail MDD>20% in: " + ", ".join(tail_fail))
        if not sig_ok:
            bits.append("OOS not significantly above hurdle")
        verdict = "基线未达标" if (not g1.get("passed", False)) else ("尾部未过线" if tail_fail else "需整改")
        reason = "; ".join(bits) if bits else "primary fails the ×2 gate/haircut/tail discipline."

    report = {
        "issue": "EVO-23", "candidate": cand, "sleeve": sleeve,
        "preregistration_commit": prereg_commit,
        "signal_source": "moomoo OpenD qfq daily ETF bars (quote-only, TrdEnv.SIMULATE)",
        "execution_source": "same OpenD daily bars; open(T+1) execution, open-to-open returns",
        "decision_cost_multiple": "x2",
        "universe_frozen": universe, "universe_present": present, "universe_missing": missing,
        "data_complete": data_complete,
        "lookback_family_months": list(family), "primary_lookback_months": primary_lb,
        "top_n": top_n,
        "overall_verdict": verdict, "verdict_reason": reason,
        "primary_gate1": g1, "tail_windows_failing_mdd": tail_fail,
        "multiple_testing": mt, "runs": runs,
        "benchmarks": _benchmarks(frames_by_symbol, universe, P=P),
        "notes": [
            "NO-FIT (hard gate #2 clause #4): lookback / rebalance / holdings are literature "
            "conventions (Faber 2007; Moskowitz–Ooi–Pedersen 2012; Antonacci 2014; "
            "Jegadeesh–Titman 1993) frozen before results ⇒ full-sample curve IS the OOS curve, "
            "gate3 rolling is the stability proxy, no walk-forward refit is owed. If any parameter "
            "were sample-chosen the waiver is void and a real fold WF becomes mandatory.",
            "Long-only, no shorting, no leverage; sizing is a fixed equal-weight slot with NO vol "
            "target / breaker / stop — the absolute-momentum cash switch is the sole risk control "
            "(pre-registration §5).",
            "Anti-look-ahead (hard gate #2): weights decided at close(T), executed open(T+1), "
            "returns open-to-open — unit-tested.",
            "MDD≤20% is a hard gate on full-sample, every rolling window, AND every tail window; a "
            "breach is a direct negative, never averaged away.",
            "N_universe is the FROZEN universe size, so an un-fetched symbol is a permanently-cash "
            "slot (data gap), never a silent re-size off the frozen weights.",
        ],
    }

    # a-priori risk-frontier reference (pre-registration §9) — context, never a verdict cell
    try:
        ref = buy_and_hold_curve(frames_by_symbol, universe, cost_mult=2.0)
        rg1 = gate1_full_sample(ref["equity_df"], P)
        report["risk_frontier_reference"] = {
            "label": "equal-weight buy&hold of present universe (no momentum/cash switch) — reference only",
            "present_symbols": ref["present"],
            "cagr": rg1["cagr"], "mdd": rg1["mdd"],
            "stress": {name: _window_stats(ref["equity_df"], lo, hi, P)
                       for name, (lo, hi) in STRESS_WINDOWS.items()},
            "interpretation": "removing the trend/cash filter lifts exposure to 100% always-on; the "
                              "MDD it incurs is the frontier the momentum cash-switch is built to cap.",
        }
    except Exception as exc:  # noqa: BLE001
        report["risk_frontier_reference"] = {"error": str(exc)}

    return report
