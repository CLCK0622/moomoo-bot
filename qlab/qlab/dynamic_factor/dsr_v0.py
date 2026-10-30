"""EVO-883 v0.1 numerical adapter.

V family aggregation is not wired: v0.1 makes pool admission depend on DSR while
the V family depends on post-admission membership (EVO-883 review draft1). Until
v0.2 resolves that loop, dsr_eval stops after SR/skew/kurt/N and returns
DSR/V as null with ``prereg_pending_v0.2``. ``formula`` and ``daily_sr`` stay
available as pure functions for unit checks with an externally supplied V.
"""

from __future__ import annotations

import math
import re

from .contract import result, unavailable
from .conventions import arithmetic
from .fees import finite


def variance(values, ddof):
    if len(values) <= ddof or not all(finite(x) for x in values):
        raise ValueError("dsr.insufficient_or_nonfinite_observations")
    mean = math.fsum(values) / len(values)
    return math.fsum((x - mean) ** 2 for x in values) / (len(values) - ddof)


def formula(policy, *, SR, n, N, V, skew, kurt, n_complete):
    """Read both DSR expressions and coefficients from the pinned JSON ASTs."""
    p = policy.document
    ddof = int(re.fullmatch(r"ddof(\d+)", p["DSR"]["sample_sd"])[1])
    if (
        type(n) is not int
        or n <= ddof
        or type(N) is not int
        or N < 1
        or not all(finite(x) for x in (SR, V, skew, kurt))
        or V < 0
    ):
        raise ValueError("dsr.invalid_sample_or_variance")
    if N == 1:
        if not n_complete:
            raise ValueError("dsr.n_eq1_requires_complete_audit")
        if p["DSR"]["N_eq1"] != "SR0=0_only_if_complete_audited_N_really_1":
            raise ValueError("dsr.n_eq1_rule_unsupported")
        sr0 = 0.0
    else:
        sr0 = arithmetic(p["DSR"]["SR0"], {"V": V, "gamma": p["DSR"]["gamma"], "N": N})
    value = arithmetic(
        p["DSR"]["value"], {"SR": SR, "SR0": sr0, "n": n, "skew": skew, "kurt": kurt}
    )
    if not finite(value):
        raise ValueError("dsr.nonfinite_formula_result")
    return sr0, value


def daily_sr(observation, periods):
    sr = observation["sharpe_per_period"]
    d = observation.get("details", {})
    scale = d.get("sharpe_scale")
    conversions = d.get("scale_conversions", 0)
    if type(conversions) is not int:
        raise ValueError("dsr.scale_mismatch_or_repeated_conversion")
    if not finite(sr):
        raise ValueError("dsr.family_or_independent_sr_missing")
    if scale == "annual" and conversions == 0:
        return sr / math.sqrt(periods)
    if scale == "daily" and conversions in (0, 1):
        return sr
    raise ValueError("dsr.scale_mismatch_or_repeated_conversion")


V_PENDING = "prereg_pending_v0.2"


def evaluate(request, ledger, policy):
    snapshot = ledger.safe_snapshot()
    inputs = {"request": request, "ledger": snapshot, **policy.binding}
    metrics = {
        "dsr": None,
        "trials_variance": None,
        "family_variance": None,
        "independent_variance": None,
        "sharpe": None,
        "skew": None,
        "kurt": None,
        "sr0": None,
        "cumulative_n": snapshot["cumulative_n"],
        "cumulative_n_lower_bound": snapshot["cumulative_n_lower_bound"],
        "n_ledger_hash": snapshot["n_ledger_hash"],
        "gate_n": None,
        "n_complete": snapshot["n_complete"],
        "gate_n_is_lower_bound": not snapshot["n_complete"],
        "local_counted_n": snapshot["local_counted_n"],
        "diagnostic_passed": False,
        "passed": False,
    }
    reasons = list(snapshot["reasons"])
    unavailable_reason = None
    p = policy.document
    try:
        if not isinstance(request, dict):
            raise ValueError("dsr.request_invalid")
        if "v" in request or "trials_variance" in request:
            raise ValueError("dsr.scalar_v_forbidden")
        if "sharpe" in request or "sharpe_scale" in request:
            raise ValueError("dsr.scalar_sr_forbidden")
        if (
            snapshot["genesis"] is None
            or (snapshot["genesis"].get("authority_source") or {}).get("sha256")
            != p["genesis"]["sha256"]
        ):
            raise ValueError("dsr.seed_not_imported")
        reported = request.get("self_report_n")
        if type(reported) is not int or reported < 1:
            raise ValueError("dsr.self_report_n_missing_or_invalid")
        reported = ledger.observe_self_report_n(reported)
        snapshot = ledger.safe_snapshot()
        inputs["ledger"] = snapshot
        metrics["n_ledger_hash"] = snapshot["n_ledger_hash"]
        metrics["gate_n"] = max(snapshot["cumulative_n_lower_bound"], reported)
        if (
            request.get("return_basis") != p["N"]["DSR_SR_basis"]
            or request.get("return_scale") != "daily"
        ):
            raise ValueError("dsr.scale_or_basis_mismatch")
        returns = request["returns"]
        ddof = int(re.fullmatch(r"ddof(\d+)", p["DSR"]["sample_sd"])[1])
        var = variance(returns, ddof)
        if var <= 0:
            raise ValueError("dsr.zero_return_variance")
        mean = math.fsum(returns) / len(returns)
        central = {
            f"population_m{k}": math.fsum((x - mean) ** k for x in returns)
            / len(returns)
            for k in (2, 3, 4)
        }
        skew = arithmetic(p["DSR"]["skew"].replace("^", "**"), central)
        kurt_expr = (
            p["DSR"]["kurt"].removesuffix("_non_excess_normal3").replace("^", "**")
        )
        kurt = arithmetic(kurt_expr, central)
        sr = mean / math.sqrt(var)
        metrics.update(sharpe=sr, skew=skew, kurt=kurt)
        # V family aggregation / admission waits for EVO-883 v0.2; no default V.
        raise ValueError(V_PENDING)
    except (ValueError, TypeError, KeyError, ZeroDivisionError, OverflowError) as exc:
        unavailable_reason = (
            str(exc)
            if isinstance(exc, ValueError)
            else "dsr.input_or_denominator_invalid"
        )
        reasons.append(unavailable_reason)
    reasons.append("prereg_draft_not_frozen")
    availability = {
        k: (
            {"available": True, "reason": None}
            if metrics[k] is not None
            else unavailable(unavailable_reason)
        )
        for k in ("dsr", "trials_variance", "sharpe")
    }
    return policy.bind(
        result(
            "dsr_eval",
            inputs,
            metrics=metrics,
            reasons=reasons,
            availability=availability,
            assumptions=[
                "N is only a lower bound; numerical DSR may overstate confidence and is diagnostic only, never certification.",
                "V family aggregation and DSR>=threshold admission are pending EVO-883 v0.2; DSR/V stay null.",
                "Historical raw strategy Sharpe values are retained for provenance and never used as active-return V.",
            ],
        )
    )
