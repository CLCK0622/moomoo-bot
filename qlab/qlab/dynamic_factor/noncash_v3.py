"""V3 no-acquisition boundaries. Supplied receipts never authorize execution.

Real B is deliberately unsealed: EVO-883 v18 accepted the inventory framework,
but explicitly refused it as a runtime catalog. Synthetic catalogs exercise the
mechanisms only and cannot be presented as that missing release.
"""

from copy import deepcopy
from datetime import datetime

from .contract import code_sha, digest, is_sha, result
from .conventions import load_conventions
from .fees import finite
from .state_v2 import necessary_state_known
from .catalog_members import members

ACCEPTED_CATALOG_SHA256 = None
CATALOG_REASON = "EVO883/01a18ca6-5887-71b9-b06d-7777e5139585: v21 protective registration; 61 fact UNKNOWN; runtime B release remains absent"
ROUTES = {
    "buy",
    "pending_order",
    "migration",
    "exchange",
    "in_kind_distribution",
    "old_rights",
}
CONSUMERS = {
    "score",
    "label",
    "calibration",
    "holdings_valuation",
    "cash_valuation",
    "order",
}
STATUSES = {"CLEAR", "UNRESOLVED", "UNKNOWN"}


def instant(value):
    if not isinstance(value, str):
        raise ValueError("B.timestamp_required")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("B.timezone_required")
    return parsed


def seal_guard(request, policy=None):
    p = policy or load_conventions()
    required = {"catalog", "mode", "sealed_at", "first_performance_at", "synthetic"}
    if (
        p.document["version"] != "v3.0.0"
        or not isinstance(request, dict)
        or not required.issubset(request)
        or set(request)
        - required
        - {"signal_close", "prior_guard_sha256", "catalog_registration"}
        or request["mode"] not in {"history", "forward"}
        or type(request["synthetic"]) is not bool
    ):
        raise ValueError("B.guard_schema_invalid")
    sealed = instant(request["sealed_at"])
    if "prior_guard_sha256" in request and (
        request["mode"] != "forward" or not is_sha(request["prior_guard_sha256"])
    ):
        raise ValueError("B.forward_prior_guard_required")
    if sealed >= instant(request["first_performance_at"]) and (
        request["mode"] == "history" or "prior_guard_sha256" not in request
    ):
        raise ValueError("B.not_sealed_before_performance")
    if request["mode"] == "forward":
        cutoff = instant(request["signal_close"])
    else:
        cutoff = sealed
    catalog = request["catalog"]
    if (
        not isinstance(catalog, dict)
        or set(catalog) != {"universe", "calendar_sha256", "entries"}
        or catalog["universe"] != p.profile["universe"]
        or catalog["calendar_sha256"] != digest(p.calendar)
        or not isinstance(catalog["entries"], list)
        or [r.get("symbol") for r in catalog["entries"] if isinstance(r, dict)]
        != p.profile["universe"]
        or len(catalog["entries"]) != 64
    ):
        raise ValueError("B.full_U64_catalog_required")
    for row in catalog["entries"]:
        if (
            set(row) - {"guard_pending_review", "fact_state", "B_membership"}
            != {
                "symbol",
                "status",
                "children",
                "evidence_sha256",
                "received_at",
                "credible_event_evidence",
                "event_or_candidate_id",
            }
            or row["status"] not in STATUSES
            or (
                "guard_pending_review" in row
                and type(row["guard_pending_review"]) is not bool
            )
            or (
                row.get("guard_pending_review") is True
                and (
                    row["status"] != "UNKNOWN"
                    or row.get("fact_state") != "UNKNOWN"
                    or row["credible_event_evidence"] is not True
                )
            )
            or ("fact_state" in row and row["fact_state"] not in STATUSES)
            or ("B_membership" in row and row["B_membership"] is not None)
            or not isinstance(row["children"], list)
            or len(set(row["children"])) != len(row["children"])
            or any(
                not isinstance(s, str)
                or not s
                or s in p.profile["universe"]
                or s == p.profile["portfolio"]["base_ticker"]
                for s in row["children"]
            )
            or not is_sha(row["evidence_sha256"])
            or type(row["credible_event_evidence"]) is not bool
            or (row["status"] == "UNRESOLVED" and not row["credible_event_evidence"])
            or (row["status"] == "CLEAR" and row["credible_event_evidence"])
            or (
                row["credible_event_evidence"]
                and (
                    not isinstance(row["event_or_candidate_id"], str)
                    or not row["event_or_candidate_id"]
                )
            )
            or (
                not row["credible_event_evidence"]
                and row["event_or_candidate_id"] is not None
            )
            or instant(row["received_at"]) > min(sealed, cutoff)
        ):
            raise ValueError("B.catalog_evidence_invalid")
    catalog_sha = digest(catalog)
    registration = request.get("catalog_registration")
    if registration is not None:
        from .catalog_v21 import derive, BINDINGS

        derived = derive(p)
        if (
            request["synthetic"]
            or catalog != derived["catalog"]
            or registration
            != dict(
                source_bindings=BINDINGS,
                B_derivation_sha256=derived["B_derivation_sha256"],
            )
        ):
            raise ValueError("B.v21_registered_derivation_required")
    if (
        not request["synthetic"]
        and registration is None
        and (ACCEPTED_CATALOG_SHA256 is None or catalog_sha != ACCEPTED_CATALOG_SHA256)
    ):
        raise ValueError("B.catalog_not_accepted_for_runtime_sealing")
    blocked, unknown = members(catalog["entries"])
    payload = dict(
        request=deepcopy(request),
        catalog_sha256=catalog_sha,
        accepted_catalog_sha256=ACCEPTED_CATALOG_SHA256,
        B=blocked,
        unknown=unknown,
        children=sorted({s for r in catalog["entries"] for s in r["children"]}),
        runtime_consumable=False,
        certifiable=False,
        **p.binding,
    )
    if registration is not None:
        payload.update(
            B_catalog_release_sha256=None,
            B_derivation_sha256=derived["B_derivation_sha256"],
            catalog_registration_only=True,
            fact_counts=derived["fact_counts"],
        )
    return dict(payload, noncash_guard_manifest_sha256=digest(payload))


def checked_guard(guard, policy=None):
    if not isinstance(guard, dict) or seal_guard(guard["request"], policy) != guard:
        raise ValueError("B.guard_identity_mismatch")
    return guard


def actor_ids(policy=None):
    p = policy or load_conventions()
    # The meta strategy and every primary monitor get separate source receipts.
    members = p.document["variance_layers"]["family_definitions"]["meta_members"]
    return tuple(
        kind + "/" + member
        for kind in ("strategy", "virtual_monitor")
        for member in members
    )


def allowed_symbols(guard, policy=None):
    p = policy or load_conventions()
    checked_guard(guard, p)
    return set(p.profile["universe"]) - set(guard["B"]) - set(guard["unknown"]) | {
        p.profile["portfolio"]["base_ticker"]
    }


def assert_consumer_symbols(guard, consumer, symbols, policy=None):
    if consumer not in CONSUMERS:
        raise ValueError("B.factor_consumer_required_reference_proof_deferred")
    if not set(symbols).issubset(allowed_symbols(guard, policy)):
        raise ValueError("B.parent_unknown_or_child_numeric_read_forbidden")


def guarded_value(guard, consumer, symbol, reader, *, policy=None):
    """The only injected numeric-reader call, dominated by the symbol guard."""
    assert_consumer_symbols(guard, consumer, [symbol], policy)
    return reader(symbol)


def economic_values(guard, consumer, symbols, reader, *, policy=None):
    assert_consumer_symbols(guard, consumer, symbols, policy)
    return {
        s: guarded_value(guard, consumer, s, reader, policy=policy) for s in symbols
    }


def economic_read_receipt(
    guard, consumer, symbols, reader, *, actor=None, origin=None, policy=None
):
    """Witness the numeric boundary; a catalog/hash lookup is not this receipt."""
    p = policy or load_conventions()
    if not isinstance(origin, dict) or actor is None:
        raise ValueError("B.actor_bound_numeric_origin_required")
    if (
        origin.get("actor") != actor
        or origin.get("noncash_guard_manifest_sha256")
        != guard["noncash_guard_manifest_sha256"]
        or not is_sha(origin.get("source_sha256"))
        or origin.get("zero_origin_receipt_sha256")
        != digest(
            {k: v for k, v in origin.items() if k != "zero_origin_receipt_sha256"}
        )
    ):
        raise ValueError("B.numeric_actor_origin_source_mismatch")
    if actor in actor_ids(p):
        if (
            zero_origin(
                guard, actor, origin["initial_state"], origin["source_sha256"], p
            )
            != origin
        ):
            raise ValueError("B.zero_origin_or_actor_mismatch")
    elif actor not in {
        "reference/CREF-F1-L020",
        "reference/CREF-F3-L020",
        "reference/MREF-F2-L020",
        "reference/MREF-F4-L020",
    }:
        raise ValueError("B.actor_bound_numeric_origin_required")
    values = economic_values(guard, consumer, symbols, reader, policy=p)
    payload = dict(
        actor=actor,
        zero_origin_receipt_sha256=origin["zero_origin_receipt_sha256"],
        source_sha256=origin["source_sha256"],
        consumer=consumer,
        symbols=list(symbols),
        numeric_values_sha256=digest(values),
        reader_source_sha256=code_sha(reader),
        guard_mechanism_sha256=code_sha(guarded_value),
        noncash_guard_manifest_sha256=guard["noncash_guard_manifest_sha256"],
        input_kind="numeric_values",
        read_boundary_exercised=bool(symbols),
        independently_verified=False,
        runtime_consumable=False,
    )
    return values, dict(payload, numeric_read_receipt_sha256=digest(payload))


def zero_exposure(state, guard, *, initial=False):
    necessary_state_known(state)
    if not (
        set(guard["request"]["catalog"]["universe"]) | set(guard["children"])
    ).issubset(state["inventory"]):
        raise ValueError("B.complete_inventory_zero_evidence_required")
    if (
        "pending_orders" not in state
        or not isinstance(state["pending_orders"], list)
        or state["rights"]
        or state["receivables"]
    ):
        raise ValueError("B.zero_exposure_unproven_or_old_rights")
    blocked = set(guard["B"]) | set(guard["unknown"]) | set(guard["children"])
    # An undeclared child cannot acquire an exemption by being absent from
    # the current directory. The frozen domain plus QQQ is the outer boundary.
    blocked.update(
        set(state["inventory"]) - set(guard["request"]["catalog"]["universe"]) - {"QQQ"}
    )
    if any(q and (initial or s in blocked) for s, q in state["inventory"].items()):
        raise ValueError("B.nonzero_initial_or_guarded_exposure")
    for order in state["pending_orders"]:
        if (
            not isinstance(order, dict)
            or set(order) != {"symbol", "side", "quantity"}
            or not isinstance(order["symbol"], str)
            or order["side"] not in {"BUY", "SELL"}
            or type(order["quantity"]) is not int
            or order["quantity"] < 0
        ):
            raise ValueError("B.pending_state_unknown")
        if (
            order["side"] == "BUY"
            and order["quantity"]
            and (
                initial
                or order["symbol"] in blocked
                or order["symbol"]
                not in set(guard["request"]["catalog"]["universe"]) | {"QQQ"}
            )
        ):
            raise ValueError("B.guarded_pending_buy")


def zero_origin(guard, actor, state, source_sha256, policy=None):
    p = policy or load_conventions()
    checked_guard(guard, p)
    if actor not in actor_ids(p) or not is_sha(source_sha256):
        raise ValueError("B.actor_and_source_receipt_required")
    zero_exposure(state, guard, initial=True)
    if (
        type(state.get("initialization_count")) is not int
        or state["initialization_count"] != 1
    ):
        raise ValueError("B.zero_origin_no_capital_restart")
    payload = dict(
        actor=actor,
        source_sha256=source_sha256,
        initial_state=deepcopy(state),
        noncash_guard_manifest_sha256=guard["noncash_guard_manifest_sha256"],
        mechanism_sha256=code_sha(zero_origin),
        receipt_consistency_only=True,
        runtime_consumable=False,
        certifiable=False,
    )
    return dict(payload, zero_origin_receipt_sha256=digest(payload))


def acquisition_check(guard, actor, origin, before, after, route, policy=None):
    p = policy or load_conventions()
    checked_guard(guard, p)
    if route not in ROUTES or actor not in actor_ids(p):
        raise ValueError("B.acquisition_route_or_actor_unknown")
    if (
        not isinstance(origin, dict)
        or zero_origin(
            guard, actor, origin["initial_state"], origin["source_sha256"], p
        )
        != origin
    ):
        raise ValueError("B.zero_origin_or_actor_mismatch")
    zero_exposure(before, guard)
    zero_exposure(after, guard)
    if before.get("initialization_count") != origin["initial_state"][
        "initialization_count"
    ] or after.get("initialization_count") != before.get("initialization_count"):
        raise ValueError("B.capital_restart_forbidden")
    return dict(
        actor=actor,
        route=route,
        q_B_zero=True,
        execution_verified=False,
        original_execution_gates_still_required=True,
        state=deepcopy(after),
    )


def no_dependency_receipt(guard, actor, origin, reads, policy=None):
    """Close only new-path child-price dependencies, separately for each actor."""
    p = policy or load_conventions()
    checked_guard(guard, p)
    if (
        zero_origin(guard, actor, origin["initial_state"], origin["source_sha256"], p)
        != origin
    ):
        raise ValueError("B.zero_origin_or_actor_mismatch")
    if not isinstance(reads, dict) or set(reads) != CONSUMERS:
        raise ValueError("B.all_economic_consumers_required")
    for consumer, receipt in reads.items():
        required = {
            "actor",
            "zero_origin_receipt_sha256",
            "source_sha256",
            "consumer",
            "symbols",
            "numeric_values_sha256",
            "reader_source_sha256",
            "guard_mechanism_sha256",
            "noncash_guard_manifest_sha256",
            "input_kind",
            "read_boundary_exercised",
            "independently_verified",
            "runtime_consumable",
            "numeric_read_receipt_sha256",
        }
        if (
            not isinstance(receipt, dict)
            or set(receipt) != required
            or receipt["consumer"] != consumer
            or receipt["actor"] != actor
            or receipt["zero_origin_receipt_sha256"]
            != origin["zero_origin_receipt_sha256"]
            or receipt["source_sha256"] != origin["source_sha256"]
            or not isinstance(receipt["symbols"], list)
            or not receipt["symbols"]
            or receipt["input_kind"] != "numeric_values"
            or receipt["read_boundary_exercised"] is not True
            or receipt["noncash_guard_manifest_sha256"]
            != guard["noncash_guard_manifest_sha256"]
            or receipt["guard_mechanism_sha256"] != code_sha(guarded_value)
            or not is_sha(receipt["numeric_values_sha256"])
            or not is_sha(receipt["reader_source_sha256"])
            or receipt["runtime_consumable"] is not False
            or receipt["independently_verified"] is not False
            or receipt["numeric_read_receipt_sha256"]
            != digest(
                {k: v for k, v in receipt.items() if k != "numeric_read_receipt_sha256"}
            )
        ):
            raise ValueError("B.numeric_boundary_receipt_required_not_catalog_hash")
        symbols = receipt["symbols"]
        assert_consumer_symbols(guard, consumer, symbols, p)
    payload = dict(
        actor=actor,
        zero_origin_receipt_sha256=origin["zero_origin_receipt_sha256"],
        noncash_guard_manifest_sha256=guard["noncash_guard_manifest_sha256"],
        acquisition_routes=sorted(ROUTES),
        numeric_read_scopes=deepcopy(reads),
        mechanism_sha256=code_sha(guarded_value),
        child_price_status="CONDITIONAL_NOT_APPLICABLE_MECHANISM_ONLY",
        child_price=None,
        receipt_consistency_only=True,
        independently_verified=False,
        real_zero_origin_and_runtime_reads_proven=False,
        runtime_consumable=False,
        certifiable=False,
    )
    return dict(
        payload, zero_exposure_and_consumer_dependency_receipt_sha256=digest(payload)
    )


def forward_event(
    guard,
    parent,
    children,
    received_at,
    signal_close,
    state,
    *,
    state_source_sha256,
    event_source_sha256,
    other_gates,
    previously_stopped=False,
    policy=None,
):
    p = policy or load_conventions()
    reasons = []
    retained = deepcopy(state)
    checked_guard(guard, p)
    if guard["request"]["mode"] != "forward" or parent not in p.profile["universe"]:
        raise ValueError("B.forward_scope_required")
    if not is_sha(event_source_sha256):
        raise ValueError("B.received_event_source_required")
    request = deepcopy(guard["request"])
    request["signal_close"] = signal_close
    request["sealed_at"] = signal_close
    request["prior_guard_sha256"] = guard["noncash_guard_manifest_sha256"]
    row = next(r for r in request["catalog"]["entries"] if r["symbol"] == parent)
    row.update(
        status="UNRESOLVED",
        children=children,
        received_at=received_at,
        evidence_sha256=event_source_sha256,
        credible_event_evidence=True,
        event_or_candidate_id="received/" + parent + "/" + event_source_sha256,
    )
    updated = seal_guard(request, p)
    try:
        if instant(received_at) > instant(signal_close):
            raise ValueError("B.forward_information_not_received")
        if previously_stopped:
            raise ValueError("B.no_automatic_restart")
        if not is_sha(state_source_sha256):
            raise ValueError("B.zero_exposure_evidence_missing")
        zero_exposure(state, updated)
        required = {
            "quantity",
            "M",
            "valuation",
            "cash",
            "fees",
            "age",
            "gain",
            "admission",
        }
        if (
            not isinstance(other_gates, dict)
            or set(other_gates) != required
            or any(v is not True for v in other_gates.values())
        ):
            raise ValueError("B.original_gates_not_all_verified")
    except (ValueError, KeyError, TypeError) as exc:
        reasons.append(str(exc))
    return p.bind(
        result(
            "noncash_forward_event",
            {"parent": parent, "guard": guard},
            reasons=reasons,
            metrics=dict(
                guard=updated,
                R2_stop=bool(reasons),
                continue_other_paths=not reasons,
                retained_state=retained,
                automatic_liquidation=False,
                restart_clock=False,
                next_state=deepcopy(state) if not reasons else None,
            ),
        )
    )
