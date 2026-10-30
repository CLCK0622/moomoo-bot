"""Compatibility dispatch: v0.1 refuses; explicitly bound v0.2 uses reviewed rules.

Unbound and historical v0.1 requests refuse with ``prereg_pending_v0.2``.
Explicit v0.2 bindings dispatch to the ordered pipeline and execution arithmetic.
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


def pool_admission_check(request, *, conventions=None, ledger=None):
    """Pool admission needs DSR>=threshold, whose V family needs post-admission members."""
    if conventions is not None and conventions.document["version"] in (
        "v1.0.1",
        "v2.0.0",
        "v3.0.0",
    ):
        from .pipeline import evaluate
        from .input_scope import reject_b2_inputs

        try:
            reject_b2_inputs(request, "admission")
        except ValueError as exc:
            return conventions.bind(
                result(
                    "pool_admission_check",
                    request,
                    metrics={"admitted": None, "dsr": None, "pool": None},
                    reasons=[str(exc)],
                )
            )

        if ledger is None:
            return conventions.bind(
                result(
                    "pool_admission_check",
                    {"request": request},
                    metrics={"admitted": None, "dsr": None, "pool": None},
                    reasons=["ledger_missing"],
                )
            )
        report = evaluate(dict(request, layer="candidate"), ledger, conventions)
        report["tool"] = "pool_admission_check"
        pool = report["metrics"].get("pool")
        report["metrics"]["pool"] = pool
        if pool is None:
            report["reasons"].append("pool.S2_unavailable_not_empty")
            report["ok"] = False
            report["metrics"]["fallback_holdings"] = None
        report["metrics"]["admitted"] = (
            (request["candidate_id"] in pool)
            if pool is not None and request.get("candidate_id") is not None
            else None
        )
        return report
    return _pending(
        "pool_admission_check",
        request,
        ("admitted", "dsr", "trials_variance"),
        "admission_dsr_and_v_family_dependency_loop",
    )


def initial_build_turnover_check(request, *, conventions=None, ledger=None):
    """First-day 0->98% build implies tau=49%, above the 20% turnover cap."""
    if conventions is not None and conventions.document["version"] in (
        "v1.0.1",
        "v2.0.0",
        "v3.0.0",
    ):
        from .execution import initial_build_turnover_check as calculate

        return calculate(request, conventions=conventions, ledger=ledger)
    return _pending(
        "initial_build_turnover_check",
        request,
        ("allowed", "one_way_turnover", "build_schedule"),
        "initial_build_vs_turnover_cap_not_closed",
    )


def voluntary_trade_gate(request, *, conventions=None, ledger=None):
    """Gain-to-NAV conversion for voluntary trades is not specified in v0.1."""
    if conventions is not None and conventions.document["version"] in (
        "v1.0.1",
        "v2.0.0",
        "v3.0.0",
    ):
        from .execution import voluntary_trade_gate as calculate

        return calculate(request, conventions=conventions, ledger=ledger)
    return _pending(
        "voluntary_trade_gate",
        request,
        ("allowed", "gain_nav_bps", "net_edge_bps"),
        "gain_to_nav_conversion_missing",
    )
