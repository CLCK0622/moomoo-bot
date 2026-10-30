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

    validate_consumer(request)

    pending = [request]
    while pending:
        scope = pending.pop()
        if not isinstance(scope, dict):
            raise ValueError("data.v10_lineage_scope_invalid")
        for key, value in scope.items():
            if key in {"dependency_nodes", "panel_inputs", "inputs"}:
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
