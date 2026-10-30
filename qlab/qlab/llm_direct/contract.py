"""Immutable external approval and strict, lossless JSON contracts."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import date
from pathlib import Path

from qlab.shadow15k.fees import money

FIXTURES = Path(__file__).parent / "fixtures"
VERSION = "LLMCLI-v0.1.2"
ARM = "EVO896_LLMCLI"
BINDINGS = {
    "EVO896-prereg-LLMCLI-v0.1.2.json": "e9e089b17e15b86d7bd96e0e8f69cced47759c181b1d2e3bb220743225c71b2c",
    "EVO896-common-profile-v0.1.2.json": "1736b460538b2b18142877e1729ed839ba83a4f99282c2461de07f2711277e8d",
    "EVO896-v012-design-acceptance-v1.json": "72859801e8c47c4ebd0553854e8ed3d7e518be5bd21aaaa97c1e6866c9e4f279",
    "EVO896-v012-acceptance-ruling-v3.txt": "c05b8419d8c2d10f6e911e847dd9548af62624171cadde36dd20ba12a53c79de",
    "EVO896-v012-design-acceptance-receipt.json": "577e649f4a039d6e14ab9dea047732d460ee7ef0a301ae2ec86aaaa59d432813",
    "EVO896-v012-acceptance-review-v3.zip": "d7488c24facc8f128dd0847fab4a802720297f106666f7e923cec5f0e42cc843",
    "EVO896-review-packet-LLMCLI-v0.1.2.zip": "ac9565743c1b3c5449d014995df48e5442fda5184a3ba43d53ab28b21f2b780d",
}
PROFILE_SHA = BINDINGS["EVO896-common-profile-v0.1.2.json"]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    def check(v):
        if isinstance(v, str):
            if unicodedata.normalize("NFC", v) != v:
                raise ValueError("json.non_NFC")
        elif isinstance(v, dict):
            for k, x in v.items():
                if not isinstance(k, str):
                    raise ValueError("json.string_keys_required")
                check(k)
                check(x)
        elif isinstance(v, list):
            for x in v:
                check(x)
        elif v is not None and type(v) not in (int, bool):
            raise ValueError("json.decimal_strings_required")

    check(value)
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def digest(value):
    return sha(canonical(value))


def strict_json(raw):
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out:
                raise ValueError("json.duplicate_key")
            out[k] = v
        return out

    def invalid(value):
        raise ValueError("json.nonfinite:" + value)

    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    except (TypeError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("json.invalid") from exc
    if not isinstance(value, dict):
        raise ValueError("json.object_required")
    canonical(value)
    return value


def bindings():
    for name, expected in BINDINGS.items():
        if sha((FIXTURES / name).read_bytes()) != expected:
            raise ValueError("binding.sha_mismatch:" + name)
    main = json.loads((FIXTURES / "EVO896-prereg-LLMCLI-v0.1.2.json").read_bytes())
    receipt = json.loads(
        (FIXTURES / "EVO896-v012-design-acceptance-receipt.json").read_bytes()
    )
    if (
        receipt["ruling_sha256"] != BINDINGS["EVO896-v012-acceptance-ruling-v3.txt"]
        or receipt["bindings"]
        != {
            "prereg_sha256": BINDINGS["EVO896-prereg-LLMCLI-v0.1.2.json"],
            "profile_sha256": PROFILE_SHA,
            "source_archive_sha256": BINDINGS["EVO896-review-packet-LLMCLI-v0.1.2.zip"],
        }
        or receipt["design_accepted"] is not True
        or receipt["A1_A2_A3_effective"] is not True
    ):
        raise ValueError("binding.external_acceptance_links_mismatch")
    for key, suffix in (("schema", "json"), ("prompt", "txt")):
        name = (
            "EVO896-"
            + ("output-schema" if key == "schema" else key)
            + "-v0.1.2."
            + suffix
        )
        expected = (
            main["prompt"]["sha256"]
            if key == "prompt"
            else main["output"]["schema_sha256"]
        )
        if sha((FIXTURES / name).read_bytes()) != expected:
            raise ValueError("binding.sha_mismatch:" + name)
    return main


def whole(value):
    if type(value) is not int or not 0 <= value <= 1000000:
        raise ValueError("output.integer_shares_required")
    return value


def validate_output(raw, decision):
    main = bindings()
    value = strict_json(raw)
    schema = json.loads((FIXTURES / main["output"]["schema_file"]).read_bytes())
    if set(value) != set(schema["required"]):
        raise ValueError("output.exact_fields_required")
    for key, expected in {
        "arm_version": VERSION,
        "profile_sha256": PROFILE_SHA,
        "snapshot_id": decision["snapshot_id"],
        "input_sha256": decision["input_sha256"],
        "decision_session": decision["decision_session"],
    }.items():
        if value[key] != expected:
            raise ValueError("output.echo_mismatch:" + key)
    if (
        date.fromisoformat(value["decision_session"]).isoformat()
        != value["decision_session"]
    ):
        raise ValueError("output.session_invalid")
    for k in ("targets", "forecasts_h10_bps", "ranked_symbols"):
        if not isinstance(value[k], list):
            raise ValueError("output.array_required")
    if value["status"] == "ABSTAIN":
        if value["reason_code"] not in {
            "INPUT_UNAVAILABLE",
            "PLAN_INFEASIBLE",
            "RISK_LATCH",
        } or any(value[k] for k in ("targets", "forecasts_h10_bps", "ranked_symbols")):
            raise ValueError("output.abstain_invalid")
        return value
    if value["status"] != "READY" or value["reason_code"] != "OK":
        raise ValueError("output.status_invalid")
    assets = main["input_snapshot"]["asset_order"]
    eligible = [
        s for s in assets[:-1] if decision["eligibility"][s] == "VERIFIED_ELIGIBLE"
    ]
    ranked = value["ranked_symbols"]
    if (
        not 50 <= len(ranked) <= 64
        or any(not isinstance(s, str) for s in ranked)
        or len(set(ranked)) != len(ranked)
        or set(ranked) != set(eligible)
    ):
        raise ValueError("output.eligible_rank_required")
    for key, field in (
        ("targets", "target_qty"),
        ("forecasts_h10_bps", "gross_return_bps"),
    ):
        rows = value[key]
        if (
            len(rows) != 65
            or any(not isinstance(r, dict) or set(r) != {"symbol", field} for r in rows)
            or [r["symbol"] for r in rows] != assets
        ):
            raise ValueError("output.asset_order_required")
        for row in rows:
            if field == "target_qty":
                whole(row[field])
            elif row[field] is not None and (
                type(row[field]) is not int or not -10000 <= row[field] <= 10000
            ):
                raise ValueError("output.forecast_integer_bps_required")
    # Money/ratio validation belongs to the execution adapter, never JSON repair.
    return value


def decimal_string(value, *, positive=False):
    if not isinstance(value, str):
        raise ValueError("input.decimal_string_required")
    result = money(value)
    if positive and result <= 0:
        raise ValueError("input.positive_price_required")
    return result
