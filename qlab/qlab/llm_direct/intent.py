"""Versioned forward-reference proposal; offline accounting is an explicit seam."""

from __future__ import annotations

import json

from qlab.shadow15k.ledger import timestamp

from .contract import ARM, PROFILE_SHA, VERSION, bindings, canonical, digest
from .runtime import live


def envelope(runtime, group_id, *, decision_ts):
    runtime.lifecycle.require_active()
    events = runtime.archive.events()
    live(events)
    saved = next((e["body"] for e in events if e["id"] == "intent:" + group_id), None)
    if saved:
        return json.loads(runtime.archive.get(saved["envelope_sha256"]))
    comparison = next(
        (e["body"] for e in events if e["id"] == "comparison:" + group_id), None
    )
    if comparison is None:
        raise ValueError("intent.final_comparison_missing")
    report = json.loads(runtime.archive.get(comparison["report_sha256"]))
    if not report["passed"]:
        raise ValueError("intent.group_failed")
    rows = [
        e["body"]
        for e in events
        if e["body"].get("kind") == "generation" and e["body"]["group_id"] == group_id
    ]
    first = next(r for r in rows if r["index"] == 1)
    decision = json.loads(runtime.archive.get(first["decision_sha256"]))
    if (
        not timestamp(first["end"])
        <= timestamp(decision_ts)
        <= timestamp(first["reference_open_utc"])
    ):
        raise ValueError("intent.creation_after_reference_execution")
    plan = report["results"][0]
    fields = dict(
        arm_version=VERSION,
        scenario="canonical_x2",
        decision_session=decision["decision_session"],
        input_sha256=decision["input_sha256"],
        prompt_sha256=bindings()["prompt"]["sha256"],
        model_binding_sha256=digest(bindings()["model_binding"]),
        canonical_output_sha256=first["raw_output_sha256"],
        plan_sha256=digest(plan["signature"]),
    )
    iid = "llm896:" + digest(fields)
    orders = []
    for o in plan["orders"]:
        oid = digest(
            dict(
                intent_id=iid,
                symbol=o["symbol"],
                side=o["side"],
                exchange_trade_date=o["exchange_trade_date"],
                DAY="DAY",
            )
        )
        orders.append(
            dict(
                order_id=oid,
                symbol=o["symbol"],
                side=o["side"],
                planned_qty=o["planned_qty"],
                trade_date=o["exchange_trade_date"],
                protective=o["protective"],
            )
        )
    bundle = dict(
        profile_sha256=PROFILE_SHA,
        execution_snapshot_sha256=report["execution_snapshot_sha256"],
        canonical_output_sha256=first["raw_output_sha256"],
        comparison_sha256=comparison["report_sha256"],
        inventory=decision["x2_control_state"],
        M=plan["M"],
        P=plan["P"],
    )
    value = dict(
        schema="llm_direct.forward_reference/v1",
        mode="forward_reference",
        candidate_id=ARM,
        arm_version=VERSION,
        namespaces={s: "evo881.llm_direct." + VERSION + "." + s for s in ("x1", "x2")},
        intent_digest_fields=fields,
        kernel=dict(
            intent_id=iid,
            decision_ts=decision_ts,
            input_hash=digest(bundle),
            orders=orders,
        ),
        provenance=bundle,
        status="READY" if orders else "NOOP",
        execution_verified=False,
        runtime_authorized=False,
        synthetic_only=True,
    )
    h = runtime.archive.put(canonical(value))
    runtime.archive.append(
        "intent:" + group_id,
        dict(kind="intent_envelope", envelope_sha256=h, blob_sha256s=[h]),
        validate=live,
    )
    return value


def register_synthetic(value, ledger, *, runtime):
    """Never change the strict offline kernel's namespace or grant forward access."""
    runtime.lifecycle.require_active()
    events = runtime.archive.events()
    live(events)
    h = digest(value)
    if not any(
        e["body"].get("kind") == "intent_envelope" and e["body"]["envelope_sha256"] == h
        for e in events
    ):
        raise ValueError("intent.archived_envelope_mismatch")
    if (
        value.get("schema") != "llm_direct.forward_reference/v1"
        or value.get("synthetic_only") is not True
        or value.get("runtime_authorized") is not False
        or value.get("candidate_id") != ARM
    ):
        raise ValueError("intent.versioned_synthetic_envelope_required")
    g = ledger.genesis
    if (
        g["candidate_id"] != ARM
        or g["version"] != VERSION
        or g["mode"] != "offline_synthetic"
        or g["price_basis"] != "reference"
    ):
        raise ValueError("intent.isolated_arm_ledger_required")
    if value["status"] == "NOOP":
        return dict(
            status="NOOP",
            intent_id=value["kernel"]["intent_id"],
            execution_verified=False,
        )
    return ledger.register_intent(value["kernel"])
