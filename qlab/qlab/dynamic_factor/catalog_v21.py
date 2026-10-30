"""One source-bound protective derivation shared by every v3 producer.

Static registration is not a runtime B release. Snapshot search descriptions
and null B_membership cannot authorize numeric consumption or erase UNKNOWN.
"""

import csv
import io
import json

from .contract import digest, sha256
from .conventions import FIXTURES, load_conventions

BINDINGS = {
    "EVO893-B-noncash-catalog-v21.csv": "5040272302cf675b99e0b954669dde72bfc6431f47fb9d835f3acb6f408d1a13",
    "EVO893-B-CMI-guard-v21.json": "08ed088405cbefa9bd24e8cb0756d5d10a62b105153b9cfba02af504d9371f77",
    "EVO883-v21-final-receipt.json": "b8b930396e7caf42ad8bde0f2f7ff190c40f36fd4c4686964a39154926f6644a",
}
REGISTERED_AT = "2026-10-30T11:51:14Z"


def derive(policy=None):
    p = policy or load_conventions()
    raw = {name: (FIXTURES / "catalog-v21" / name).read_bytes() for name in BINDINGS}
    if any(sha256(raw[name]) != expected for name, expected in BINDINGS.items()):
        raise ValueError("B.v21_registered_bytes_mismatch")
    receipt = json.loads(raw["EVO883-v21-final-receipt.json"])
    field = json.loads(raw["EVO893-B-CMI-guard-v21.json"])
    rows = list(
        csv.DictReader(io.StringIO(raw["EVO893-B-noncash-catalog-v21.csv"].decode()))
    )
    if len(rows) != 64 or {r["symbol"] for r in rows} != set(p.profile["universe"]):
        raise ValueError("B.full_U64_catalog_required")
    by_symbol = {r["symbol"]: r for r in rows}
    entries, evidence = [], []
    for symbol in p.profile["universe"]:
        row = by_symbol[symbol]
        fact = row["fact_state"].split("（", 1)[0]
        candidate = row["candidate_guard"].split("（", 1)[0]
        if fact not in {"UNKNOWN", "未闭合"} or candidate not in {
            "B 防护",
            "guard_pending_review=true",
            "未触发",
        }:
            raise ValueError("B.v21_state_or_candidate_column_invalid")
        pending = candidate == "guard_pending_review=true"
        if pending and (
            symbol != field["symbol"]
            or field["guard_pending_review"] is not True
            or field["fact_state"] != "UNKNOWN"
        ):
            raise ValueError("B.v21_candidate_field_binding_mismatch")
        entries.append(
            dict(
                symbol=symbol,
                status="UNRESOLVED" if fact == "未闭合" else "UNKNOWN",
                children=[],
                evidence_sha256=digest(dict(bindings=BINDINGS, raw_row=row)),
                received_at=REGISTERED_AT,
                credible_event_evidence=candidate != "未触发",
                event_or_candidate_id=row["event_id"]
                or (field["source"]["accession"] if pending else None),
                guard_pending_review=pending,
                fact_state="UNRESOLVED" if fact == "未闭合" else "UNKNOWN",
                B_membership=None,
            )
        )
        evidence.append(row)
    catalog = dict(
        universe=p.profile["universe"],
        calendar_sha256=digest(p.calendar),
        entries=entries,
    )
    payload = dict(
        catalog=catalog,
        raw_declarations=evidence,
        field_evidence=field,
        source_bindings=BINDINGS,
        registration_receipt_sha256=BINDINGS["EVO883-v21-final-receipt.json"],
        fact_counts=dict(
            known_unclosed=sum(e["fact_state"] == "UNRESOLVED" for e in entries),
            UNKNOWN=sum(e["fact_state"] == "UNKNOWN" for e in entries),
        ),
        B_catalog_release_sha256=None,
        runtime_consumable=False,
        certifiable=False,
        general_unknown_is_verified_complement=False,
        registration_only=receipt["status"]
        == "accepted_static_registration_not_runtime_B_release",
    )
    if (
        payload["fact_counts"] != {"known_unclosed": 3, "UNKNOWN": 61}
        or not payload["registration_only"]
    ):
        raise ValueError("B.v21_registration_not_runtime_release")
    return dict(payload, B_derivation_sha256=digest(payload))


def guard_request(*, sealed_at, first_performance_at, policy=None):
    derived = derive(policy)
    return dict(
        catalog=derived["catalog"],
        mode="history",
        sealed_at=sealed_at,
        first_performance_at=first_performance_at,
        synthetic=False,
        catalog_registration=dict(
            source_bindings=BINDINGS, B_derivation_sha256=derived["B_derivation_sha256"]
        ),
    )
