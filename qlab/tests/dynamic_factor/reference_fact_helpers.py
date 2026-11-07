"""Counterfactual four-file prices only; never a real market/source receipt."""

from copy import deepcopy

from qlab.dynamic_factor.contract import canonical, digest, sha256
from qlab.dynamic_factor.execution_receipts.input_data import IDENTITIES
from qlab.dynamic_factor.reference_boundary import (
    prepare_execution_inputs,
    read_execution_inputs,
)
from qlab.dynamic_factor.execution_receipts.input_facts import read_facts
from qlab.dynamic_factor.reference_profile_v301 import solo_profile
from qlab.dynamic_factor.reference_definition_v301 import member_definition
from v3_reference_helpers import protocol_scope


def four_file_program(root, original):
    p = deepcopy(original)
    history = p["initial"]["history"]
    identity = history["scope"]
    profile = solo_profile(
        member_definition(
            identity["member_id"], execution_role=identity["execution_role"]
        )
    )
    dates = [
        e["arguments"]["evidence"]["session"]
        for e in p["operations"]
        if e["operation"] == "close"
    ]
    scope = protocol_scope(dates, [], verified=49)
    history["guard"] = deepcopy(scope["guard"])
    manifest = dict(
        schema="EVO884.RestrictedExecutionInputManifest/v1",
        book_id=history["book_id"],
        run_id=p["initial"]["run_id"],
        member_id=identity["member_id"],
        scope_sha256=scope["scope_sha256"],
        profile_sha256=profile["profile_sha256"],
        inputs={},
    )
    for role in ("raw", "rights", "adv", "cash"):
        values = (
            dict(raw_open="100", raw_close="100")
            if role == "raw"
            else dict(adv20_dollar="100000000")
            if role == "adv"
            else {role + "_events": []}
        )
        data = dict(
            schema="EVO884.RestrictedExecutionRows/v1",
            role=role,
            **{k: manifest[k] for k in IDENTITIES},
            records=[
                dict(
                    date=d,
                    symbol="QQQ",
                    available_at=d + "T00:00:00Z",
                    values=deepcopy(values),
                )
                for d in dates
            ],
        )
        raw = canonical(data)
        (root / (role + ".json")).write_bytes(raw)
        manifest["inputs"][role] = dict(
            file=role + ".json",
            sha256=sha256(raw),
            source_receipt_sha256=digest([role, "UNAUTHENTICATED SYNTHETIC SOURCE"]),
            requested_dates=dates,
            requested_consumer="holdings_valuation",
            symbols=["QQQ"],
        )
    operations = []
    for e in p["operations"]:
        a = e["arguments"]
        if e["operation"] == "startup_open":
            a["source_sha256"] = manifest["inputs"]["raw"]["sha256"]
            a["expected_input_sha256"] = digest(
                {k: a[k] for k in ("timestamp", "raw_open", "source_sha256")}
            )
        elif e["operation"] in {"model_open", "close"}:
            a["evidence"]["source_sha256"] = manifest["inputs"]["raw"]["sha256"]
            a["expected_evidence_sha256"] = digest(a["evidence"])
        elif e["operation"] == "lock_projection":
            inputs = a["inputs"]
            day = scope["days"][inputs["close_state"]["signal_close_session"]]
            inputs["eligibility"].update(
                E_t=day["eligible"],
                named_count=49,
                states=day["states"],
                B=scope["guard"]["B"],
            )
            a["expected_input_sha256"] = digest(inputs)
        operations.append(e)
        if e["operation"] == "lock_projection":
            d = a["inputs"]["execution_open"]["session"]
            opening = dict(
                session=d,
                asof=d + "T14:30:00Z",
                prices={"QQQ": "100"},
                source_sha256=manifest["inputs"]["raw"]["sha256"],
                price_kind="verified_tradable_raw_open",
                origins={},
            )
            operations.append(
                dict(
                    operation="model_open",
                    arguments=dict(
                        evidence=opening, expected_evidence_sha256=digest(opening)
                    ),
                )
            )
    p["operations"] = operations
    preparation = prepare_execution_inputs(
        profile,
        scope,
        manifest,
        book_id=manifest["book_id"],
        run_id=manifest["run_id"],
        expected_manifest_sha256=digest(manifest),
        expected_scope_sha256=scope["scope_sha256"],
        expected_profile_sha256=profile["profile_sha256"],
    )
    read = read_execution_inputs(root, preparation)
    return p, read, read_facts(read)[0]
