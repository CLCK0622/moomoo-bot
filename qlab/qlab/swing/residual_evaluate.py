"""EVO-162 C1 verdict builder — wires the residual-reversal curve into EVO-149/130/23.

Mirrors ``swing.momentum_evaluate.build_momentum_report`` / ``swing.carry_evaluate``: a
pre-registered primary cell, a declared family for the multiple-testing haircut, ×1/×2
double-cost reporting, and a dedicated tail-stress block that is part of the verdict (not an
appendix). Every gate / significance / haircut number comes from the reused EVO-149/130/23
modules; nothing is re-implemented here. The frozen spec is
``RESIDUAL_REVERSAL_EVAL_PREREGISTRATION.md`` — no口径 is changed.

A run on a reduced (data-insufficient) universe — missing factor ETFs, missing breadth, or a
thin book (< ``min_names_per_leg`` per leg) — is labelled ``数据不足-仅工程可复跑`` and is
**NEVER达标** (mirrors the momentum universe-gap discipline). The short leg's PASS clause 5
(§13) is external: 锦衣卫's EVO-10 red-line review; until it is passed, PASS is withheld and
the long-only / defined-risk fallback is the deliverable path.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..events.gates import CAGR_HURDLE, MDD_CAP, gate1_full_sample
from ..events.metrics import TRADING_DAYS_PER_YEAR, _cagr, _max_drawdown
from ..events.multiple_testing import PrimarySpec, haircut_family
from .evaluate import evaluate_curve
from .momentum_signals import buy_and_hold_curve
from .residual_signals import (FACTOR_ETFS, ResidualDataGap, ResidualParams, residual_curve)

# tail windows — part of the verdict (pre-registration §10; 首辅 裁定 naïvely include 2007-08 + 2008)
STRESS_WINDOWS = {
    "2007-08_quantquake": ("2007-07-01", "2007-09-30"),
    "2008_gfc": ("2008-01-01", "2008-12-31"),
    "2018Q4_selloff": ("2018-10-01", "2018-12-31"),
    "2020-03_covid": ("2020-02-15", "2020-04-30"),
    "2022_ratehike_bear": ("2022-01-01", "2022-12-31"),
    "2025-2026_recent": ("2025-01-01", "2026-07-09"),
}

# declared family for the haircut (§12; robustness only, primary pre-fixed). Each cell is a
# distinct (mode, hold) so ``PrimarySpec.matches`` selects exactly one. ``needs_sectors`` cells
# (4-factor industry demean) run only if a GICS sector map is supplied, else recorded N/A.
PRIMARY = {"formation_weeks": 1, "estimation_weeks": 156, "cut": 0.10, "factor_set": "3f"}
FAMILY = [
    {**PRIMARY, "primary": True},                                   # F1 E156 decile 3f (PRIMARY)
    {"formation_weeks": 2, "estimation_weeks": 156, "cut": 0.10, "factor_set": "3f"},
    {"formation_weeks": 4, "estimation_weeks": 156, "cut": 0.10, "factor_set": "3f"},
    {"formation_weeks": 1, "estimation_weeks": 104, "cut": 0.10, "factor_set": "3f"},
    {"formation_weeks": 1, "estimation_weeks": 156, "cut": 0.20, "factor_set": "3f"},  # quintile
    {"formation_weeks": 1, "estimation_weeks": 156, "cut": 0.10, "factor_set": "4f",
     "needs_sectors": True},
]


def _cut_name(cut: float) -> str:
    return "decile" if abs(cut - 0.10) < 1e-9 else ("quintile" if abs(cut - 0.20) < 1e-9
                                                    else f"cut{cut:.2f}")


def _mode(spec: dict) -> str:
    return (f"resid_F{spec['formation_weeks']}_E{spec['estimation_weeks']}_"
            f"{_cut_name(spec['cut'])}_{spec['factor_set']}")


# --------------------------------------------------------------------------- #
# ADDENDUM B (short-leg risk口径 reconciliation, frozen 9deba65) — report disclosures
# --------------------------------------------------------------------------- #
ADDENDUM_B_SOURCE = "RESIDUAL_REVERSAL_PREREG_ADDENDUM_B_shortleg_risk.md (frozen 9deba65)"

# B1: the frozen §6 "single-sector net cap ≤10% gross" is MONITOR-ONLY — computed & disclosed
# per run, flagged if >10%, never enforced as a sizing cap (that would partially sector-neutralize
# the 3f primary and blur it against its own §12 4f robustness cell).
_B1_MONITOR_NOTE = (
    "MONITOR-ONLY diagnostic (addendum B1): the single-sector net cap is disclosed, NOT enforced. "
    "The 3-factor primary is intentionally market/size/value-neutral but NOT sector-neutral "
    "(sector-neutralization is the separate §12 4-factor family cell); a hard cap here would "
    "contaminate the frozen equal-weight-decile construction. Sector-tilt risk is already bounded "
    "by single-name ≤2.5% gross (≥20 names/leg) + dollar/beta-neutrality + 2.0× gross hard cap + "
    "10% ann. vol target + 8%/5-day breaker — the vol target caps total book risk regardless of "
    "the tilt's source. A static current-GICS map, when supplied, is a REPORTING-ONLY input, never "
    "in the signal / sizing / verdict.")

# B2: the frozen §6 "+25% per-name short stop" is honestly relabeled — the SIMULATE weekly
# backtest holds to the next rebalance with NO intraday stop (conservative: eats the full adverse
# move, so it does NOT underestimate risk); the stop is a live-execution overlay, not exercised.
B2_SHORT_STOP_DISCLOSURE = (
    "main口径 backtest = weekly-hold to the next rebalance, NO intraday +25% stop exercised; the "
    "+25% single-name short stop is a LIVE-EXECUTION OVERLAY not active in this SIMULATE run and "
    "cannot be claimed as an active tail limit (addendum B2). No-stop is conservative — the book "
    "eats the full adverse move, so risk is not underestimated.")

# B3: gap risk is a live-transition requirement, out of scope this SIMULATE round (recorded only).
B3_GAP_RISK_NOTE = (
    "live-transition requirement (addendum B3, no action this SIMULATE round): if the strategy "
    "leaves SIMULATE/quote-only, the +25% stop must be modeled as fills-at-the-next-open-after-"
    "trigger (NOT a guaranteed +25% exit — an overnight/M&A gap can pierce it) and that transition "
    "triggers a FRESH 锦衣卫 red-line review. Gap loss is bounded now: single-name ≤2.5% gross ⇒ "
    "even a +100% overnight gap ≈ 2.5% NAV single-name loss.")

# 锦衣卫 EVO-10 conditional-PASS context (addendum B intro) — factual disclosure, changes no logic.
SHORT_LEG_REVIEW_CONTEXT = (
    "锦衣卫 EVO-10 review on b0b80a6 = conditional PASS (9deba65): the short leg is a dollar+beta-"
    "neutral, diversified, borrowable-cash hedged structure with a bounded, quantifiable book-level "
    "max loss ⇒ NOT an EVO-10 infinite/undefined-risk exclusion; it MAY run in the SIMULATE "
    "backtest (no forced long-only/defined-risk fallback). Scope guard: this covers SIMULATE/"
    "quote-only ONLY — the instant the short leg leaves SIMULATE or adds any live credential / "
    "order path, the review is void and a fresh 锦衣卫 review is required.")


def _sector_net_exposure(weights_df: pd.DataFrame, sectors: dict | None) -> dict:
    """B1 diagnostic: realized max single-sector net exposure as a fraction of gross (monitor-only).

    ``weights_df`` carries signed notional per symbol per day (from ``residual_curve``). For each
    day and GICS sector, net = Σ signed weights in that sector; the diagnostic is
    ``max_over(days, sectors) |net| / gross``. Flagged if > 10% gross. Never enforced, never
    silently dropped: with no sector map it reports ``measured=False`` and relies on the bounding
    stack + the §12 4f cell (锦衣卫 prerequisite #1).
    """
    if not sectors:
        return {"measured": False, "computed": True, "monitor_only": True, "cap_enforced": False,
                "threshold_frac_gross": 0.10,
                "note": "single-sector net exposure UNMEASURED under OpenD-only (no static GICS map "
                        "supplied). " + _B1_MONITOR_NOTE + " See the §12 4f cell for the sector-"
                        "neutral robustness check."}
    syms = [c for c in weights_df.columns if c != "date"]
    W = weights_df[syms].to_numpy(float)
    sec_of = [str(sectors.get(s) or sectors.get(s.upper()) or "UNKNOWN") for s in syms]
    mapped = int(sum(1 for s in sec_of if s != "UNKNOWN"))
    gross = np.abs(W).sum(axis=1)
    realized_max, worst_sector, worst_idx = 0.0, None, -1
    for sec in sorted({s for s in sec_of if s != "UNKNOWN"}):
        cols = [j for j, s in enumerate(sec_of) if s == sec]
        net = W[:, cols].sum(axis=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            frac = np.where(gross > 0, np.abs(net) / gross, 0.0)
        j = int(np.argmax(frac))
        if frac[j] > realized_max:
            realized_max, worst_sector, worst_idx = float(frac[j]), sec, j
    dates = pd.DatetimeIndex(weights_df["date"])
    return {
        "measured": True, "computed": True, "monitor_only": True, "cap_enforced": False,
        "threshold_frac_gross": 0.10,
        "realized_max_single_sector_net_frac_gross": realized_max,
        "breaches_10pct_flag": bool(realized_max > 0.10),
        "worst_sector": worst_sector,
        "worst_date": str(dates[worst_idx].date()) if worst_idx >= 0 else None,
        "n_sectors_mapped": len({s for s in sec_of if s != "UNKNOWN"}),
        "symbols_mapped": mapped, "symbols_total": len(syms),
        "sector_map_coverage": round(mapped / len(syms), 3) if syms else 0.0,
        "note": _B1_MONITOR_NOTE,
    }


def _addendum_b_block(b1_sector_diag: dict | None) -> dict:
    """Assemble the addendum-B disclosure block carried by EVERY report (all branches)."""
    return {
        "source": ADDENDUM_B_SOURCE,
        "B1_single_sector_net_exposure": b1_sector_diag if b1_sector_diag is not None else {
            "measured": False, "computed": False,
            "note": "no primary run on the present data (data-insufficient); single-sector net "
                    "exposure not computed. " + _B1_MONITOR_NOTE},
        "B2_short_stop": B2_SHORT_STOP_DISCLOSURE,
        "B3_gap_risk": B3_GAP_RISK_NOTE,
        "short_leg_review": SHORT_LEG_REVIEW_CONTEXT,
    }


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


def _cell(stock_frames, factor_frames, universe, spec, *, P, alpha, n_boot, seed,
          sectors=None) -> dict:
    p = ResidualParams(formation_weeks=spec["formation_weeks"],
                       estimation_weeks=spec["estimation_weeks"],
                       cut=spec["cut"], factor_set=spec["factor_set"])
    out = {"mode": _mode(spec), "hold": spec["formation_weeks"],
           "spec": {k: spec[k] for k in ("formation_weeks", "estimation_weeks", "cut", "factor_set")},
           "cost_variants": {}}
    if spec.get("needs_sectors") and sectors is None:
        out["unavailable"] = ("4-factor industry-demean cell needs a GICS sector map "
                              "(external, out of scope this round) — recorded N/A, not run.")
        return out
    weights_df = None
    for cm, tag in ((1.0, "x1"), (2.0, "x2")):
        try:
            res = residual_curve(stock_frames, factor_frames, universe, p,
                                 cost_mult=cm, sectors=sectors)
        except ResidualDataGap as exc:
            out["unavailable"] = f"数据不足 (factor gap): {exc}"
            return out
        except ValueError as exc:
            out["unavailable"] = f"数据不足 (engine): {exc}"
            return out
        if weights_df is None:
            weights_df = res["weights_df"]          # cost-independent ⇒ compute B1 once per cell
        eq, tl = res["equity_df"], res["trade_log"]
        ev = evaluate_curve(eq, tl, P=P, hurdle=CAGR_HURDLE, alpha=alpha, n_boot=n_boot, seed=seed)
        ev["diagnostics"] = res["diagnostics"]
        ev["stress"] = {name: _window_stats(eq, lo, hi, P) for name, (lo, hi) in STRESS_WINDOWS.items()}
        out["cost_variants"][tag] = ev
    # B1 (addendum B): realized max single-sector net exposure per run — monitor-only diagnostic
    out["sector_net_exposure"] = _sector_net_exposure(weights_df, sectors)
    return out


def _mt_cell(c):
    x2 = c["cost_variants"]["x2"]
    sig = x2["significance"]
    return {"mode": c["mode"], "hold": c["hold"],
            "p_value": sig.get("p_cagr_below_hurdle", 1.0),
            "oos_sharpe": sig.get("sharpe_point", 0.0), "oos_n": sig.get("n", 0),
            "oos_skew": sig.get("skew", 0.0), "oos_kurtosis": sig.get("kurtosis", 3.0),
            "gates_passed": bool(x2["gates_1_3_passed"])}


def _benchmarks(stock_frames, factor_frames, universe, *, P) -> dict:
    """EVO-12 §4 benchmarks (context only). Missing data ⇒ N/A (data gap)."""
    out = {}
    if factor_frames.get("SPY") is not None and len(factor_frames["SPY"]):
        ref = buy_and_hold_curve({"SPY": factor_frames["SPY"]}, ["SPY"], cost_mult=2.0)
        g = gate1_full_sample(ref["equity_df"], P)
        out["SPY_buy_and_hold"] = {"cagr": g["cagr"], "mdd": g["mdd"]}
    else:
        out["SPY_buy_and_hold"] = "N/A (data gap)"
    present = [s for s in universe if stock_frames.get(s) is not None and len(stock_frames.get(s))]
    if present:
        ref = buy_and_hold_curve(stock_frames, universe, cost_mult=2.0)
        g = gate1_full_sample(ref["equity_df"], P)
        out["equal_weight_universe_buy_and_hold"] = {"cagr": g["cagr"], "mdd": g["mdd"],
                                                     "present_symbols": present}
    else:
        out["equal_weight_universe_buy_and_hold"] = "N/A (data gap)"
    out["cash"] = {"cagr": 0.0, "mdd": 0.0}
    return out


def build_residual_report(stock_frames, factor_frames, universe, *,
                          universe_resolved: bool = False, sectors=None,
                          short_leg_reviewed: bool | None = None,
                          P=TRADING_DAYS_PER_YEAR, alpha=0.05, n_boot=2000, seed=12345,
                          prereg_commit="PENDING") -> dict:
    """Full C1 verdict following the frozen pre-registration (primary = F1/E156/decile/3f)."""
    cand = "C1 cross-sectional residual reversal (large-cap, weekly, market-neutral stat-arb)"
    present = [s for s in universe if stock_frames.get(s) is not None and len(stock_frames.get(s))]
    missing = [s for s in universe if s not in present]
    factor_missing = [s for s in FACTOR_ETFS if factor_frames.get(s) is None
                      or not len(factor_frames.get(s))]

    base_report = {
        "issue": "EVO-162", "candidate": cand,
        "preregistration_commit": prereg_commit,
        "signal_source": "moomoo OpenD qfq daily bars (quote-only, TrdEnv.SIMULATE)",
        "execution_source": "same OpenD daily bars; open(T+1) execution, open-to-open returns",
        "decision_cost_multiple": "x2",
        "universe_resolved": universe_resolved,
        "universe_frozen_size": len(universe),
        "universe_present": present, "universe_missing_count": len(missing),
        "factor_etfs_present": [s for s in FACTOR_ETFS if s not in factor_missing],
        "factor_etfs_missing": factor_missing,
        "tail_windows": list(STRESS_WINDOWS.keys()),
        "family": [_mode(s) for s in FAMILY],
        "primary_cell": _mode(PRIMARY),
        # addendum B disclosures ride on EVERY branch (incl. data-insufficient); B1 is filled with
        # the primary cell's realized sector exposure below once a primary run exists.
        "addendum_b": _addendum_b_block(None),
    }

    # Hard factor gap: the 3-factor primary口径 cannot even be built ⇒ engine reproducible,
    # but no verdict can be formed against the frozen universe.
    if factor_missing or len(present) < 2:
        base_report.update({
            "overall_verdict": "数据不足-无法评估",
            "verdict_reason": (
                f"factor ETFs missing={factor_missing}; only {len(present)}/{len(universe)} "
                f"frozen-universe stocks have real OpenD bars. The 3-factor residual model needs "
                f"all of {list(FACTOR_ETFS)} plus cross-sectional breadth (N≫K); it cannot be "
                f"built on the present data. Engine is reproducible; NO达标 claim is possible."),
            "data_complete": False, "runs": [],
            "benchmarks": _benchmarks(stock_frames, factor_frames, universe, P=P),
        })
        return base_report

    runs = [_cell(stock_frames, factor_frames, universe, s, P=P, alpha=alpha,
                  n_boot=n_boot, seed=seed, sectors=sectors) for s in FAMILY]
    runnable = [c for c in runs if "cost_variants" in c and c["cost_variants"]]

    primary = PrimarySpec(mode=_mode(PRIMARY), hold=PRIMARY["formation_weeks"],
                          quantile=PRIMARY["cut"], max_concurrent=len(universe))
    mt = (haircut_family([_mt_cell(c) for c in runnable], primary, alpha=alpha, P=P)
          if runnable else {"primary_survives_haircut": False, "primary_found": False,
                            "note": "no runnable family cell"})

    prun = next((c for c in runs if c["mode"] == _mode(PRIMARY)), None)
    prim_x2 = prun["cost_variants"].get("x2") if (prun and "cost_variants" in prun) else None

    if prim_x2 is None:
        base_report.update({
            "overall_verdict": "数据不足-无法评估",
            "verdict_reason": ("primary cell could not run on the present data (" +
                               (prun.get("unavailable", "no result") if prun else "cell absent") + ")."),
            "data_complete": False, "runs": runs, "multiple_testing": mt,
            "benchmarks": _benchmarks(stock_frames, factor_frames, universe, P=P),
        })
        return base_report

    diag = prim_x2["diagnostics"]
    thin = bool(diag.get("any_thin_book"))
    data_complete = bool(diag.get("data_complete") and universe_resolved and not thin)
    stress = prim_x2["stress"]
    tail_fail = [k for k, v in stress.items() if isinstance(v, dict) and v.get("mdd_breach_20pct")]
    g1 = prim_x2["gate1"]
    gates_ok = bool(prim_x2["gates_1_3_passed"])
    sig_ok = bool(prim_x2["significance"].get("significant_beats_hurdle", False))
    haircut_ok = bool(mt.get("primary_survives_haircut"))
    engine_pass = bool(gates_ok and sig_ok and haircut_ok and not tail_fail)

    # short-leg EVO-10 clause 5 (§13): PASS is withheld until 锦衣卫 approves; None = not reviewed
    short_leg_ok = (short_leg_reviewed is True)

    if not data_complete:
        verdict = "数据不足-仅工程可复跑"
        why = []
        if not universe_resolved:
            why.append("RESIDUAL_UNIVERSE_RESOLVED.txt not yet committed (universe unresolved)")
        if missing:
            why.append(f"{len(missing)}/{len(universe)} frozen stocks missing real bars")
        if thin:
            why.append(f"thin book: some weeks have < {diag.get('min_names_per_leg_required')} "
                       f"names/leg (min seen {diag.get('min_names_per_leg')})")
        reason = ("; ".join(why) + ". The reduced-universe run below is engineering evidence, NOT a "
                  f"verdict against the frozen universe. Primary ×2 on the reduced data: "
                  f"CAGR={g1.get('cagr', 0):.2%}, MDD={g1.get('mdd', 0):.2%}, "
                  f"mean {diag.get('mean_names_per_leg', 0):.1f} names/leg — cannot be reported as达标.")
    elif engine_pass and short_leg_ok:
        verdict = "PASS"
        reason = ("primary clears gates 1-3 at ×2, is significant, survives the Bonferroni haircut, "
                  "no tail window breaches MDD≤20%, and the short leg passed 锦衣卫 EVO-10 review.")
    elif engine_pass and not short_leg_ok:
        verdict = "PASS(待锦衣卫复核)"
        reason = ("engine口径 all clear at ×2 (gates 1-3, significant, haircut, tails) — but PASS "
                  "clause 5 is external: short-leg EVO-10 red-lines await 锦衣卫 review (不过不跑). "
                  "Until approved, the deliverable path is long-only / defined-risk fallback.")
    else:
        bits = []
        if not g1.get("passed", False):
            bits.append(f"gate1 CAGR={g1.get('cagr', 0):.2%} vs hurdle {CAGR_HURDLE:.0%}, "
                        f"MDD={g1.get('mdd', 0):.2%} vs cap {MDD_CAP:.0%}")
        if tail_fail:
            bits.append("tail MDD>20% in: " + ", ".join(tail_fail))
        if not sig_ok:
            bits.append("OOS not significantly above hurdle")
        if not haircut_ok:
            bits.append("primary does not survive the Bonferroni haircut")
        # cost fragility: clears ×1 but not ×2
        prim_x1 = prun["cost_variants"].get("x1")
        cost_fragile = bool(prim_x1 and prim_x1["gates_1_3_passed"] and not gates_ok)
        if not g1.get("passed", False):
            verdict = "基线未达标"
        elif tail_fail:
            verdict = "尾部未过线"
        elif cost_fragile:
            verdict = "成本脆弱"
        else:
            verdict = "需整改"
        reason = "; ".join(bits) if bits else "primary fails the ×2 gate/haircut/tail discipline."

    report = dict(base_report)
    report.update({
        "overall_verdict": verdict, "verdict_reason": reason,
        "data_complete": data_complete,
        "short_leg_reviewed": short_leg_reviewed,
        "primary_gate1": g1, "primary_diagnostics": diag,
        "tail_windows_failing_mdd": tail_fail,
        "primary_stress": stress,
        "multiple_testing": mt, "runs": runs,
        "benchmarks": _benchmarks(stock_frames, factor_frames, universe, P=P),
        # B1 (addendum B): surface the PRIMARY cell's realized single-sector net exposure
        "addendum_b": _addendum_b_block(prun.get("sector_net_exposure")),
        "notes": [
            "NO-FIT (hard gate #2 clause #4): F / E / factor set / decile count / rebalance / vol "
            "target / breaker / caps are literature conventions (Blitz–Huij–Lansdorp–Verbeek 2011; "
            "de Groot–Huij–Zhou; Blitz–Huij–Martens 2011) frozen before results. Additionally the "
            "betas are estimated ONLY on trailing data and applied to the next disjoint week, so "
            "every signal is genuinely OOS by construction — the full-sample curve IS the OOS curve, "
            "gate3 rolling is the stability proxy. Any sample-chosen parameter voids the waiver and a "
            "real fold walk-forward becomes mandatory (§11).",
            "Dollar- and beta-neutral long-short; the 2.0× gross cap is a HARD invariant (never "
            "exceeded on any date); vol-target + breaker are the pre-registered 压力段去杠杆规则 (§5).",
            "Anti-look-ahead (§7): weekly weights decided at close(T), executed open(T+1), returns "
            "open-to-open — unit-tested (future-bar shock cannot move earlier realized returns).",
            "MDD≤20% is a hard gate on full-sample, every rolling window, AND every tail window "
            "(incl. 2007-08 quant-quake + 2008 GFC); a breach is a direct negative, never averaged.",
            "N is the FROZEN universe size — an un-fetched / excluded symbol is a permanently-absent "
            "cross-section slot (data gap), never a silent re-size; a < min-names/leg week is 数据不足.",
            "Short-leg PASS clause 5 (§13) is 锦衣卫's EVO-10 review; conditional PASS on b0b80a6 "
            "(addendum B / 9deba65) ⇒ the short leg MAY run in SIMULATE (no forced fallback). The "
            "long-only / defined-risk path stays coded as a fallback for the live-transition case.",
            "ADDENDUM B (9deba65): single-sector net cap is MONITOR-ONLY — realized max is computed "
            "& disclosed per run and flagged if >10% gross, NEVER enforced as a sizing cap (B1, see "
            "addendum_b); the +25% single-name short stop is a LIVE-EXECUTION OVERLAY not exercised "
            "in this weekly-hold SIMULATE run and cannot be claimed as an active tail limit (B2); "
            "gap risk is a live-transition requirement with no action this round (B3).",
            "SURVIVORSHIP: 'large & liquid as of 2026' over 2006→ is survivorship-biased; a weekly "
            "dollar-neutral residual long-short is far less sensitive than a long-only level bet, but "
            "the bias is disclosed and cannot turn a fail into a pass (§2).",
        ],
    })

    # a-priori risk-frontier reference (§14) — same signal at 1.0× gross, vol-target/breaker OFF
    try:
        p_ref = ResidualParams(formation_weeks=PRIMARY["formation_weeks"],
                              estimation_weeks=PRIMARY["estimation_weeks"],
                              cut=PRIMARY["cut"], factor_set=PRIMARY["factor_set"], lever=False)
        ref = residual_curve(stock_frames, factor_frames, universe, p_ref, cost_mult=2.0,
                             sectors=sectors)
        rg1 = gate1_full_sample(ref["equity_df"], P)
        report["risk_frontier_reference"] = {
            "label": "same long-short signal at 1.0× gross (un-levered), vol-target/breaker DISABLED "
                     "— reference only, can never turn a fail into a pass",
            "cagr": rg1["cagr"], "mdd": rg1["mdd"],
            "stress": {name: _window_stats(ref["equity_df"], lo, hi, P)
                       for name, (lo, hi) in STRESS_WINDOWS.items()},
            "interpretation": "isolates how much of both the return and the tail come from the 2.0× "
                              "leverage overlay vs the raw residual edge.",
        }
    except Exception as exc:  # noqa: BLE001
        report["risk_frontier_reference"] = {"error": str(exc)}

    return report
