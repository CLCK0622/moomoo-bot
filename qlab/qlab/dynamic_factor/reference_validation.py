"""Pure validation shared by the host and isolated reference worker. No IO."""

import hashlib
import json
import math
from datetime import datetime, timezone


def utc_instant(value):
    if not isinstance(value, str):
        raise ValueError("reference.timezone_timestamp_required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("reference.timezone_timestamp_required")
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("reference.timezone_timestamp_required") from exc


def validate_timing(scope, guard):
    """Guard <= scope < the same performance instant, in the same mode."""
    if scope.get("mode") not in {"history", "forward"} or scope["mode"] != guard.get(
        "mode"
    ):
        raise ValueError("reference.scope_guard_mode_mismatch")
    sealed = utc_instant(scope["sealed_at"])
    performance = utc_instant(scope["first_performance_at"])
    if (
        utc_instant(guard["first_performance_at"]) != performance
        or not utc_instant(guard["sealed_at"]) <= sealed < performance
    ):
        raise ValueError("reference.scope_view_or_preperformance_mismatch")


def zero_state(state, scope, initial=False):
    fields = {
        "inventory",
        "cash",
        "nav",
        "age",
        "origin",
        "rights",
        "receivables",
        "pending_orders",
        "unknown_components",
        "initialization_count",
    }
    if (
        not isinstance(state, dict)
        or not fields.issubset(state)
        or set(state) - fields - {"date", "retired_ids", "exit_intents"}
    ):
        raise ValueError("reference.R2_zero_exposure_state_unknown")

    def unknown(value):
        return (
            value is None
            or (isinstance(value, dict) and any(unknown(v) for v in value.values()))
            or (isinstance(value, list) and any(unknown(v) for v in value))
        )

    if (
        any(unknown(state[k]) for k in fields)
        or state["rights"]
        or state["receivables"]
        or state["unknown_components"]
        or type(state["initialization_count"]) is not int
        or state["initialization_count"] != 1
        or any(
            not isinstance(state[k], dict)
            for k in ("inventory", "age", "origin", "rights", "receivables")
        )
    ):
        raise ValueError("reference.R2_zero_exposure_state_unknown")
    if (
        type(state["cash"]) not in (int, float)
        or type(state["nav"]) not in (int, float)
        or not math.isfinite(state["cash"])
        or not math.isfinite(state["nav"])
        or state["cash"] < 0
        or state["nav"] <= 0
    ):
        raise ValueError("reference.R2_zero_exposure_state_unknown")
    if (
        any(not isinstance(k, str) for k in state["inventory"])
        or any(
            not isinstance(k, str) or type(v) is not int or v < 0
            for k, v in state["age"].items()
        )
        or any(
            not isinstance(k, str) or not isinstance(v, str)
            for k, v in state["origin"].items()
        )
        or any(
            q and (k not in state["age"] or k not in state["origin"])
            for k, q in state["inventory"].items()
        )
    ):
        raise ValueError("reference.R2_zero_exposure_state_unknown")
    guard = scope["guard"]
    domain = set(scope["universe"]) | set(guard["children"])
    if not domain.issubset(state["inventory"]) or any(
        type(q) is not int or q < 0 for q in state["inventory"].values()
    ):
        raise ValueError("reference.R2_zero_exposure_state_unknown")
    blocked = set(guard["B"]) | set(guard["unknown"]) | set(guard["children"])
    if any(
        q and (initial or s in blocked or s not in set(scope["universe"]) | {"QQQ"})
        for s, q in state["inventory"].items()
    ):
        raise ValueError("reference.R2_nonzero_guarded_exposure")
    if not isinstance(state["pending_orders"], list):
        raise ValueError("reference.R2_zero_exposure_state_unknown")
    for order in state["pending_orders"]:
        if (
            set(order) != {"symbol", "side", "quantity"}
            or order["side"] not in {"BUY", "SELL"}
            or type(order["quantity"]) is not int
            or order["quantity"] < 0
        ):
            raise ValueError("reference.R2_zero_exposure_state_unknown")
        if (
            order["side"] == "BUY"
            and order["quantity"]
            and (
                initial
                or order["symbol"] in blocked
                or order["symbol"] not in set(scope["universe"]) | {"QQQ"}
            )
        ):
            raise ValueError("reference.R2_guarded_pending_buy")


REFERENCE_ACTORS = {
    "reference/CREF-F1-L020",
    "reference/CREF-F3-L020",
    "reference/MREF-F2-L020",
    "reference/MREF-F4-L020",
}
REGISTRY_SHA256 = "f531d65a5ad54fc68a8be40bc25cbb3987d0aeedd4c2c345ed334b1599445c48"


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()


def is_sha(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(c in "0123456789abcdef" for c in value)
    )


def checked_document(doc, fields, key):
    if (
        not isinstance(doc, dict)
        or set(doc) != set(fields.split()) | {key}
        or not is_sha(doc.get(key))
        or doc[key] != digest({k: v for k, v in doc.items() if k != key})
    ):
        raise ValueError("reference.proof_receipt_identity_invalid")


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def validate_packet_document(guard, actor, packet, mechanisms):
    """One complete, IO-free packet policy for both compiler and worker.

    Mechanism identities come from trusted host source, outside the caller's
    JSON request. Re-signing a nested payload cannot substitute another actor,
    source, registry, guard or mechanism. Raw simulator states remain evidence.
    """
    require(
        isinstance(mechanisms, dict)
        and set(mechanisms)
        == {"origin", "acquisition", "numeric_read", "guarded_value"}
        and all(is_sha(v) for v in mechanisms.values()),
        "reference.trusted_mechanism_bindings_required",
    )
    require(actor in REFERENCE_ACTORS, "reference.separate_actor_required")
    scope = dict(guard=guard, universe=guard["request"]["catalog"]["universe"])
    guard_sha = guard["noncash_guard_manifest_sha256"]
    checked_document(
        packet,
        """actor producer_kind registry_sha256 noncash_guard_manifest_sha256
        zero_origin no_acquisition economic_no_read scope independently_verified real_runtime_proven
        runtime_consumable certifiable""",
        "reference_proof_packet_sha256",
    )
    require(
        packet["actor"] == actor
        and packet["producer_kind"] == "reference"
        and packet["registry_sha256"] == REGISTRY_SHA256
        and packet["noncash_guard_manifest_sha256"] == guard_sha
        and all(
            packet[k] is False
            for k in (
                "independently_verified",
                "real_runtime_proven",
                "runtime_consumable",
                "certifiable",
            )
        )
        and isinstance(packet["scope"], str),
        "reference.separate_proof_packet_mismatch",
    )
    initial, no_buy, no_read = (
        packet["zero_origin"],
        packet["no_acquisition"],
        packet["economic_no_read"],
    )
    checked_document(
        initial,
        """actor producer_kind registry_sha256 initial_state source_sha256
        noncash_guard_manifest_sha256 mechanism_sha256 runtime_consumable certifiable""",
        "zero_origin_receipt_sha256",
    )
    require(
        initial["actor"] == actor
        and initial["producer_kind"] == "reference"
        and initial["registry_sha256"] == REGISTRY_SHA256
        and initial["noncash_guard_manifest_sha256"] == guard_sha
        and initial["mechanism_sha256"] == mechanisms["origin"]
        and is_sha(initial["source_sha256"])
        and initial["runtime_consumable"] is False
        and initial["certifiable"] is False,
        "reference.separate_zero_origin_required",
    )
    zero_state(initial["initial_state"], scope, initial=True)
    for key, kind in (("age", int), ("origin", str)):
        require(
            isinstance(initial["initial_state"][key], dict)
            and all(
                isinstance(k, str) and type(v) is kind
                for k, v in initial["initial_state"][key].items()
            ),
            "reference.R2_zero_exposure_state_unknown",
        )
    origin_sha, source_sha = (
        initial["zero_origin_receipt_sha256"],
        initial["source_sha256"],
    )
    routes = {
        "buy",
        "pending_order",
        "migration",
        "exchange",
        "in_kind_distribution",
        "old_rights",
    }
    consumers = {
        "score",
        "label",
        "calibration",
        "holdings_valuation",
        "cash_valuation",
        "order",
    }
    checked_document(
        no_buy,
        """actor routes zero_origin_receipt_sha256 all_acquisition_routes_checked
        mechanism_sha256""",
        "no_acquisition_receipt_sha256",
    )
    checked_document(
        no_read,
        """actor reads zero_origin_receipt_sha256 no_acquisition_receipt_sha256
        mechanism_sha256 child_price child_price_status runtime_consumable""",
        "economic_no_read_receipt_sha256",
    )
    require(
        no_buy["actor"] == no_read["actor"] == actor
        and isinstance(no_buy["routes"], dict)
        and set(no_buy["routes"]) == routes
        and isinstance(no_read["reads"], dict)
        and set(no_read["reads"]) == consumers,
        "reference.separate_routes_and_consumers_required",
    )
    require(
        no_buy["zero_origin_receipt_sha256"]
        == no_read["zero_origin_receipt_sha256"]
        == origin_sha
        and no_read["no_acquisition_receipt_sha256"]
        == no_buy["no_acquisition_receipt_sha256"]
        and no_buy["all_acquisition_routes_checked"] is True
        and no_buy["mechanism_sha256"] == mechanisms["acquisition"]
        and no_read["mechanism_sha256"] == mechanisms["numeric_read"]
        and no_read["child_price"] is None
        and no_read["child_price_status"] == "CONDITIONAL_NOT_APPLICABLE_MECHANISM_ONLY"
        and no_read["runtime_consumable"] is False,
        "reference.proof_origin_link_invalid",
    )
    for route, row in no_buy["routes"].items():
        checked_document(
            row,
            """actor route before after zero_origin_receipt_sha256
            noncash_guard_manifest_sha256 mechanism_sha256 q_B_zero runtime_consumable""",
            "route_receipt_sha256",
        )
        require(
            row["actor"] == actor
            and row["route"] == route
            and row["zero_origin_receipt_sha256"] == origin_sha
            and row["noncash_guard_manifest_sha256"] == guard_sha
            and row["mechanism_sha256"] == mechanisms["acquisition"]
            and row["q_B_zero"] is True
            and row["runtime_consumable"] is False,
            "reference.acquisition_induction_receipt_mismatch",
        )
        zero_state(row["before"], scope)
        zero_state(row["after"], scope)
    for consumer, read in no_read["reads"].items():
        checked_document(
            read,
            """actor zero_origin_receipt_sha256 source_sha256 reader_source_sha256
            numeric_values_sha256 producer_kind consumer numeric_receipt mechanism_sha256
            registry_sha256 noncash_guard_manifest_sha256 runtime_consumable""",
            "reference_numeric_receipt_sha256",
        )
        inner = read["numeric_receipt"]
        checked_document(
            inner,
            """actor zero_origin_receipt_sha256 source_sha256 consumer symbols
            numeric_values_sha256 reader_source_sha256 guard_mechanism_sha256
            noncash_guard_manifest_sha256 input_kind read_boundary_exercised independently_verified
            runtime_consumable registry_sha256""",
            "numeric_read_receipt_sha256",
        )
        require(
            read["actor"] == inner["actor"] == actor
            and read["consumer"] == inner["consumer"] == consumer
            and read["zero_origin_receipt_sha256"]
            == inner["zero_origin_receipt_sha256"]
            == origin_sha
            and read["source_sha256"] == inner["source_sha256"] == source_sha
            and read["producer_kind"] == "reference"
            and read["registry_sha256"] == inner["registry_sha256"] == REGISTRY_SHA256
            and read["noncash_guard_manifest_sha256"]
            == inner["noncash_guard_manifest_sha256"]
            == guard_sha
            and read["mechanism_sha256"] == mechanisms["numeric_read"]
            and inner["guard_mechanism_sha256"] == mechanisms["guarded_value"]
            and read["reader_source_sha256"] == inner["reader_source_sha256"]
            and read["numeric_values_sha256"] == inner["numeric_values_sha256"]
            and is_sha(inner["reader_source_sha256"])
            and is_sha(inner["numeric_values_sha256"])
            and inner["input_kind"] == "numeric_values"
            and inner["read_boundary_exercised"] is True
            and inner["independently_verified"] is False
            and inner["runtime_consumable"] is False
            and read["runtime_consumable"] is False,
            "reference.numeric_boundary_proof_required",
        )
        symbols = inner["symbols"]
        require(
            isinstance(symbols, list)
            and bool(symbols)
            and all(isinstance(s, str) for s in symbols)
            and len(symbols) == len(set(symbols))
            and not set(symbols)
            & (set(guard["B"]) | set(guard["unknown"]) | set(guard["children"]))
            and set(symbols).issubset(set(scope["universe"]) | {"QQQ"}),
            "reference.numeric_boundary_proof_required",
        )
    return packet
