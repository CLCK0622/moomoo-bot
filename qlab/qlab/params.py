"""Strategy parameter sets and perturbation.

The original repo's tuned ``best_params.json`` lives under its gitignored
``reports/`` directory and was NEVER committed, so the exact winning parameter
vector behind the '~45%' claim is itself unavailable. ``DEFAULT_PARAMS`` below is
a documented, neutral baseline (core ORB long-only, optional filters off) that
exercises every code path the engine reads. It is a harness baseline, not a
recovered optimum — see ``qlab/README.md``.
"""
from __future__ import annotations

import copy

# Every key the vendored engine / exit manager / conditions read via .get(),
# pinned explicitly so runs are fully specified and auditable.
DEFAULT_PARAMS: dict = {
    # --- Opening range breakout (core, always-on) ---
    "orb_lock_minutes": 15,
    # --- Optional entry filters (off by default => pure ORB breakout) ---
    "use_vwap_filter": False,
    "use_kc_trend": False,
    "use_anti_chase": False,
    "use_rsi_filter": False,
    "rsi_overbought": 70.0,
    "use_macd_filter": False,
    "use_volume_spike": False,
    "use_ema_cross": False,
    "use_atr_pctl_filter": False,
    # --- Exits ---
    "tp1_rr_ratio": 1.0,
    "tp2_atr_mult": 3.0,
    "tp2_sell_pct": 0.5,
    "trailing_retain_pct": 0.2,
    "extreme_stop_pct": 0.03,
    "eod_close_minute": 55,
    "trailing_activate_rr": 1.5,
    "use_vwap_exit": False,
    "use_fixed_tp": False,
    "fixed_tp_pct": 0.015,
    # --- Session / risk controls ---
    "max_entry_hour": 15,
    "allow_reentry": True,
    "daily_loss_limit_pct": 0.015,
    # --- Auxiliary entry strategies ---
    "use_gap_and_go": False,
    "gap_go_min_pct": 0.03,
    "use_vwap_bounce": False,
    "vwap_bounce_threshold": 0.002,
    # --- Drawdown-adaptive position sizing ---
    "dd_scale_start": 0.05,
    "dd_scale_min": 0.4,
}

# Parameters perturbed in the robustness sweep, with relative deltas applied.
PERTURB_KEYS = [
    "orb_lock_minutes",
    "tp1_rr_ratio",
    "extreme_stop_pct",
    "trailing_activate_rr",
    "daily_loss_limit_pct",
]


def default_params() -> dict:
    return copy.deepcopy(DEFAULT_PARAMS)


def perturb(params: dict, key: str, rel_delta: float) -> dict:
    """Return a copy of ``params`` with ``key`` scaled by ``(1 + rel_delta)``.

    Integer-valued keys are rounded and kept >= 1.
    """
    out = copy.deepcopy(params)
    base = out[key]
    val = base * (1.0 + rel_delta)
    if isinstance(base, int):
        val = max(1, int(round(val)))
    out[key] = val
    return out
