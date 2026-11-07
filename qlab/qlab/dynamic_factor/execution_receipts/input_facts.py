"""Owned four-file reads and their mandatory economic-fact binding.

Hashes identify bytes, not source permission. This diagnostic capability cannot
stand in for SRC/AUTH, a B release, a reseal or a complete-arm N receipt.
"""

from copy import deepcopy
import json
from weakref import WeakKeyDictionary

from ..contract import canonical, digest, sha256
from ..execution_numbers import amount
from ..reference_validation import utc_instant
from .input_data import validate_data
from .input_run import read_preparation, read_context


_READS = WeakKeyDictionary()
ROLES = ("raw", "rights", "adv", "cash")


class InputRead:
    def __init__(self):
        raise TypeError("reference.owned_four_file_read_required")


def read_files(root, preparation):
    """Acquire from the real isolated reader, never from a serialized report."""
    from ..reference_boundary import run_isolated

    request, _ = read_preparation(preparation)
    report = run_isolated(root, request, input_preparation=preparation)
    if report["transport_complete"] is not True:
        raise ValueError(report["reason"])
    profile, scope = read_context(preparation)
    document = dict(
        schema="EVO884.ReadExecutionFacts/v1",
        manifest=request["manifest"],
        profile=profile,
        scope=scope,
        data=report["data"],
        boundary=report["access_boundary_receipt"],
    )
    cap = object.__new__(InputRead)
    _READS[cap] = canonical(document)
    return cap


def read_facts(cap):
    if type(cap) is not InputRead or cap not in _READS:
        raise ValueError("reference.owned_four_file_read_required")
    raw = _READS[cap]
    return json.loads(raw), sha256(raw)


def bind_program(program, facts):
    """Check every original market cell before the sole engine is replayed.

    Selection signals and the separate analytical-TR benchmark retain their own
    identities; the four-file receipt does not authenticate either source.
    Numerical equality uses C04's canonical amount reader, never new rounding.
    """
    if (
        type(facts) is not dict
        or set(facts) != {"schema", "manifest", "profile", "scope", "data", "boundary"}
        or facts["schema"] != "EVO884.ReadExecutionFacts/v1"
    ):
        raise ValueError("reference.closed_read_facts_required")
    from .input_envelope import prepare_input_envelope

    m, scope = facts["manifest"], facts["scope"]
    checked = prepare_input_envelope(
        facts["profile"],
        scope,
        m,
        book_id=m["book_id"],
        run_id=m["run_id"],
        expected_manifest_sha256=digest(m),
        expected_scope_sha256=m["scope_sha256"],
        expected_profile_sha256=m["profile_sha256"],
    )
    if not checked["prepared"]:
        raise ValueError(checked["reasons"][0])
    initial = program["initial"]
    identity = initial["history"]["scope"]
    if (
        initial["run_id"] != m["run_id"]
        or initial["history"]["book_id"] != m["book_id"]
        or identity["member_id"] != m["member_id"]
        or facts["profile"]["profile_sha256"] != m["profile_sha256"]
        or digest(initial["history"]["guard"]) != digest(scope["guard"])
    ):
        raise ValueError("reference.input_execution_identity_mismatch")
    boundary = facts["boundary"]
    if (
        boundary["declared_input_manifest"] != m
        or boundary["source_acceptance"] != "not_checked"
        or boundary["isolated_child"] is not True
        or boundary["accessed_roles"] != list(ROLES)
        or boundary["seal_status"] != "seal_pending"
        or boundary["input_file_sha256"]
        != {role: m["inputs"][role]["sha256"] for role in ROLES}
    ):
        raise ValueError("reference.four_file_boundary_mismatch")
    index, reads, processed, consumed = {}, [], set(), {}
    if set(facts["data"]) != set(ROLES):
        raise ValueError("reference.four_roles_required")
    for role in ROLES:
        data = facts["data"][role]
        validate_data(canonical(data), role, m)
        index[role] = {(r["date"], r["symbol"]): r for r in data["records"]}

    def cell(role, date, symbol, key, asof):
        row = index[role].get((date, symbol))
        if row is None:
            raise ValueError("reference.execution_cell_missing")
        if utc_instant(row["available_at"]) > utc_instant(asof):
            raise ValueError("reference.execution_cell_not_yet_available")
        value = row["values"][key]
        if value is None:
            raise ValueError("reference.execution_cell_unknown")
        reads.append(
            dict(
                role=role,
                date=date,
                symbol=symbol,
                field=key,
                original_value_sha256=digest(value),
                file_sha256=m["inputs"][role]["sha256"],
            )
        )
        return value

    def prices(values, date, key, asof):
        consumed.setdefault(date, set()).update(values)
        for symbol, value in values.items():
            if amount(value) != amount(cell("raw", date, symbol, key, asof)):
                raise ValueError("reference.execution_price_not_from_read")

    times = {kind: {} for kind in ("model_open", "close")}
    for event in program["operations"]:
        if event["operation"] in times:
            e = event["arguments"]["evidence"]
            times[event["operation"]][e["session"]] = e["asof"]
    closes = []
    for event in program["operations"]:
        op, a = event["operation"], event["arguments"]
        if op == "startup_open":
            date = utc_instant(a["timestamp"]).date().isoformat()
            prices({"QQQ": a["raw_open"]}, date, "raw_open", a["timestamp"])
            if a["source_sha256"] != m["inputs"]["raw"]["sha256"]:
                raise ValueError("reference.execution_raw_source_mismatch")
        elif op == "lock_projection":
            inputs = a["inputs"]
            opening = inputs["execution_open"]
            date = opening["session"]
            # N1/N5 already bind the sole core: these are the locked T-open
            # facts, not a second signal selection at the open.
            if date not in times["model_open"]:
                raise ValueError("reference.actual_open_observation_time_required")
            asof = times["model_open"][date]
            prices(opening["raw_open"], date, "raw_open", asof)
            signal_date = inputs["close_state"]["signal_close_session"]
            day = scope["days"].get(signal_date)
            eligibility = inputs["eligibility"]
            if day is None or (
                eligibility["E_t"] != day["eligible"]
                or eligibility["named_count"] != day["verified_count"]
                or eligibility["quantity_state"] != day["quantity_state"]
                or eligibility["B"] != scope["guard"]["B"]
            ):
                raise ValueError("reference.execution_E_t_not_from_scope")
            for symbol, value in opening["ADV20_usd_asof_close"].items():
                if signal_date not in times["close"]:
                    raise ValueError("reference.actual_signal_close_time_required")
                if amount(value) != amount(
                    cell(
                        "adv",
                        signal_date,
                        symbol,
                        "adv20_dollar",
                        times["close"][signal_date],
                    )
                ):
                    raise ValueError("reference.execution_ADV_not_from_read")
        elif op in {"model_open", "close"}:
            e = a["evidence"]
            date, asof = e["session"], e["asof"]
            prices(
                e["prices"],
                date,
                "raw_open" if op == "model_open" else "raw_close",
                asof,
            )
            if e["source_sha256"] != m["inputs"]["raw"]["sha256"]:
                raise ValueError("reference.execution_raw_source_mismatch")
            if op == "close":
                closes.append(date)
                if a["startup_valuation"] is not None:
                    prices(
                        {"QQQ": a["startup_valuation"]["raw_close"]},
                        date,
                        "raw_close",
                        asof,
                    )
                # Original nonempty events must have a common-accounting
                # operation. A complete flag never erases an unread event.
                for role in ("rights", "cash"):
                    if not consumed[date] <= {
                        symbol for d, symbol in index[role] if d == date
                    }:
                        raise ValueError("reference.original_event_coverage_required")
                    for d, symbol in index[role]:
                        if d != date:
                            continue
                        events = cell(role, date, symbol, role + "_events", asof)
                        if any(
                            (role, date, symbol, row["sha256"]) not in processed
                            for row in events
                        ):
                            raise ValueError("reference.unprocessed_original_event")
        elif op == "cash_event":
            role = a["role"]
            if utc_instant(a["asof"]).date().isoformat() != a["session"]:
                raise ValueError("reference.original_event_session_mismatch")
            if role not in {"cash", "rights"}:
                raise ValueError("reference.event_role_invalid")
            originals = cell(
                role, a["session"], a["event"]["symbol"], role + "_events", a["asof"]
            )
            matching = [
                r
                for r in originals
                if canonical(json.loads(r["raw"])) == canonical(a["event"])
            ]
            if len(matching) != 1:
                raise ValueError("reference.event_not_from_read")
            key = (role, a["session"], a["event"]["symbol"], matching[0]["sha256"])
            if key in processed:
                raise ValueError("reference.duplicate_original_event")
            processed.add(key)
        else:
            raise ValueError("reference.execution_operation_not_whitelisted")
    if closes != scope["train"]:
        raise ValueError("reference.complete_read_train_required")
    return dict(
        schema="EVO884.ReadExecutionFactBinding/v1",
        program_sha256=digest(program),
        facts_sha256=digest(facts),
        manifest_sha256=digest(m),
        input_files=deepcopy(boundary["input_file_sha256"]),
        original_read_roles=list(ROLES),
        original_reader_calls=4,
        fact_cells=reads,
        processed_events=len(processed),
        source_acceptance="not_checked",
        seal_status="seal_pending",
        runtime_consumable=False,
        certifiable=False,
    )
