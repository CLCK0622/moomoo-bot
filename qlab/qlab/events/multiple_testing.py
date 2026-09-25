"""Pre-registration + multiple-testing haircut for the config sweep (EVO-149 item A).

The battery evaluates a grid of ``(mode, hold)`` configurations (and, if ever
swept, ``quantile`` / ``max_concurrent``). Declaring PASS because *any* cell of
that grid cleared the hurdle — the old ``any_full_pass`` rule — is textbook
data-snooping: with 8 cells the best-of-8 CAGR is upward-biased even under a true
null. This module removes that bias two ways, both reported:

1. **Pre-registration.** A single ``PrimarySpec`` is fixed *before* looking at
   results; only that cell decides PASS. Every other cell is robustness evidence,
   never the basis of a verdict. ``quantile`` and ``max_concurrent`` are part of
   the registered spec (they are untuned design levers that move CAGR), so they
   cannot be cherry-picked after the fact.

2. **Family-wise / FDR haircut.** Across the whole family of per-cell OOS
   p-values we apply Bonferroni (FWER) and Benjamini-Hochberg (FDR), and we
   compute the **Deflated Sharpe Ratio** (Bailey & López de Prado 2014), which
   discounts the winning Sharpe by the number of trials and the return
   distribution's skew/kurtosis. A cell "survives the haircut" only if its
   adjusted p-value stays below ``alpha``.

The verdict rule (in :mod:`run_events`) then reads: PASS ⟺ the pre-registered
primary cell passes its gates *and* its OOS significance survives the haircut.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict

import numpy as np

# Euler–Mascheroni constant (for the expected-maximum-Sharpe term in DSR).
_EULER_GAMMA = 0.5772156649015329


@dataclass(frozen=True)
class PrimarySpec:
    """The single pre-registered configuration whose OOS result decides PASS.

    Fixed ahead of the run; every other grid cell is robustness-only. ``quantile``
    and ``max_concurrent`` are registered here so they cannot be tuned post-hoc.
    """

    mode: str = "pead"
    hold: int = 10
    quantile: float = 0.2
    max_concurrent: int = 10

    def matches(self, run: dict) -> bool:
        return run.get("mode") == self.mode and run.get("hold") == self.hold

    def to_dict(self) -> dict:
        return asdict(self)


def _norm_ppf(p: float) -> float:
    """Inverse standard-normal CDF (Acklam's rational approximation, no SciPy)."""
    if p <= 0.0:
        return -math.inf
    if p >= 1.0:
        return math.inf
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1.0 - 0.02425
    if p < plow:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    if p > phigh:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
           (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bonferroni(pvalues: list[float]) -> list[float]:
    """Bonferroni-adjusted p-values (clipped to 1)."""
    m = len(pvalues)
    return [min(1.0, p * m) for p in pvalues]


def benjamini_hochberg(pvalues: list[float]) -> list[float]:
    """Benjamini-Hochberg FDR-adjusted p-values (step-up, monotone-enforced)."""
    m = len(pvalues)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: pvalues[i])
    adj = [0.0] * m
    prev = 1.0
    for rank in range(m - 1, -1, -1):     # from largest p to smallest
        i = order[rank]
        val = pvalues[i] * m / (rank + 1)
        prev = min(prev, val)
        adj[i] = min(1.0, prev)
    return adj


def deflated_sharpe_ratio(sharpe: float, *, n_obs: int, n_trials: int,
                          sharpe_std_trials: float, skew: float = 0.0,
                          kurtosis: float = 3.0, periods_per_year: int = 252) -> dict:
    """Deflated Sharpe Ratio (Bailey & López de Prado 2014).

    ``sharpe`` is the *annualized* winning Sharpe; it is de-annualized internally.
    ``sharpe_std_trials`` is the spread (std) of annualized Sharpes across the
    ``n_trials`` configurations — the raw material of selection bias. Returns the
    expected-maximum benchmark ``sr0`` and ``dsr`` = P(true SR > 0 | selection),
    plus a ``significant`` flag at the conventional 0.95 threshold.
    """
    if n_obs < 2 or n_trials < 1:
        return {"dsr": 0.0, "sr0_annual": 0.0, "n_trials": n_trials,
                "significant": False, "note": "insufficient_obs_or_trials"}
    sr = sharpe / math.sqrt(periods_per_year)          # per-observation SR
    sr_std = sharpe_std_trials / math.sqrt(periods_per_year)
    if sr_std <= 0:
        sr_std = 1e-9
    m = max(n_trials, 2)
    # expected maximum of m iid trial SRs under H0 (Bailey–López de Prado eq.)
    e_max = ((1.0 - _EULER_GAMMA) * _norm_ppf(1.0 - 1.0 / m)
             + _EULER_GAMMA * _norm_ppf(1.0 - 1.0 / (m * math.e)))
    sr0 = sr_std * e_max                                # per-observation benchmark
    denom = math.sqrt(max(1e-12, 1.0 - skew * sr + (kurtosis - 1.0) / 4.0 * sr * sr))
    z = (sr - sr0) * math.sqrt(n_obs - 1) / denom
    dsr = _norm_cdf(z)
    return {"dsr": float(dsr), "sr0_annual": float(sr0 * math.sqrt(periods_per_year)),
            "n_trials": int(n_trials), "expected_max_z": float(e_max),
            "significant": bool(dsr > 0.95)}


def haircut_family(cells: list[dict], primary: PrimarySpec, *,
                   alpha: float = 0.05, P: int = 252) -> dict:
    """Apply the full multiple-testing haircut across the config family.

    ``cells`` is a list of dicts, one per configuration, each with keys
    ``mode``, ``hold``, ``p_value`` (the OOS beats-hurdle p-value from
    :mod:`significance`), ``oos_sharpe``, ``oos_n``, ``gates_passed`` (point).
    Returns the pre-registration record, the Bonferroni/BH adjusted p-values, the
    Deflated Sharpe Ratio of the primary cell, and the primary cell's survival.
    """
    m = len(cells)
    pvals = [float(c.get("p_value", 1.0)) for c in cells]
    bonf = bonferroni(pvals)
    bh = benjamini_hochberg(pvals)

    per_cell = []
    primary_idx = None
    for i, c in enumerate(cells):
        is_primary = primary.matches(c)
        if is_primary:
            primary_idx = i
        per_cell.append({
            "mode": c.get("mode"), "hold": c.get("hold"),
            "is_primary": is_primary,
            "p_value_raw": pvals[i],
            "p_value_bonferroni": bonf[i],
            "p_value_bh": bh[i],
            "gates_passed_point": bool(c.get("gates_passed", False)),
            "survives_bonferroni": bool(bonf[i] < alpha),
            "survives_bh": bool(bh[i] < alpha),
        })

    sharpes = [float(c.get("oos_sharpe", 0.0)) for c in cells]
    sharpe_std = float(np.std(sharpes, ddof=1)) if len(sharpes) > 1 else 0.0

    dsr = None
    primary_survives = False
    primary_record = None
    if primary_idx is not None:
        pc = cells[primary_idx]
        dsr = deflated_sharpe_ratio(
            float(pc.get("oos_sharpe", 0.0)), n_obs=int(pc.get("oos_n", 0)),
            n_trials=m, sharpe_std_trials=sharpe_std,
            skew=float(pc.get("oos_skew", 0.0)),
            kurtosis=float(pc.get("oos_kurtosis", 3.0)), periods_per_year=P)
        primary_survives = bool(per_cell[primary_idx]["gates_passed_point"]
                                and per_cell[primary_idx]["survives_bonferroni"])
        primary_record = per_cell[primary_idx]

    return {
        "method": "preregistered_primary + bonferroni + benjamini_hochberg + deflated_sharpe",
        "alpha": alpha,
        "family_size": m,
        "primary_spec": primary.to_dict(),
        "primary_found": primary_idx is not None,
        "primary_cell": primary_record,
        "deflated_sharpe": dsr,
        "per_cell": per_cell,
        "verdict_basis": "primary_only",
        "primary_survives_haircut": primary_survives,
        "note": "PASS is decided ONLY by the pre-registered primary cell surviving "
                "the Bonferroni haircut; all other cells are robustness evidence. "
                "any_full_pass (best-of-grid) is deliberately NOT used.",
    }
