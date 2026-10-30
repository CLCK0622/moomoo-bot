"""Interface stubs for rules EVO-883 v0.1 leaves unresolved (review draft1).

Each tool accepts its future request shape, fingerprints it, and refuses with
``prereg_pending_v0.2``. No default, family or conversion is invented here; the
bodies are filled only after v0.2 is delivered with a pinned SHA.
"""

from __future__ import annotations

from .contract import result, unavailable

PENDING = "prereg_pending_v0.2"


def _pending(tool, request, metric_names, gap):
    return result(
        tool,
        {"request": request},
        metrics={k: None for k in metric_names},
        reasons=[PENDING],
        missing=[gap],
        availability={k: unavailable(PENDING) for k in metric_names},
        assumptions=[f"EVO-883 v0.1 does not close: {gap}"],
    )


def pool_admission_check(request):
    """Pool admission needs DSR>=threshold, whose V family needs post-admission members."""
    return _pending(
        "pool_admission_check",
        request,
        ("admitted", "dsr", "trials_variance"),
        "admission_dsr_and_v_family_dependency_loop",
    )


def initial_build_turnover_check(request):
    """First-day 0->98% build implies tau=49%, above the 20% turnover cap."""
    return _pending(
        "initial_build_turnover_check",
        request,
        ("allowed", "one_way_turnover", "build_schedule"),
        "initial_build_vs_turnover_cap_not_closed",
    )


def voluntary_trade_gate(request):
    """Gain-to-NAV conversion for voluntary trades is not specified in v0.1."""
    return _pending(
        "voluntary_trade_gate",
        request,
        ("allowed", "gain_nav_bps", "net_edge_bps"),
        "gain_to_nav_conversion_missing",
    )
