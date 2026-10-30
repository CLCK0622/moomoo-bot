"""Synthetic scope and protocol fixtures; never market/performance evidence."""

from copy import deepcopy

from qlab.dynamic_factor.conventions import load_conventions
from qlab.dynamic_factor.contract import digest
from qlab.dynamic_factor.isolation import seal_manifest
from qlab.dynamic_factor.catalog_v21 import guard_request
from qlab.dynamic_factor.noncash_v3 import seal_guard
from qlab.dynamic_factor.reference_compile_v3 import seal_scope
from test_v2_isolation import synthetic_manifest


def sealed(*, real=False):
    p = load_conventions()
    r = synthetic_manifest(p)
    r.update(
        role="external_reference_roles",
        sealed_at="2026-10-30T12:00:00Z",
        first_performance_at="2026-11-01T00:00:00Z",
    )
    g = (
        guard_request(
            sealed_at="2026-10-30T11:55:00Z",
            first_performance_at=r["first_performance_at"],
        )
        if real
        else deepcopy(r["noncash_guard_manifest"]["request"])
    )
    g.update(
        sealed_at="2026-10-30T11:55:00Z", first_performance_at=r["first_performance_at"]
    )
    r["noncash_guard_manifest"] = seal_guard(g)
    if real:
        r["records"] = []
    return seal_manifest(r, p)


def unit_scope(*, real=False):
    p = load_conventions()
    return seal_scope(sealed(real=real), [p.calendar[600]], [], p)


def protocol_scope(train, warmup):
    """Counterfactual wire-format fixture only, not a full eligibility proof.

    Public source compilation is independently checked on original evidence;
    this expands one synthetic day to exercise the complete 1260/252 protocol.
    """
    s = unit_scope()
    template = next(iter(s["days"].values()))
    days = {}
    for date in train:
        day = deepcopy(template)
        day["date"] = date
        day["eligible_set_derivation_sha256"] = digest(
            {k: v for k, v in day.items() if k != "eligible_set_derivation_sha256"}
        )
        days[date] = day
    s.update(
        days=days,
        train=list(train),
        warmup=list(warmup),
        numeric_symbols={
            date: template["eligible"] for date in list(warmup) + list(train)
        },
        eligible_set_derivation_sha256=digest(days),
        eligible_set_manifest_sha256=digest(
            {date: day["eligible"] for date, day in days.items()}
        ),
    )
    s["scope_sha256"] = digest({k: v for k, v in s.items() if k != "scope_sha256"})
    return s


def synthetic_numeric_reader(symbol):
    return 100.0


def reference_proofs(guard):
    from qlab.dynamic_factor.reference_noncash import (
        actors,
        origin,
        acquisition,
        numeric_read,
        packet,
    )
    from qlab.dynamic_factor.noncash_v3 import CONSUMERS, ROUTES
    from v3_test_helpers import synthetic_zero_state

    out = {}
    for actor in actors():
        state = synthetic_zero_state(guard)
        initial = origin(
            guard, actor, state, digest("SYNTHETIC_REFERENCE_STATE/" + actor)
        )
        routes = {
            route: acquisition(guard, actor, initial, state, state, route)
            for route in sorted(ROUTES)
        }
        reads = {
            role: numeric_read(guard, actor, role, ["QQQ"], synthetic_numeric_reader)[1]
            for role in sorted(CONSUMERS)
        }
        out[actor] = packet(guard, actor, initial, routes, reads)
    return out
