"""V5 raw-prefix cases; synthetic fixtures confer no installation authority."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from qlab.dynamic_factor import authority_prefix as prefix
from qlab.dynamic_factor.authority_ledger import (
    FIELDS,
    FIXTURES,
    PUBLISHED,
    records,
    state,
    verify_bytes,
)
from qlab.dynamic_factor.contract import canonical, digest, sha256


def observation(raw, anchor, *, path="/SYNTHETIC/authority/ledger.jsonl"):
    # The test's independent source pins these bytes; this is not a production
    # permission adapter. Original anchor formatting is retained and hashed.
    anchor_raw = json.dumps(anchor, indent=2, sort_keys=True).encode() + b"\n"
    anchor_sha = sha256(anchor_raw)
    return dict(
        anchor_raw=anchor_raw,
        anchor_ref="sha256:" + anchor_sha,
        anchor_payload_sha256=anchor_sha,
        approved_anchor_sha256=anchor_sha,
        approved_release_sha256=sha256(b"PRIVATE_APPROVED_RELEASE"),
        ledger_path=path,
        ledger_sha256=sha256(raw),
    )


def sample():
    raw = b"".join(
        canonical(dict(seq=i, value="line-" + str(i))) + b"\n" for i in range(3)
    )
    anchor = dict(
        PUBLISHED,
        sequence=2,
        ledger_file_sha256=sha256(raw),
    )
    return raw, anchor


def check_receipt(result):
    assert set(result) == {"schema", "status", "evidence_refs", "measured", "reasons"}
    assert result["schema"] == "EVO884.AnchorPrefixCheck/v1"
    assert set(result["measured"]) == set(prefix.MEASUREMENTS)
    assert result["evidence_refs"]
    for ref in result["evidence_refs"]:
        assert ref.startswith("sha256:") and len(ref) == 71
        int(ref[7:], 16)
    if result["status"] == "PASS":
        assert not result["reasons"]
        assert all(v is not None for v in result["measured"].values())
        assert result["measured"]["equal"] is True
    else:
        assert result["status"] in {"FAIL", "MISSING"}
        assert result["reasons"] and all(r.strip() for r in result["reasons"])
    json.dumps(result, allow_nan=False)
    return result


@pytest.mark.parametrize(
    "case,reason",
    [
        ("V5-01", None),
        ("V5-02", "ledger.anchor_prefix_truncated"),
        ("V5-03", "ledger.anchor_prefix_truncated"),
        ("V5-04", "ledger.anchor_prefix_line_format_invalid"),
        ("V5-06", "ledger.anchor_prefix_sha256_mismatch"),
        ("V5-08", "ledger.anchor_prefix_line_format_invalid"),
        ("V5-09", "ledger.anchor_prefix_line_format_invalid"),
        ("V5-10", "ledger.anchor_prefix_sha256_mismatch"),
        ("V5-11", "ledger.anchor_prefix_sequence_mismatch"),
        ("V5-12", "ledger.anchor_prefix_input_invalid"),
        ("V5-13", "ledger.current_release_unbound_or_stale"),
        ("V5-14", "ledger.observed_object_drift"),
    ],
    ids=lambda value: value if value is None or value.startswith("V5-") else None,
)
def test_v5_original_prefix_cases(case, reason, record_property):
    record_property("spec_id", case)
    raw, anchor = sample()
    if case == "V5-02":
        raw = raw[: raw.find(b"\n") + 1]
    elif case == "V5-03":
        raw = raw[:-1]
    elif case == "V5-04":
        raw = raw[:-1] + b" \n"
    elif case == "V5-06":
        raw = raw.replace(b"line-1", b"evil-1")
    elif case == "V5-08":
        raw = raw.replace(b"\n", b"\r\n", 1)
    elif case == "V5-09":
        raw = raw.replace(b"\n", b"\r\n")
    elif case == "V5-10":
        anchor["sequence"] -= 1
    elif case == "V5-11":
        raw = raw.replace(b'"seq":1', b'"seq":7')
    elif case == "V5-12":
        anchor.pop("ledger_file_sha256")
    obs = observation(raw, anchor)
    if case == "V5-13":
        obs["approved_anchor_sha256"] = "f" * 64
    elif case == "V5-14":
        obs["ledger_sha256"] = "f" * 64
    result = check_receipt(prefix.verify_anchor_prefix(raw, anchor, obs))
    assert result["reasons"] == ([] if reason is None else [reason])
    record_property("actual_reason", reason or "PASS")
    record_property("range_end", result["measured"]["range_end"])
    record_property("observed_sha256", result["measured"]["observed_sha256"])
    if case == "V5-01":
        assert result["measured"]["range_end"] == len(raw)
        assert result["measured"]["observed_sha256"] == sha256(raw)
        assert result["measured"]["line_count"] == 3


@pytest.mark.parametrize("bad", [True, False, 2.0, "2", -1, None])
def test_v5_anchor_sequence_is_an_exact_nonnegative_integer(bad):
    raw, anchor = sample()
    anchor["sequence"] = bad
    result = prefix.verify_anchor_prefix(raw, anchor, observation(raw, anchor))
    assert check_receipt(result)["reasons"] == ["ledger.anchor_prefix_input_invalid"]


@pytest.mark.parametrize(
    "bad_line,reason",
    [
        (b'{"seq":0,"seq":0}', "ledger.anchor_prefix_line_format_invalid"),
        (b'{"seq":0,"x":NaN}', "ledger.anchor_prefix_line_format_invalid"),
        (b'{"seq":0,"x":1e999}', "ledger.anchor_prefix_line_format_invalid"),
        (b'{"seq": 0}', "ledger.anchor_prefix_line_format_invalid"),
        (b'[{"seq":0}]', "ledger.anchor_prefix_line_format_invalid"),
        (b"", "ledger.anchor_prefix_line_format_invalid"),
        (b'{"seq":true}', "ledger.anchor_prefix_sequence_mismatch"),
        (b'{"seq":0.0}', "ledger.anchor_prefix_sequence_mismatch"),
        (b'{"seq":0,"x":"\xff"}', "ledger.anchor_prefix_line_format_invalid"),
    ],
)
def test_v5_never_repairs_original_line_bytes(bad_line, reason):
    raw, anchor = sample()
    raw = bad_line + b"\n" + raw[raw.find(b"\n") + 1 :]
    result = prefix.verify_anchor_prefix(raw, anchor, observation(raw, anchor))
    assert check_receipt(result)["reasons"] == [reason]


@pytest.mark.parametrize("value", [None, {}, [], b"x", "chain"])
def test_v5_missing_or_malformed_host_binding_has_no_fallback(value):
    raw, anchor = sample()
    result = prefix.verify_anchor_prefix(raw, anchor, value)
    assert check_receipt(result)["status"] == "MISSING"
    assert result["reasons"] == ["ledger.current_release_unbound_or_stale"]
    assert result["measured"]["range_end"] is None


def test_v5_original_anchor_bytes_are_independently_pinned():
    raw, anchor = sample()
    obs = observation(raw, anchor)
    changed = dict(anchor, sequence=1)
    result = prefix.verify_anchor_prefix(raw, changed, obs)
    assert check_receipt(result)["reasons"] == [
        "ledger.current_release_unbound_or_stale"
    ]
    # A duplicate-key source is rejected even when its last value looks right.
    obs["anchor_raw"] = b'{"sequence":1,"sequence":2}'
    result = prefix.verify_anchor_prefix(raw, anchor, obs)
    assert check_receipt(result)["reasons"] == ["ledger.anchor_prefix_input_invalid"]


def test_v5_preserves_the_original_nonblank_anchor_reference():
    raw, anchor = sample()
    obs = observation(raw, anchor)
    obs["anchor_ref"] = "PRIVATE-PUBLISHED-ANCHOR@seq2"
    result = check_receipt(prefix.verify_anchor_prefix(raw, anchor, obs))
    assert result["status"] == "PASS"
    assert result["measured"]["anchor_ref"] == obs["anchor_ref"]


def test_v5_is_pure_and_does_not_mutate_or_open_metadata_paths(monkeypatch):
    raw, anchor = sample()
    obs = observation(raw, anchor)
    before = deepcopy((anchor, obs))

    def forbidden(*args, **kwargs):
        raise AssertionError("V5 must not open or write any path")

    with monkeypatch.context() as context:
        context.setattr("builtins.open", forbidden)
        context.setattr(Path, "read_bytes", forbidden)
        context.setattr(Path, "write_bytes", forbidden)
        first = prefix.verify_anchor_prefix(raw, anchor, obs)
        second = prefix.verify_anchor_prefix(raw, anchor, obs)
    assert first == second
    assert (anchor, obs) == before
    assert check_receipt(first)["status"] == "PASS"


def test_v5_nonbytes_has_no_fabricated_raw_evidence():
    with pytest.raises(ValueError, match="^ledger.anchor_prefix_input_invalid$"):
        prefix.verify_anchor_prefix("not bytes", {}, {})


def test_v5_15_self_reported_pass_cannot_replace_recomputation(record_property):
    record_property("spec_id", "V5-15")
    raw, anchor = sample()
    changed = raw.replace(b"line-1", b"evil-1")
    obs = observation(changed, anchor)
    obs.update(status="PASS", equal=True)
    result = prefix.verify_anchor_prefix(changed, anchor, obs)
    assert check_receipt(result)["reasons"] == ["ledger.anchor_prefix_sha256_mismatch"]
    assert result["measured"]["equal"] is False
    record_property("actual_reason", result["reasons"][0])


def original_archive():
    raw = (FIXTURES / "EVO891-B-ledger-v2.jsonl").read_bytes()
    witness = json.loads((FIXTURES / "EVO891-B-ledger-v2.tip.json").read_bytes())
    anchor = dict(PUBLISHED, ledger_file_sha256=sha256(raw))
    return raw, witness, anchor


def test_v5_06_rehashed_history_and_matching_local_witness_cannot_change_pin(
    record_property,
):
    record_property("spec_id", "V5-06")
    raw, _, anchor = original_archive()
    rows = records(raw)
    rows[1]["private_tamper"] = True
    for index, row in enumerate(rows[1:], 1):
        row["previous_hash"] = digest(rows[index - 1])
    changed = b"".join(canonical(row) + b"\n" for row in rows)
    current = state(rows)
    forged_witness = {key: current[key] for key in FIELDS}
    forged_witness["ledger_file_sha256"] = sha256(changed)
    assert forged_witness["tip"] == digest(rows[-1])
    assert forged_witness["ledger_file_sha256"] == sha256(changed)
    result = prefix.verify_anchor_prefix(changed, anchor, observation(changed, anchor))
    assert check_receipt(result)["reasons"] == ["ledger.anchor_prefix_sha256_mismatch"]
    with pytest.raises(ValueError, match="ledger.published_prefix_mismatch"):
        verify_bytes(changed, forged_witness, anchor)
    record_property("actual_reason", result["reasons"][0])


def append_gap(raw):
    rows = records(raw)
    rows.append(
        dict(
            event="gap_update",
            seq=len(rows),
            previous_hash=digest(rows[-1]),
            gap_id="PRIVATE-GAP",
            status="open",
        )
    )
    current = state(rows)
    rows.append(
        dict(
            event="checkpoint",
            seq=len(rows),
            previous_hash=digest(rows[-1]),
            N=current["N"],
            n_high_water=current["n_high_water"],
        )
    )
    new_raw = b"".join(canonical(row) + b"\n" for row in rows)
    current = state(rows)
    witness = {key: current[key] for key in FIELDS}
    witness.update(
        ledger_file="EVO891-B-ledger-v2.jsonl", ledger_file_sha256=sha256(new_raw)
    )
    return new_raw, witness


@pytest.mark.parametrize("suffix", ["gap_without_witness", "blank", "bad_checkpoint"])
def test_v5_05_tail_prefix_pass_cannot_bypass_full_reader(suffix, record_property):
    record_property("spec_id", "V5-05")
    raw, witness, anchor = original_archive()
    if suffix == "blank":
        changed = raw + b"\n"
    else:
        changed, _ = append_gap(raw)
        if suffix == "bad_checkpoint":
            changed = changed.replace(b'"event":"checkpoint"', b'"event":"CHECKPOINT"')
            # Preserve the anchored prefix; mutate only the appended suffix.
            changed = raw + changed[len(raw) :]
    result = prefix.verify_anchor_prefix(changed, anchor, observation(changed, anchor))
    assert check_receipt(result)["status"] == "PASS"
    assert result["measured"]["range_end"] == len(raw)
    with pytest.raises(ValueError) as error:
        verify_bytes(changed, witness, anchor)
    record_property("actual_reason", str(error.value))


def test_v5_07_legitimate_append_and_current_witness_preserve_old_prefix(
    record_property,
):
    record_property("spec_id", "V5-07")
    raw, _, anchor = original_archive()
    changed, witness = append_gap(raw)
    assert changed[: len(raw)] == raw
    result = prefix.verify_anchor_prefix(changed, anchor, observation(changed, anchor))
    assert check_receipt(result)["status"] == "PASS"
    assert result["measured"]["observed_sha256"] == sha256(raw)
    assert result["measured"]["ledger_sha256"] == sha256(changed)
    assert result["measured"]["observed_sha256"] != result["measured"]["ledger_sha256"]
    current, _ = verify_bytes(changed, witness, anchor)
    assert current["sequence"] == anchor["sequence"] + 2
    assert current["n_high_water"] == anchor["n_high_water"]
    record_property("actual_reason", "PASS_PREFIX_AND_FULL_INTEGRITY_ONLY")


def receiver_fixture(tmp_path, monkeypatch, mutation):
    """Private host source with real V5; never a production trust constructor."""
    from authority_host_helpers import private_host
    from qlab.dynamic_factor import authority_host as host
    from qlab.dynamic_factor.authority_record_types import _HOST_TOKEN, _issue_coverage

    context, snapshot, _, source = private_host(
        tmp_path, monkeypatch, prefix_stub=False
    )
    _, replay, coverage = host.check_snapshot(context, snapshot)
    raw, anchor = source["chain_raw"], source["anchor"]
    if mutation == "truncate":
        # The v2 archive's entire original prefix ends at seq20.
        boundary = len((FIXTURES / "EVO891-B-ledger-v2.jsonl").read_bytes())
        raw = raw[: boundary - 1]
    elif mutation == "CRLF":
        raw = raw.replace(b"\n", b"\r\n", 1)
    elif mutation == "wrong_sequence":
        anchor["sequence"] -= 1
    elif mutation in {"stale_witness", "legal_append"}:
        rows = records(raw)
        rows.append(
            dict(
                event="gap_update",
                seq=len(rows),
                previous_hash=digest(rows[-1]),
                gap_id="PRIVATE-APPEND",
                status="open",
            )
        )
        rows.append(
            dict(
                event="checkpoint",
                seq=len(rows),
                previous_hash=digest(rows[-1]),
                N=1313,
                n_high_water=1313,
            )
        )
        raw = b"".join(canonical(row) + b"\n" for row in rows)
        coverage = _issue_coverage(raw, "PRIVATE-APPEND-APPROVAL", _HOST_TOKEN)
        if mutation == "legal_append":
            cur = state(rows, trusted_coverage=coverage)
            witness = {key: cur[key] for key in FIELDS}
            witness.update(
                ledger_file="EVO891-B-ledger-v2.jsonl", ledger_file_sha256=sha256(raw)
            )
            source["witness"] = witness
            witness_raw = canonical(witness) + b"\n"
            Path(source["witness_path"]).write_bytes(witness_raw)
            source["witness_sha256"] = sha256(witness_raw)
    source["chain_raw"] = raw
    source["chain_sha256"] = sha256(raw)
    Path(source["chain_path"]).write_bytes(raw)
    source["observation"] = observation(raw, anchor, path=source["chain_path"])
    source["observation"]["approved_release_sha256"] = source["identities"][
        "approved_release_sha256"
    ]
    source["published_anchor_bytes"] = source["observation"]["anchor_raw"]
    # Other return identities are synthetic but must describe the same source.
    source["identities"]["anchor_sha256"] = sha256(source["published_anchor_bytes"])
    source["identities"]["chain_sha256"] = sha256(raw)
    source["identities"]["witness_sha256"] = source["witness_sha256"]
    monkeypatch.setattr(host, "_read_approved_deployment", lambda: deepcopy(source))
    context = host.open_host_context()
    snapshot = host._retain_snapshot(context, {"accepted": True}, replay, coverage)
    pin = host.pin_run(context, arm_tag="EVO883_FACTOR", run_id="PRIVATE-V5-RECEIVER")
    return context, snapshot, pin, source


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("truncate", "ledger.anchor_prefix_truncated"),
        ("CRLF", "ledger.anchor_prefix_line_format_invalid"),
        ("wrong_sequence", "ledger.anchor_prefix_sha256_mismatch"),
        ("stale_witness", "ledger.tail_or_high_water_mismatch"),
    ],
)
def test_v5_formal_receiver_rejects_before_projection(
    tmp_path, monkeypatch, mutation, reason, record_property
):
    from qlab.dynamic_factor.reception_v2 import receive_arm_n

    context, snapshot, pin, source = receiver_fixture(tmp_path, monkeypatch, mutation)
    calls = []
    actual = prefix.verify_anchor_prefix

    def counted(*args):
        result = actual(*args)
        calls.append(result)
        return result

    monkeypatch.setattr(prefix, "verify_anchor_prefix", counted)
    result = receive_arm_n(
        source["approval_bytes"],
        source["projection_bytes"],
        host_context=context,
        installed_snapshot=snapshot,
        run_pin=pin,
        arm_tag="EVO883_FACTOR",
    )
    assert result["accepted"] is False
    assert result["reasons"] == [reason]
    assert result["details"]["complete_N"] is None
    assert result["observations"]["formal_projection_consumption"] == 0
    assert len(calls) == 1
    assert calls[0]["status"] == ("PASS" if mutation == "stale_witness" else "FAIL")
    record_property("receiver_mutation", mutation)
    record_property("actual_reason", reason)
    record_property("prefix_calls", len(calls))
    record_property("projection_consumption", 0)


@pytest.mark.parametrize("mutation", ["unchanged", "legal_append"])
def test_v5_formal_receiver_and_bound_readback_share_the_real_helper(
    tmp_path, monkeypatch, mutation, record_property
):
    from qlab.dynamic_factor import authority_host as host
    from qlab.dynamic_factor.reception_v2 import receive_arm_n

    context, snapshot, pin, source = receiver_fixture(tmp_path, monkeypatch, mutation)
    calls = []
    actual = prefix.verify_anchor_prefix

    def counted(*args):
        checked = actual(*args)
        calls.append(checked)
        return checked

    monkeypatch.setattr(prefix, "verify_anchor_prefix", counted)
    result = receive_arm_n(
        source["approval_bytes"],
        source["projection_bytes"],
        host_context=context,
        installed_snapshot=snapshot,
        run_pin=pin,
        arm_tag="EVO883_FACTOR",
    )
    assert result["accepted"] is True, result["reasons"]
    assert result["details"]["complete_N"] is None
    assert result["details"]["n_evaluated_unknown_count"] == 101
    view = host.host_view(context, snapshot, pin, "EVO883_FACTOR")
    readback = view.arm_readout("EVO883_FACTOR")
    # Readback cannot turn the controlled unknowns into a complete formal N.
    binding = readback["artifacts"]["formal_N_binding"]
    assert binding["accepted"] is False
    assert binding["details"]["gate_N"] is None
    assert binding["reasons"] == ["reception.N_complete_projection_required"]
    assert len(calls) >= 2
    assert all(check_receipt(check)["status"] == "PASS" for check in calls)
    assert len({check["measured"]["observed_sha256"] for check in calls}) == 1
    assert all(
        check["measured"]["approved_release_sha256"]
        == source["identities"]["approved_release_sha256"]
        for check in calls
    )
    record_property("receiver_mutation", mutation)
    record_property("prefix_calls", len(calls))
    record_property("actual_reason", "PASS_INTEGRITY_COMPLETE_N_NULL")
