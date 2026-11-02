"""Closed transport records, before C04 semantics or trusted source reception.

Original event JSON stays original bytes. A finite-looking amount, an empty
event vector or a matching hash is not evidence that a price/cash/right is known.
"""

import hashlib
import json
import math

from ..reference_validation import utc_instant


FIELDS = {
    "raw": {"raw_open", "raw_close"},
    "adv": {"adv20_dollar"},
    "rights": {"rights_events"},
    "cash": {"cash_events"},
}
IDENTITIES = ("book_id", "run_id", "member_id", "scope_sha256", "profile_sha256")


def require_resealed_evidence(value):
    """A pending readout is forbidden anywhere in a supplied sidecar.

    Absence of this marker is not source authentication or reseal acceptance.
    The formal B/P4/P7 and permission gates must still be satisfied separately.
    """
    pending = [value]
    while pending:
        item = pending.pop()
        if type(item) is dict:
            if item.get("seal_status") == "seal_pending":
                raise ValueError("reference.seal_pending")
            pending.extend(item.values())
        elif type(item) is list:
            pending.extend(item)


def strict_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("execution_input.duplicate_json_key")
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError("execution_input.nonfinite_json")

    return json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)


def validate_data(raw, role, manifest):
    data = strict_json(raw)
    if (
        type(data) is not dict
        or set(data) != {"schema", "role", "records"} | set(IDENTITIES)
        or data["schema"] != "EVO884.RestrictedExecutionRows/v1"
        or data["role"] != role
        or any(data[k] != manifest[k] for k in IDENTITIES)
        or type(data["records"]) is not list
    ):
        raise ValueError("execution_input.data_schema_or_binding_mismatch")
    slot = manifest["inputs"][role]
    expected = [(d, s) for d in slot["requested_dates"] for s in slot["symbols"]]
    actual = []
    # Validate every identity before examining the first value. The host has
    # already applied the original B predicate to this exact hashed manifest.
    for row in data["records"]:
        if type(row) is not dict or set(row) != {
            "date",
            "symbol",
            "available_at",
            "values",
        }:
            raise ValueError("execution_input.record_schema_or_injection_forbidden")
        actual.append((row["date"], row["symbol"]))
    if actual != expected:
        raise ValueError("execution_input.exact_declared_date_symbol_batch_required")
    for row in data["records"]:
        utc_instant(row["available_at"])
        values = row["values"]
        if type(values) is not dict or set(values) != FIELDS[role]:
            raise ValueError("execution_input.fields_not_whitelisted")
        for value in values.values():
            if role in {"raw", "adv"}:
                # Preserve explicit unknowns and exact decimal spellings. C04
                # owns the canonical amount/units/price-time validation later.
                if value is not None and (
                    type(value) not in (str, int, float)
                    or (type(value) is str and not value)
                    or (type(value) is float and not math.isfinite(value))
                ):
                    raise ValueError("execution_input.scalar_transport_required")
            else:
                if value is None:
                    continue
                if type(value) is not list:
                    raise ValueError("execution_input.original_event_vector_required")
                for event in value:
                    if (
                        type(event) is not dict
                        or set(event) != {"raw", "sha256"}
                        or type(event["raw"]) is not str
                        or hashlib.sha256(event["raw"].encode()).hexdigest()
                        != event["sha256"]
                        or type(strict_json(event["raw"])) is not dict
                    ):
                        raise ValueError(
                            "execution_input.original_event_bytes_required"
                        )
    return data
