"""EVO-883 pure numerical helpers and the legacy evaluator compatibility route.

``formula`` and ``daily_sr`` are unit arithmetic with externally supplied inputs.
``evaluate`` delegates to the public arm-tagged, read-only runtime refusal gate;
it never writes self-reported N or supplies runtime SR/DSR/V.
"""

from __future__ import annotations

import math
import re

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
    """Compatibility route shares the read-only, explicitly tagged public gate."""
    from .statistics import dsr_eval

    return dsr_eval(request, ledger, conventions=policy)
