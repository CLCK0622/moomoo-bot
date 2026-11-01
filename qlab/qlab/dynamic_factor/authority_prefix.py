"""Read-only V5 check of the original LF bytes through an approved anchor.

The host must obtain anchor/observation from its original approval source,
bind the same immutable chain buffer, and reject untrusted/current-release
failures before calling this helper. A caller-created dict is not authority.
This module opens no paths and grants no read/write or runtime capability.

Formal reception and independent readback use this one function. Installation
call site: authority_install.preflight -> verify_anchor_prefix (待安装前提).
No installation entrypoint is enabled here. A PASS checks the prefix only;
the caller must still verify the complete chain, checkpoint, current witness,
state, original published ancestor, and source/permission prerequisites.
"""

import hashlib
import json
from pathlib import PurePosixPath
from typing import Any, Dict


SCHEMA = "EVO884.AnchorPrefixCheck/v1"
MEASUREMENTS = (
    "anchor_ref",
    "anchor_sequence",
    "range_end",
    "expected_sha256",
    "observed_sha256",
    "ledger_path",
    "ledger_sha256",
    "algorithm",
    "line_count",
    "byte_start",
    "ledger_bytes",
    "anchor_payload_sha256",
    "approved_release_sha256",
    "equal",
)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _is_sha(value):
    return (
        type(value) is str
        and len(value) == 64
        and all(c in "0123456789abcdef" for c in value)
    )


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _constant(value):
    raise ValueError("nonfinite_json_number")


def _json(raw):
    return json.loads(
        raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant
    )


def _canonical(value):
    # Do not use contract.clean: it deliberately maps nonfinite numbers to null.
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def verify_anchor_prefix(chain_raw: bytes, anchor, observation) -> Dict[str, Any]:
    """Return the closed V5 receipt for a host-bound bytes/anchor observation.

    observation contains ledger_path, ledger_sha256, anchor_raw, anchor_ref,
    anchor_payload_sha256, approved_anchor_sha256, approved_release_sha256.
    approved_anchor_sha256 is the current anchor pin from the trusted release;
    anchor_payload_sha256 hashes anchor_raw, not the JSONL prefix. The host
    owns provenance; neither these strings nor the result can mint host trust.

    Malformed domain inputs return FAIL/MISSING with measured unknowns null.
    A non-bytes first argument raises ValueError before any parsing: no raw
    evidence exists from which to construct a receipt evidence reference.
    """
    if type(chain_raw) is not bytes:
        raise ValueError("ledger.anchor_prefix_input_invalid")
    measured = dict.fromkeys(MEASUREMENTS)
    measured.update(
        ledger_sha256=_sha(chain_raw),
        ledger_bytes=len(chain_raw),
        algorithm="sha256",
        line_count=0,
        byte_start=0,
    )
    refs = ["sha256:" + measured["ledger_sha256"]]

    def result(reason=None, status="FAIL"):
        return {
            "schema": SCHEMA,
            "status": "PASS" if reason is None else status,
            "evidence_refs": list(dict.fromkeys(refs)),
            "measured": measured,
            "reasons": [] if reason is None else [reason],
        }

    invalid = "ledger.anchor_prefix_input_invalid"
    if anchor is None:
        return result(invalid, "MISSING")
    if type(anchor) is not dict:
        return result(invalid)
    sequence = anchor.get("sequence")
    if type(sequence) is not int or sequence < 0:
        return result(invalid)
    measured["anchor_sequence"] = sequence
    expected = anchor.get("ledger_file_sha256")
    if not _is_sha(expected):
        return result(invalid)
    measured["expected_sha256"] = expected
    if (
        not _is_sha(anchor.get("ledger_id"))
        or not _is_sha(anchor.get("tip"))
        or type(anchor.get("n_high_water")) is not int
        or anchor["n_high_water"] < 0
    ):
        return result(invalid)
    if type(observation) is not dict:
        return result("ledger.current_release_unbound_or_stale", "MISSING")
    anchor_raw = observation.get("anchor_raw")
    if type(anchor_raw) is not bytes:
        return result("ledger.current_release_unbound_or_stale", "MISSING")
    anchor_sha = _sha(anchor_raw)
    refs.append("sha256:" + anchor_sha)
    measured["anchor_payload_sha256"] = anchor_sha
    try:
        original_anchor = _json(anchor_raw)
        if type(original_anchor) is not dict or _canonical(
            original_anchor
        ) != _canonical(anchor):
            return result("ledger.current_release_unbound_or_stale")
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
        return result(invalid)
    if (
        observation.get("anchor_payload_sha256") != anchor_sha
        or observation.get("approved_anchor_sha256") != anchor_sha
        or type(observation.get("anchor_ref")) is not str
        or not observation["anchor_ref"].strip()
        or not _is_sha(observation.get("approved_release_sha256"))
    ):
        return result("ledger.current_release_unbound_or_stale")
    measured["anchor_ref"] = observation["anchor_ref"]
    measured["approved_release_sha256"] = observation["approved_release_sha256"]
    path = observation.get("ledger_path")
    if (
        type(path) is not str
        or len(path) < 2
        or not PurePosixPath(path).is_absolute()
        or ".." in PurePosixPath(path).parts
    ):
        return result(invalid)
    measured["ledger_path"] = path
    if observation.get("ledger_sha256") != measured["ledger_sha256"]:
        return result("ledger.observed_object_drift")

    if sequence >= chain_raw.count(b"\n"):
        return result("ledger.anchor_prefix_truncated")
    start = 0
    for index in range(sequence + 1):
        end = chain_raw.find(b"\n", start)
        if end < 0:
            return result("ledger.anchor_prefix_truncated")
        raw_line = chain_raw[start:end]
        if not raw_line or b"\r" in raw_line:
            return result("ledger.anchor_prefix_line_format_invalid")
        try:
            row = _json(raw_line)
            if type(row) is not dict or _canonical(row) != raw_line:
                return result("ledger.anchor_prefix_line_format_invalid")
        except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
            return result("ledger.anchor_prefix_line_format_invalid")
        if type(row.get("seq")) is not int or row["seq"] != index:
            return result("ledger.anchor_prefix_sequence_mismatch")
        start = end + 1  # Original LF is included; never reconstruct hash bytes.
        measured["line_count"] = index + 1
    measured["range_end"] = start
    measured["observed_sha256"] = _sha(chain_raw[:start])
    measured["equal"] = measured["observed_sha256"] == expected
    if not measured["equal"]:
        return result("ledger.anchor_prefix_sha256_mismatch")
    return result()
