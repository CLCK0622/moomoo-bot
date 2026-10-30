"""Counterfactual complete U64 catalogs only; never the real v18 catalog."""

from qlab.dynamic_factor.conventions import load_conventions
from qlab.dynamic_factor.contract import digest
from qlab.dynamic_factor.noncash_v3 import seal_guard


def synthetic_guard(p=None, *, blocked=(), unknown=(), mode="history"):
    p = p or load_conventions()
    entries = [
        dict(
            symbol=s,
            status="UNRESOLVED"
            if s in blocked
            else "UNKNOWN"
            if s in unknown
            else "CLEAR",
            children=["SYNTHETIC_CHILD_" + s] if s in blocked else [],
            evidence_sha256=digest("SYNTHETIC_CATALOG_" + s),
            received_at="2026-10-01T00:00:00Z",
            credible_event_evidence=s in blocked,
            event_or_candidate_id="SYNTHETIC_EVENT_" + s if s in blocked else None,
        )
        for s in p.profile["universe"]
    ]
    request = dict(
        catalog=dict(
            universe=p.profile["universe"],
            calendar_sha256=digest(p.calendar),
            entries=entries,
        ),
        mode=mode,
        synthetic=True,
        sealed_at="2026-10-02T00:00:00Z",
        first_performance_at="2026-10-03T00:00:00Z",
    )
    if mode == "forward":
        request["signal_close"] = request["sealed_at"]
    return seal_guard(request, p)


def synthetic_zero_state(guard):
    inventory = {
        s: 0
        for s in guard["request"]["catalog"]["universe"] + guard["children"] + ["QQQ"]
    }
    return dict(
        inventory=inventory,
        cash=15000,
        nav=15000,
        age={},
        origin={},
        rights={},
        receivables={},
        pending_orders=[],
        unknown_components=[],
        initialization_count=1,
    )
