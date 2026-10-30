"""Fee arithmetic from frozen parameter files; no account or quote access."""

from __future__ import annotations

import math
from datetime import date
from pathlib import Path

from .contract import result, unavailable

FIXTURES = Path(__file__).parent / "fixtures"


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def iso_date(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError("ISO date required")
    return value


def _legacy_fee_frontier(
    request,
    params_path,
    schedule_path=FIXTURES / "fee_schedule.json",
    *,
    conventions=None,
):
    """Retained import compatibility only; the obsolete numerical path is disabled."""
    from .conventions import load_conventions

    policy = conventions or load_conventions()
    return policy.bind(
        result(
            "fee_frontier",
            {"request": request, **policy.binding},
            metrics={
                "net_edge_bps": None,
                "cash_net_edge_bps": None,
                "annual_drag_fraction": None,
                "taf_usd": None,
                "cost_bps": None,
            },
            reasons=["fee.legacy_frontier_disabled"],
            availability={"net_edge_bps": unavailable("fee.legacy_frontier_disabled")},
            assumptions=[
                "The legacy fee implementation is disabled. Use the frozen restored-TAF research policy via fee_frontier."
            ],
        )
    )


def fee_frontier(
    request,
    params_path,
    schedule_path=FIXTURES / "fee_schedule.json",
    *,
    conventions=None,
):
    from .conventions import load_conventions
    from .fee_model import evaluate

    return evaluate(
        request, params_path, schedule_path, conventions or load_conventions()
    )
