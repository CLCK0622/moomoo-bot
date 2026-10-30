"""Versioned v10 consumer overlay. No event repair, data fetch or ledger writer.

The external acceptance authenticates the draft's scoped rules without changing
its pending bytes. There is no accepted reconciliation checkpoint in this input.
Unknown inverse-price ancestry therefore covers the declared span, including
prior anchors; a calendar-date cutoff cannot establish recovery.
"""

import json
import csv
import io
from copy import deepcopy

from .contract import result, sha256, unavailable
from .conventions import FIXTURES
from .fees import iso_date
from .fees import finite


BINDINGS = {
    "EVO883-v10-engineering-disposition-draft-v1.json": "0f9811006c529051f2941bdc69fc916be8209e5e822acbd23464abd2109fbdd1",
    "EVO883-EVO893-v10-final-acceptance-v1.json": "43e14aebacc3cb4a0f775e1b4d35ebd45bc536aa260470e0b673bf7cf7784f0d",
}
INHERITED = {
    "B": "prior Barnes33 and inferred Randgold6; prior79 not replaced by new40",
    "COR": "prior CoreSite33 security-line conflict",
}


def sources():
    raw = {n: (FIXTURES / "evo898" / n).read_bytes() for n in BINDINGS}
    if any(sha256(b) != BINDINGS[n] for n, b in raw.items()):
        raise ValueError("data.v10_binding_mismatch")
    doc, acceptance = [json.loads(raw[n]) for n in BINDINGS]
    if acceptance["accepted_bindings"][0]["sha256"] != BINDINGS[next(iter(BINDINGS))]:
        raise ValueError("data.v10_acceptance_binding_mismatch")
    return doc, acceptance


def field_rules(doc):
    fields = {
        field: rule["id"]
        for rule in doc["propagation_rules"]
        for field in rule["outputs"]
    }
    # Explicit consumer names for the windows/interval/state required by the
    # rule prose, in addition to every verbatim machine output field.
    fields.update(
        history_window="P_FEATURES_AND_LABELS",
        dollar_ADV="P_FEATURES_AND_LABELS",
        label_interval="P_FEATURES_AND_LABELS",
        rank_calibration="P_ELIGIBILITY_AND_GAIN",
        cash_holdings="P_INTEGER_CASH",
        cross_fold_state="P_STATE_CONTINUITY",
    )
    return fields


def s1_input_receipt():
    """Adopt the authenticated field receipt, never manufacture price rows.

    Actual values still require the byte-matching source CSV at the data reader.
    Receipt adoption does not authenticate a caller's arbitrary numeric value.
    """
    doc, _ = sources()
    return dict(
        schema="EVO898.S1-input/v1",
        input_version="v1",
        field_receipt_adopted=True,
        **deepcopy(doc["S1_field_update"]),
        acceptance_sha256=list(BINDINGS.values())[1],
        price_values=None,
        reason="data.S1_field_receipt_only_source_CSV_required_for_values",
    )


def s1_scope(item):
    s1 = s1_input_receipt()
    return (
        item.get("symbol") == s1["symbol"]
        and item.get("field") == s1["field"]
        and s1["from_date"] <= iso_date(item["date"]) <= s1["to_date"]
        and item.get("source_csv_sha256") == s1["csv_sha256"]
        and item.get("price_basis") == "NONE"
    )


def read_s1_raw_open(raw):
    """Offline price reader; only the exact accepted source CSV is admissible.

    Receipt lookup alone does not validate numeric data. Callers must supply
    its original bytes, not a separately constructed row/hash assertion.
    """
    s1 = s1_input_receipt()
    if sha256(raw) != s1["csv_sha256"]:
        raise ValueError("data.S1_CSV_identity_mismatch")
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
    values = []
    for row in rows:
        day = iso_date((row.get("date") or row.get("time_key") or "")[:10])
        value = float(row["open_none"])
        page = int(row["page_no"])
        if not 1 <= page <= 4 or row["page_sha256"] != s1["page_SHA"][page - 1]:
            raise ValueError("data.S1_page_binding_mismatch")
        if not finite(value) or value <= 0:
            raise ValueError("data.S1_raw_open_invalid")
        values.append(dict(symbol="BRK.B", date=day, raw_open=value))
    dates = [row["date"] for row in values]
    if (
        len(values) != s1["rows"]
        or dates != sorted(set(dates))
        or dates[0] != s1["from_date"]
        or dates[-1] != s1["to_date"]
    ):
        raise ValueError("data.S1_range_mismatch")
    return dict(receipt=s1, rows=values)


def event_receipts(doc):
    """Keep the full evidence, including the original date, kind and amounts."""
    return [
        dict(
            evidence=deepcopy(row),
            event_key=row["event_key"],
            action=row["action"],
            analytical_D=None,
            receivable=None,
            available_cash=None,
            reason="data.v10_event_binding_unresolved",
            reasons=deepcopy(row["quarantine_reasons"]),
        )
        for row in doc["event_decisions"]
    ]


def normalize_dependencies(request):
    """Flatten supported consumer scopes before evaluating any formal value.

    Node identities remain global across folds/states, so duplicate or
    conflicting declarations cannot silently replace earlier ancestry. Unknown
    lineage containers fail closed instead of looking like an empty graph.
    """
    graph, panels = [], []
    from .lineage_schema import validate_consumer

    def isolation_scope(value):
        # Consumer extension for frozen v3 only. These are real graph nodes,
        # not opaque hashes or a metadata exemption from ancestry inspection.
        from datetime import datetime

        from .contract import digest, is_sha
        from .conventions import load_conventions

        policy = load_conventions()
        binding = policy.binding
        if (
            not isinstance(value, dict)
            or set(value) != set(binding) | {"request", "quarantine_manifest_sha256"}
            or any(value.get(k) != v for k, v in binding.items())
            or binding["conventions_version"] != "v3.0.0"
            or not isinstance(value["request"], dict)
        ):
            raise ValueError("data.v3_isolation_schema_invalid")
        declaration = value["request"]
        required = {"role", "records", "mode", "sealed_at", "first_performance_at"}
        if (
            not required.issubset(declaration)
            or set(declaration) - required - {"signal_close", "noncash_guard_manifest"}
            or declaration["role"]
            not in {
                "train_solo_probes",
                "train_calibration",
                "train_meta",
                "external_reference_roles",
                "test_meta",
                "authorized_forward",
            }
            or declaration["mode"] not in {"history", "forward"}
            or not isinstance(declaration["records"], list)
        ):
            raise ValueError("data.v3_isolation_schema_invalid")

        def instant(raw):
            if not isinstance(raw, str):
                raise ValueError("data.v3_isolation_schema_invalid")
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("data.v3_isolation_schema_invalid")
            return parsed

        sealed = instant(declaration["sealed_at"])
        if sealed >= instant(declaration["first_performance_at"]):
            raise ValueError("data.v3_isolation_not_preperformance")
        if "signal_close" in declaration:
            instant(declaration["signal_close"])
        if declaration["mode"] == "forward" and "signal_close" not in declaration:
            raise ValueError("data.v3_isolation_schema_invalid")
        guarded = set()
        if "noncash_guard_manifest" in declaration:
            from .noncash_v3 import checked_guard

            guard = checked_guard(declaration["noncash_guard_manifest"], policy)
            guarded = set(guard["B"]) | set(guard["unknown"])
        fields = {
            "symbol",
            "field_role",
            "from_date",
            "to_date_or_null_with_reason",
            "reason",
            "source_sha256",
            "dependency_lineage",
            "evidence_version",
            "state",
            "gates_by_date",
            "received_at",
        }
        gate_fields = {
            "history_dates",
            "raw_price",
            "dollar_adv",
            "units_verified",
            "security_line_verified",
            "recipe_inputs_verified",
        }
        nodes = []
        for row in declaration["records"]:
            if (
                not isinstance(row, dict)
                or set(row) != fields
                or row["symbol"] not in policy.profile["universe"]
                or row["field_role"] != "selection"
                or row["state"]
                not in {
                    "VERIFIED_USABLE",
                    "VERIFIED_INELIGIBLE",
                    "QUARANTINED",
                    "UNKNOWN",
                }
                or any(
                    not isinstance(row[k], str) or not row[k]
                    for k in ("reason", "evidence_version")
                )
                or not is_sha(row["source_sha256"])
                or not isinstance(row["dependency_lineage"], list)
                or not row["dependency_lineage"]
                or not isinstance(row["gates_by_date"], dict)
            ):
                raise ValueError("data.v3_isolation_schema_invalid")
            start = iso_date(row["from_date"])
            end = row["to_date_or_null_with_reason"]
            if end is not None and iso_date(end) < start:
                raise ValueError("data.v3_isolation_schema_invalid")
            received = instant(row["received_at"])
            if received > sealed or (
                declaration["mode"] == "forward"
                and received > instant(declaration["signal_close"])
            ):
                raise ValueError("data.v3_isolation_information_cutoff")
            if row["symbol"] in guarded and row["gates_by_date"]:
                raise ValueError("B.guarded_numeric_evidence_forbidden")
            for date, gates in row["gates_by_date"].items():
                if (
                    not isinstance(gates, dict)
                    or set(gates) != gate_fields
                    or not start <= iso_date(date)
                    or (end is not None and date > end)
                    or not isinstance(gates["history_dates"], list)
                    or any(not isinstance(d, str) for d in gates["history_dates"])
                    or any(
                        gates[k] is not None and not finite(gates[k])
                        for k in ("raw_price", "dollar_adv")
                    )
                    or any(
                        gates[k] is not None and type(gates[k]) is not bool
                        for k in (
                            "units_verified",
                            "security_line_verified",
                            "recipe_inputs_verified",
                        )
                    )
                ):
                    raise ValueError("data.v3_isolation_schema_invalid")
                for date_value in gates["history_dates"]:
                    iso_date(date_value)
            for node in row["dependency_lineage"]:
                if (
                    not isinstance(node, dict)
                    or not {"id", "field", "parents"}.issubset(node)
                    or set(node)
                    - {
                        "id",
                        "field",
                        "parents",
                        "symbol",
                        "date",
                        "event_keys",
                        "value",
                        "source_sha256",
                        "reconciliation_checkpoint",
                    }
                    or any(
                        not isinstance(node[k], str) or not node[k]
                        for k in ("id", "field")
                    )
                    or not isinstance(node["parents"], list)
                    or any(not isinstance(k, str) or not k for k in node["parents"])
                    or ("symbol" in node and not isinstance(node["symbol"], str))
                    or (
                        "event_keys" in node
                        and (
                            not isinstance(node["event_keys"], list)
                            or any(not isinstance(k, str) for k in node["event_keys"])
                        )
                    )
                    or (
                        "value" in node
                        and node["value"] is not None
                        and not finite(node["value"])
                    )
                    or ("source_sha256" in node and not is_sha(node["source_sha256"]))
                    or (
                        "reconciliation_checkpoint" in node
                        and not isinstance(node["reconciliation_checkpoint"], dict)
                    )
                ):
                    raise ValueError("data.v3_isolation_schema_invalid")
                if "date" in node:
                    iso_date(node["date"])
                from .lineage_schema import NODE

                validate_consumer(
                    {"dependency_nodes": [node]},
                    schema={
                        "dependency_nodes": ("list", dict(NODE, source_sha256="string"))
                    },
                )
                nodes.append(deepcopy(node))
        if value["quarantine_manifest_sha256"] != digest(
            {"request": declaration, **binding}
        ):
            raise ValueError("data.v3_isolation_identity_mismatch")
        # _project below checks these together with all original declarations:
        # duplicate IDs, missing parents, cycles and inherited B/COR ancestry.
        return nodes

    from .lineage_schema import consumer_schema_v3

    # Only this registered root field is delegated to the strict v3 adapter.
    # Every remaining consumer byte still traverses the closed B8 schema.
    extra_symbols = {"VSNT"}
    if "noncash_guard_manifest" in request:
        from .noncash_v3 import checked_guard

        extra_symbols.update(
            checked_guard(request["noncash_guard_manifest"])["children"]
        )
    validate_consumer(
        {
            k: v
            for k, v in request.items()
            if k not in {"isolation_manifest", "noncash_guard_manifest"}
        },
        schema=consumer_schema_v3(extra_symbols),
        securities=extra_symbols,
    )

    pending = [request]
    while pending:
        scope = pending.pop()
        if not isinstance(scope, dict):
            raise ValueError("data.v10_lineage_scope_invalid")
        for key, value in scope.items():
            if key == "isolation_manifest":
                if scope is not request:
                    raise ValueError("data.v3_isolation_location_invalid")
                graph.extend(isolation_scope(value))
            elif key in {"dependency_nodes", "panel_inputs", "inputs"}:
                if not isinstance(value, list) or any(
                    not isinstance(item, dict) for item in value
                ):
                    raise ValueError("data.v10_lineage_list_required")
                (graph if key == "dependency_nodes" else panels).extend(deepcopy(value))
            elif key in {"folds", "events"}:
                if not isinstance(value, list):
                    raise ValueError("data.v10_lineage_list_required")
                pending.extend(reversed(value))
            elif key in {"input_state", "output_state", "event"}:
                if value is not None:
                    pending.append(value)
            elif key == "inventory":
                if not isinstance(value, dict):
                    raise ValueError("data.v10_inventory_lineage_invalid")
                panels.extend(
                    dict(symbol=symbol, field="inventory", parents=[])
                    for symbol, quantity in value.items()
                    if quantity and symbol in INHERITED
                )
        # An event is evidence even when the current inventory has been sold.
        if scope.get("symbol") in INHERITED:
            panels.append(dict(symbol=scope["symbol"], field="event", parents=[]))
    return dict(dependency_nodes=graph, inputs=panels)


def _project(request, doc):
    """Resolve an explicit dependency DAG, independent of node/calendar order.

    Nodes carry id, field, parents, and optionally symbol/date/event_keys. A
    graph edge is an actual consumer dependency (anchor, lookback, full label
    entitlement interval, calibration/ranking or carried state), not a fixed
    ex-day window. Missing edges/parents and cycles refuse the readout. A leaf
    with unknown ancestry cannot assert independence merely by omitting B/COR.
    """
    rows = deepcopy(request.get("dependency_nodes", []))
    for i, item in enumerate(request.get("inputs", [])):
        rows.append(
            dict(item, id=item.get("id", f"panel/{i}"), parents=item.get("parents", []))
        )
    by_id, visiting, done = {}, set(), {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise ValueError("data.v10_dependency_identity_missing")
        if row["id"] in by_id:
            raise ValueError("data.v10_duplicate_dependency_identity")
        if not isinstance(row.get("parents"), list) or any(
            not isinstance(p, str) for p in row["parents"]
        ):
            raise ValueError("data.v10_ancestry_missing")
        if not isinstance(row.get("field"), str):
            raise ValueError("data.v10_field_missing")
        by_id[row["id"]] = row
    events = {r["event_key"]: r for r in doc["event_decisions"]}
    known_events = set(events) | {f"inherited:{s}" for s in INHERITED}

    def project(key):
        row = by_id[key]
        lineage = row.get("event_keys", [])
        if not isinstance(lineage, list) or any(k not in known_events for k in lineage):
            raise ValueError("data.v10_unknown_event_lineage")
        lineage = set(lineage)
        reasons = []
        symbol = row.get("symbol")
        if symbol in INHERITED:
            lineage.add(f"inherited:{symbol}")
            lineage.update(k for k in events if k.startswith(symbol + "|"))
        if lineage:
            reasons.append("data.v10_unresolved_event_or_adjustment_anchor")
        for parent in row["parents"]:
            projected = done[parent]
            lineage.update(projected["event_keys"])
            reasons.extend(projected["reasons"])
        if not row["parents"] and not symbol and not lineage:
            reasons.append("data.v10_ancestry_missing")
        if row.get("reconciliation_checkpoint") is not None:
            reasons.append("data.v10_checkpoint_not_supported_by_bound_receipt")
        done[key] = dict(
            id=key,
            field=row["field"],
            value=None if reasons else row.get("value"),
            reasons=sorted(set(reasons)),
            event_keys=sorted(lineage),
            submitted=deepcopy(row),
        )

    # An iterative DFS supports a full daily carried-state chain without
    # depending on the interpreter's recursion limit (3,191 dates here).
    for key in by_id:
        stack = [(key, False)]
        while stack:
            current, expanded = stack.pop()
            if current in done:
                continue
            if current not in by_id:
                raise ValueError("data.v10_dependency_parent_missing")
            if expanded:
                project(current)
                visiting.remove(current)
                continue
            if current in visiting:
                raise ValueError("data.v10_dependency_cycle")
            visiting.add(current)
            stack.append((current, True))
            stack.extend(
                (parent, False) for parent in reversed(by_id[current]["parents"])
            )
    return [done[row["id"]] for row in rows]


def quarantine_check(request):
    """Read-only business boundary; all 40 records and 15 relations survive.

    readouts is the conservative formal projection when any requested consumer
    is indeterminate. submitted nodes remain evidence, never accepted values.
    No supplied checkpoint is accepted by this v1 input.
    """
    reasons, projected, doc = [], None, None
    try:
        doc, _ = sources()
        projected = _project(normalize_dependencies(request), doc)
        if any(row["reasons"] for row in projected):
            reasons.append("data.v10_quarantined_dependency")
        if request.get("skip_invalid_folds") or request.get("valid_only"):
            reasons.append("wf.invalid_fold_may_not_be_skipped")
        if request.get("restart_capital"):
            reasons.append("wf.capital_restart_forbidden")
        if request.get("replacement_symbols") or request.get("truncate_sample"):
            reasons.append("data.panel_or_sample_change_requires_design_version")
        if "panel_symbols" in request:
            from .conventions import load_conventions

            expected = load_conventions().profile["universe"]
            if request["panel_symbols"] != expected:
                reasons.append("data.v10_frozen_panel_required")
    except (KeyError, TypeError, ValueError, OSError, AttributeError) as exc:
        reasons.append(
            str(exc) if isinstance(exc, ValueError) else "data.v10_input_invalid"
        )
    rules = field_rules(doc) if doc else {}
    reason = reasons[0] if reasons else "data.v10_no_formal_calculation_performed"
    return result(
        "event_quarantine",
        {"request": request, "bindings": BINDINGS},
        reasons=reasons,
        metrics={
            "events": event_receipts(doc) if doc else None,
            "unmatched_relations": deepcopy(doc["unmatched_declaration_relations"])
            if doc
            else None,
            "inherited_constraints": INHERITED,
            "projected_nodes": projected,
            "readouts": {field: None for field in rules},
            "strict_eligible_count": None,
            "eligibility_state": "UNKNOWN",
            "optional_new_risk_allowed": False,
            "automatic_recovery": False,
            "S1": s1_input_receipt() if doc else None,
        },
        availability={field: unavailable(reason) for field in rules},
        artifacts={"bindings": BINDINGS, "field_rule_ids": rules},
    )
