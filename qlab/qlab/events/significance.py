"""Bootstrap / permutation significance for an OOS equity curve (EVO-149 item B).

The four gates test whether a *point estimate* clears a hurdle (CAGR ≥ 50%,
MDD ≤ 20%). On a sparse sample (≈40 events/config, 8 folds) a point estimate can
clear a hurdle purely by luck, so a bare "passed" is not evidence. This module
attaches a **confidence interval and a p-value** to the OOS CAGR / Sharpe so a
gate can require a *significant* pass rather than a lucky one.

Design (deliberately non-parametric, deterministic):

* **Moving-block (circular) bootstrap** of the per-bar OOS return series. Daily
  event-drift returns are autocorrelated (multi-day holds overlap), so an iid
  bootstrap would understate the variance; resampling contiguous blocks of length
  ``L ≈ n**(1/3)`` preserves the short-range dependence.
* **CAGR / Sharpe CI** — percentile interval over the resampled statistics.
* **Beats-hurdle p-value** — fraction of resamples whose CAGR falls below the
  hurdle. Small ⇒ the curve is *confidently* above the hurdle, not just nominally.
* **Sharpe>0 p-value** — a proper bootstrap null: recenter returns to zero mean,
  resample, and measure how often the null Sharpe exceeds the observed one.

Everything is seeded, so the numbers are reproducible and unit-testable to the
value (EVO-24/149 test convention).
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np

from .metrics import _cagr, _max_drawdown, _sharpe, TRADING_DAYS_PER_YEAR

DEFAULT_N_BOOT = 2000
DEFAULT_ALPHA = 0.05


def _block_len(n: int) -> int:
    """Politis-style rule-of-thumb block length ``≈ n**(1/3)`` (≥1, ≤n)."""
    if n <= 2:
        return 1
    return int(min(n, max(1, round(n ** (1.0 / 3.0)))))


def _moving_block_indices(n: int, block_len: int, rng: np.random.RandomState) -> np.ndarray:
    """Circular moving-block resample index vector of length ``n``."""
    if n == 0:
        return np.empty(0, dtype=int)
    n_blocks = int(np.ceil(n / block_len))
    starts = rng.randint(0, n, size=n_blocks)
    idx = np.concatenate([(np.arange(s, s + block_len) % n) for s in starts])
    return idx[:n]


@dataclass(frozen=True)
class SignificanceResult:
    """Significance block for one OOS return series."""

    n: int
    n_boot: int
    block_len: int
    alpha: float
    hurdle: float
    cagr_point: float
    cagr_ci_low: float
    cagr_ci_high: float
    sharpe_point: float
    sharpe_ci_low: float
    sharpe_ci_high: float
    skew: float                     # sample skewness of the return series (for DSR)
    kurtosis: float                 # sample kurtosis (normal = 3, for DSR)
    p_cagr_below_hurdle: float      # H0: CAGR ≥ hurdle; small ⇒ confidently above
    p_sharpe_le_0: float            # H0: true mean = 0; small ⇒ Sharpe > 0
    significant_beats_hurdle: bool  # p_cagr_below_hurdle < alpha
    significant_positive: bool      # p_sharpe_le_0 < alpha
    degenerate: bool                # too few bars to bootstrap meaningfully

    def to_dict(self) -> dict:
        return asdict(self)


def bootstrap_significance(returns, *, P: int = TRADING_DAYS_PER_YEAR,
                           hurdle: float = 0.50, rf_annual: float = 0.0,
                           n_boot: int = DEFAULT_N_BOOT, alpha: float = DEFAULT_ALPHA,
                           block_len: int | None = None, seed: int = 12345) -> SignificanceResult:
    """Moving-block bootstrap CI + p-values for CAGR and Sharpe of ``returns``.

    ``returns`` is the per-bar OOS return series (cost-after). Returns a
    :class:`SignificanceResult`; on a series too short to resample it is flagged
    ``degenerate`` and every p-value defaults to the non-significant end (1.0).
    """
    ret = np.asarray([r for r in returns if r is not None and np.isfinite(r)], dtype=float)
    n = int(len(ret))
    rf_bar = rf_annual / P

    if n < 4:
        eq = np.cumprod(1.0 + ret) if n >= 2 else np.array([1.0])
        return SignificanceResult(
            n=n, n_boot=0, block_len=0, alpha=alpha, hurdle=hurdle,
            cagr_point=_cagr(eq, P) if n >= 2 else 0.0,
            cagr_ci_low=0.0, cagr_ci_high=0.0,
            sharpe_point=_sharpe(ret - rf_bar, P) if n >= 2 else 0.0,
            sharpe_ci_low=0.0, sharpe_ci_high=0.0, skew=0.0, kurtosis=3.0,
            p_cagr_below_hurdle=1.0, p_sharpe_le_0=1.0,
            significant_beats_hurdle=False, significant_positive=False,
            degenerate=True)

    L = block_len or _block_len(n)
    rng = np.random.RandomState(seed)

    eq_point = np.cumprod(1.0 + ret)
    cagr_point = _cagr(eq_point, P)
    sharpe_point = _sharpe(ret - rf_bar, P)

    mu, sd = ret.mean(), ret.std()
    if sd > 0:
        skew = float(np.mean(((ret - mu) / sd) ** 3))
        kurtosis = float(np.mean(((ret - mu) / sd) ** 4))
    else:
        skew, kurtosis = 0.0, 3.0

    ret_centered = ret - mu           # H0: true mean 0 (for the Sharpe null)

    cagr_boot = np.empty(n_boot, dtype=float)
    sharpe_boot = np.empty(n_boot, dtype=float)
    sharpe_null = np.empty(n_boot, dtype=float)
    for b in range(n_boot):
        idx = _moving_block_indices(n, L, rng)
        rs = ret[idx]
        cagr_boot[b] = _cagr(np.cumprod(1.0 + rs), P)
        sharpe_boot[b] = _sharpe(rs - rf_bar, P)
        sharpe_null[b] = _sharpe(ret_centered[idx], P)

    cagr_ci_low, cagr_ci_high = (float(np.quantile(cagr_boot, alpha / 2.0)),
                                 float(np.quantile(cagr_boot, 1.0 - alpha / 2.0)))
    sharpe_ci_low, sharpe_ci_high = (float(np.quantile(sharpe_boot, alpha / 2.0)),
                                     float(np.quantile(sharpe_boot, 1.0 - alpha / 2.0)))
    p_cagr_below_hurdle = float(np.mean(cagr_boot < hurdle))
    # +1 smoothing: a permutation/bootstrap p-value is never exactly 0
    p_sharpe_le_0 = float((1.0 + np.sum(sharpe_null >= sharpe_point)) / (n_boot + 1.0))

    return SignificanceResult(
        n=n, n_boot=n_boot, block_len=L, alpha=alpha, hurdle=hurdle,
        cagr_point=cagr_point, cagr_ci_low=cagr_ci_low, cagr_ci_high=cagr_ci_high,
        sharpe_point=sharpe_point, sharpe_ci_low=sharpe_ci_low, sharpe_ci_high=sharpe_ci_high,
        skew=skew, kurtosis=kurtosis,
        p_cagr_below_hurdle=p_cagr_below_hurdle, p_sharpe_le_0=p_sharpe_le_0,
        significant_beats_hurdle=bool(p_cagr_below_hurdle < alpha),
        significant_positive=bool(p_sharpe_le_0 < alpha),
        degenerate=False)
