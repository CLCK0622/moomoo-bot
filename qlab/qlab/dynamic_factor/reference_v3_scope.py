"""Pure closed scope validator loaded before the worker's file capability."""

import hashlib
import json
import math

from .catalog_members import members


UNIVERSE_SHA256 = "3a1f8ddcdc7707d9e0033a41e3a280ceb6396a483090435b17afd2c461b4d939"
RECIPE_IDS_SHA256 = "ae472dbcbad100d33eef49f27f7ea63f26096db421663c9927ed65011e304fd8"
REGISTERED_CATALOG_SHA256 = (
    "e1603f88dd3dda1de4fbab6418c8ea35e2251a9d1774083c41e27bab04040999"
)
PROFILE_BINDING_SHA256 = (
    "046280489ddc8c362a750c4b9aac167283046ecffa4d8b62f0e3098e70b55d1c"
)


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


def strings(value):
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def hash_value(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(c in "0123456789abcdef" for c in value)
    )


def validate_scope(scope, view, binding):
    fields = {
        "schema",
        "guard",
        "days",
        "train",
        "warmup",
        "numeric_symbols",
        "universe",
        "all16_recipe_ids",
        "quarantine_manifest_sha256",
        "eligible_set_derivation_sha256",
        "eligible_set_manifest_sha256",
        "source_evidence_version_sha256",
        "B_catalog_release_sha256",
        "B_derivation_sha256",
        "sealed_at",
        "first_performance_at",
        "bindings",
        "complete",
        "runtime_consumable",
        "certifiable",
        "scope_sha256",
    }
    if (
        not isinstance(scope, dict)
        or set(scope) != fields
        or scope["scope_sha256"]
        != digest({k: v for k, v in scope.items() if k != "scope_sha256"})
    ):
        raise ValueError("reference.scope_identity_or_schema_invalid")
    if any(
        not hash_value(scope[k])
        for k in (
            "scope_sha256",
            "quarantine_manifest_sha256",
            "eligible_set_derivation_sha256",
            "eligible_set_manifest_sha256",
            "source_evidence_version_sha256",
            "B_derivation_sha256",
        )
    ) or not all(
        strings(scope[k]) for k in ("train", "warmup", "universe", "all16_recipe_ids")
    ):
        raise ValueError("reference.scope_schema_invalid")
    if (
        scope["schema"] != "EVO900.reference-shared-scope/v3"
        or scope["train"] != list(view["train"])
        or scope["warmup"] != list(view["warmup"])
        or set(scope["days"]) != set(view["train"])
        or any(scope["bindings"].get(k) != v for k, v in binding.items())
        or scope["sealed_at"] >= scope["first_performance_at"]
        or scope["runtime_consumable"] is not False
        or scope["certifiable"] is not False
    ):
        raise ValueError("reference.scope_view_or_preperformance_mismatch")
    guard = scope["guard"]
    binding_keys = {
        "conventions_version",
        "conventions_status",
        "conventions_sha256",
        "profile_sha256",
        "prereg_version",
        "prereg_sha256",
        "common_profile_sha256",
    }
    if set(scope["bindings"]) != binding_keys:
        raise ValueError("reference.scope_binding_schema_invalid")
    if any(not isinstance(v, str) for v in scope["bindings"].values()):
        raise ValueError("reference.scope_binding_schema_invalid")
    if (
        digest(binding) != PROFILE_BINDING_SHA256
        or digest(scope["universe"]) != UNIVERSE_SHA256
        or digest(scope["all16_recipe_ids"]) != RECIPE_IDS_SHA256
    ):
        raise ValueError("reference.profile_or_universe_or_recipe_mismatch")
    if guard["noncash_guard_manifest_sha256"] != digest(
        {k: v for k, v in guard.items() if k != "noncash_guard_manifest_sha256"}
    ):
        raise ValueError("reference.guard_identity_invalid")
    catalog = guard["request"]["catalog"]
    if (
        guard["catalog_sha256"] != digest(catalog)
        or catalog["universe"] != scope["universe"]
        or len(scope["universe"]) != 64
        or len(set(scope["universe"])) != 64
    ):
        raise ValueError("reference.same_B_catalog_required")
    entries = catalog["entries"]
    base_guard = {
        "request",
        "catalog_sha256",
        "accepted_catalog_sha256",
        "B",
        "unknown",
        "children",
        "runtime_consumable",
        "certifiable",
        "noncash_guard_manifest_sha256",
    } | binding_keys
    if (
        set(guard)
        - base_guard
        - {
            "B_catalog_release_sha256",
            "B_derivation_sha256",
            "catalog_registration_only",
            "fact_counts",
        }
    ):
        raise ValueError("reference.guard_schema_invalid")
    if (
        guard["accepted_catalog_sha256"] is not None
        or scope["B_catalog_release_sha256"] is not None
        or any(not strings(guard[k]) for k in ("B", "unknown", "children"))
    ):
        raise ValueError("reference.runtime_B_release_not_published")
    if "fact_counts" in guard and (
        set(guard["fact_counts"]) != {"known_unclosed", "UNKNOWN"}
        or any(type(v) is not int for v in guard["fact_counts"].values())
    ):
        raise ValueError("reference.guard_schema_invalid")
    if set(guard["request"]) - {
        "catalog",
        "mode",
        "sealed_at",
        "first_performance_at",
        "synthetic",
        "signal_close",
        "prior_guard_sha256",
        "catalog_registration",
    } or set(catalog) != {"universe", "calendar_sha256", "entries"}:
        raise ValueError("reference.guard_schema_invalid")
    for entry in entries:
        base_entry = {
            "symbol",
            "status",
            "children",
            "evidence_sha256",
            "received_at",
            "credible_event_evidence",
            "event_or_candidate_id",
        }
        if not base_entry.issubset(entry) or set(entry) - base_entry - {
            "guard_pending_review",
            "fact_state",
            "B_membership",
        }:
            raise ValueError("reference.guard_schema_invalid")
        if (
            any(
                not isinstance(entry[k], str)
                for k in ("symbol", "status", "evidence_sha256", "received_at")
            )
            or not strings(entry["children"])
            or type(entry["credible_event_evidence"]) is not bool
            or (
                entry["event_or_candidate_id"] is not None
                and not isinstance(entry["event_or_candidate_id"], str)
            )
            or (
                "guard_pending_review" in entry
                and type(entry["guard_pending_review"]) is not bool
            )
            or (
                "fact_state" in entry
                and entry["fact_state"] not in {"CLEAR", "UNKNOWN", "UNRESOLVED"}
            )
            or ("B_membership" in entry and entry["B_membership"] is not None)
        ):
            raise ValueError("reference.guard_schema_invalid")
    registration = guard["request"].get("catalog_registration")
    if registration is not None:
        names = {
            "EVO893-B-noncash-catalog-v21.csv",
            "EVO893-B-CMI-guard-v21.json",
            "EVO883-v21-final-receipt.json",
        }
        if (
            set(registration) != {"source_bindings", "B_derivation_sha256"}
            or set(registration["source_bindings"]) != names
            or any(not hash_value(v) for v in registration["source_bindings"].values())
            or not hash_value(registration["B_derivation_sha256"])
        ):
            raise ValueError("reference.guard_schema_invalid")
    if [e["symbol"] for e in entries] != scope["universe"]:
        raise ValueError("reference.same_B_catalog_required")
    if (
        guard["request"]["synthetic"] is not True
        and guard["catalog_sha256"] != REGISTERED_CATALOG_SHA256
    ):
        raise ValueError("reference.same_registered_v21_derivation_required")
    blocked, unknown = members(entries)
    if blocked != guard["B"] or unknown != guard["unknown"]:
        raise ValueError("reference.same_B_catalog_required")
    if (
        len(scope["all16_recipe_ids"]) != 16
        or len(set(scope["all16_recipe_ids"])) != 16
    ):
        raise ValueError("reference.all16_eligibility_required")
    if scope["eligible_set_derivation_sha256"] != digest(scope["days"]) or scope[
        "eligible_set_manifest_sha256"
    ] != digest({date: d["eligible"] for date, d in scope["days"].items()}):
        raise ValueError("reference.same_E_t_required")
    for date, day in scope["days"].items():
        day_fields = {
            "date",
            "eligible",
            "states",
            "reasons",
            "verified_count",
            "upper_bound",
            "quantity_state",
            "quarantine_manifest_sha256",
            "new_tilt_allowed",
            "required_M_valuation_cash_fees_still_required",
            "noncash_guard_manifest_sha256",
            "B_catalog_sha256",
            "synthetic_catalog_sha256",
            "eligible_set_derivation_sha256",
        } | binding_keys
        if set(day) != day_fields:
            raise ValueError("reference.day_schema_invalid")
        if (
            not strings(day["eligible"])
            or any(not strings(v) for v in day["reasons"].values())
            or set(day["reasons"]) != set(scope["universe"])
            or any(
                v
                not in {
                    "VERIFIED_USABLE",
                    "VERIFIED_INELIGIBLE",
                    "QUARANTINED",
                    "UNKNOWN",
                }
                for v in day["states"].values()
            )
        ):
            raise ValueError("reference.day_schema_invalid")
        if day["eligible_set_derivation_sha256"] != digest(
            {k: v for k, v in day.items() if k != "eligible_set_derivation_sha256"}
        ):
            raise ValueError("reference.same_E_t_required")
        eligible = sorted(
            s for s, state in day["states"].items() if state == "VERIFIED_USABLE"
        )
        if (
            set(day["states"]) != set(scope["universe"])
            or day["date"] != date
            or eligible != day["eligible"]
            or set(eligible) & (set(blocked) | set(unknown))
            or day["quarantine_manifest_sha256"] != scope["quarantine_manifest_sha256"]
            or day["noncash_guard_manifest_sha256"]
            != guard["noncash_guard_manifest_sha256"]
        ):
            raise ValueError("reference.same_E_t_required")
        if (
            day["quantity_state"] != "VERIFIED_GE50"
            or len(eligible) < 50
            or day["verified_count"] != len(eligible)
        ):
            raise ValueError(
                "reference.quantity_unknown_or_insufficient_no_QQQ_substitution"
            )
    union = sorted({s for day in scope["days"].values() for s in day["eligible"]})
    expected = {
        date: (scope["days"][date]["eligible"] if date in scope["days"] else union)
        for date in list(view["warmup"]) + list(view["train"])
    }
    if scope["numeric_symbols"] != expected or scope["complete"] is not True:
        raise ValueError("reference.numeric_scope_or_complete_mismatch")
    return scope


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
        or state["initialization_count"] != 1
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


def check_reference_packets(proofs, scope):
    actors = {
        "reference/CREF-F1-L020",
        "reference/CREF-F3-L020",
        "reference/MREF-F2-L020",
        "reference/MREF-F4-L020",
    }
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
    if not isinstance(proofs, dict) or set(proofs) != actors:
        raise ValueError("reference.separate_three_proofs_required")
    for actor, packet in proofs.items():
        fields = {
            "actor",
            "producer_kind",
            "registry_sha256",
            "noncash_guard_manifest_sha256",
            "zero_origin",
            "no_acquisition",
            "economic_no_read",
            "scope",
            "independently_verified",
            "real_runtime_proven",
            "runtime_consumable",
            "certifiable",
            "reference_proof_packet_sha256",
        }
        if (
            set(packet) != fields
            or packet["actor"] != actor
            or packet["producer_kind"] != "reference"
            or packet["real_runtime_proven"] is not False
            or packet["independently_verified"] is not False
            or packet["runtime_consumable"] is not False
            or packet["certifiable"] is not False
            or packet["registry_sha256"]
            != "f531d65a5ad54fc68a8be40bc25cbb3987d0aeedd4c2c345ed334b1599445c48"
            or packet["noncash_guard_manifest_sha256"]
            != scope["guard"]["noncash_guard_manifest_sha256"]
            or packet["reference_proof_packet_sha256"]
            != digest(
                {
                    k: v
                    for k, v in packet.items()
                    if k != "reference_proof_packet_sha256"
                }
            )
        ):
            raise ValueError("reference.separate_proof_packet_mismatch")
        origin = packet["zero_origin"]
        no_buy = packet["no_acquisition"]
        no_read = packet["economic_no_read"]
        zero_state(origin["initial_state"], scope, initial=True)
        if (
            origin["actor"] != actor
            or no_buy["actor"] != actor
            or no_read["actor"] != actor
            or set(no_buy["routes"]) != routes
            or set(no_read["reads"]) != consumers
        ):
            raise ValueError("reference.separate_routes_and_consumers_required")
        for doc, key in [
            (origin, "zero_origin_receipt_sha256"),
            (no_buy, "no_acquisition_receipt_sha256"),
            (no_read, "economic_no_read_receipt_sha256"),
        ]:
            if doc[key] != digest({k: v for k, v in doc.items() if k != key}):
                raise ValueError("reference.proof_receipt_identity_invalid")
        if (
            no_buy["zero_origin_receipt_sha256"] != origin["zero_origin_receipt_sha256"]
            or no_read["zero_origin_receipt_sha256"]
            != origin["zero_origin_receipt_sha256"]
            or no_read["no_acquisition_receipt_sha256"]
            != no_buy["no_acquisition_receipt_sha256"]
        ):
            raise ValueError("reference.proof_origin_link_invalid")
        for route, receipt in no_buy["routes"].items():
            if (
                receipt["actor"] != actor
                or receipt["route"] != route
                or receipt["zero_origin_receipt_sha256"]
                != origin["zero_origin_receipt_sha256"]
                or receipt["noncash_guard_manifest_sha256"]
                != scope["guard"]["noncash_guard_manifest_sha256"]
                or receipt["route_receipt_sha256"]
                != digest(
                    {k: v for k, v in receipt.items() if k != "route_receipt_sha256"}
                )
            ):
                raise ValueError("reference.acquisition_induction_receipt_mismatch")
            zero_state(receipt["before"], scope)
            zero_state(receipt["after"], scope)
        for role, read in no_read["reads"].items():
            inner = read["numeric_receipt"]
            if (
                read["actor"] != actor
                or read["consumer"] != role
                or not inner["symbols"]
                or inner["input_kind"] != "numeric_values"
                or inner["read_boundary_exercised"] is not True
                or set(inner["symbols"])
                & (
                    set(scope["guard"]["B"])
                    | set(scope["guard"]["unknown"])
                    | set(scope["guard"]["children"])
                )
                or not set(inner["symbols"]).issubset(set(scope["universe"]) | {"QQQ"})
            ):
                raise ValueError("reference.numeric_boundary_proof_required")


def check_panel(scope, rows, dates):
    if [r["date"] for r in rows] != list(dates):
        raise ValueError("reference.only_complete_train_warmup_visible")
    for row in rows:
        names = scope["numeric_symbols"][row["date"]]
        if set(row["prices"]) != set(names):
            raise ValueError("reference.guarded_or_unknown_numeric_input")
        if any(
            type(row["prices"][s]) not in (int, float)
            or not math.isfinite(row["prices"][s])
            or row["prices"][s] <= 0
            for s in names
        ):
            raise ValueError("reference.numeric_input_invalid")
