import pytest

from qlab.dynamic_factor.authority_ledger import (
    records,
    replay_approved_archive,
    validate_new_attempt,
    state,
)
from qlab.dynamic_factor.authority_record_types import validate_attempt_fields
from authority_stage1_helpers import archive, rewrite, raw_json
from qlab.dynamic_factor.authority_record_types import _issue_coverage, _HOST_TOKEN


def test_101_unknown_rows_preserve_book_and_never_become_formal_bounds():
    raw, witness, coverage = archive()
    before = bytes(raw)
    result = replay_approved_archive(raw, trusted_release=coverage, witness=witness)
    assert raw == before
    assert result["accepted"] is True
    assert result["raw_unknown_rows"] == 101
    assert result["book_N"] == result["high_water"] == 1313
    assert result["counted_as_zero"] is result["counted_as_not_evaluated"] is False
    for key in (
        "complete_N",
        "gate_N",
        "formal_lower_bound",
        "formal_upper_bound",
        "DSR",
    ):
        assert result[key] is None
    assert result["n_complete"] is result["new_writes_relaxed"] is False
    original = [row for row in records(raw) if row.get("n_evaluated_null_reason")]
    assert [row["attempt_id"] for row in result["unknown_rows"]] == [
        row["attempt_id"] for row in original
    ]
    assert all(row["n_evaluated"] is None for row in result["unknown_rows"])


@pytest.mark.parametrize("value", [None, -1, 1.0, True, "0"])
def test_new_writes_never_relax(value):
    raw, _, _ = archive()
    row = dict(records(raw)[1149], n_evaluated=value)
    with pytest.raises(ValueError, match="ledger.attempt_field_missing_or_invalid"):
        validate_new_attempt(row, records(raw)[:21])


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_reason_and_coverage_both_required(reason):
    raw, _, coverage = archive()
    row = dict(records(raw)[1149], n_evaluated_null_reason=reason)
    coverage = _issue_coverage(raw_json(row) + b"\n", "PRIVATE-BAD-REASON", _HOST_TOKEN)
    with pytest.raises(ValueError, match="attempt_field_missing_or_invalid"):
        validate_attempt_fields(
            row, mode="historical_replay", trusted_coverage=coverage
        )


def test_caller_coverage_and_rehashed_mutation_cannot_expand_adoption():
    raw, witness, coverage = archive()
    with pytest.raises(ValueError, match="trusted_archive_coverage_required"):
        replay_approved_archive(
            raw, trusted_release={"approved": True}, witness=witness
        )
    changed = rewrite(raw, lambda rows: rows[1149].update(n_evaluated=0))
    with pytest.raises(ValueError, match="approved_archive_bytes_mismatch"):
        replay_approved_archive(changed, trusted_release=coverage, witness=witness)
    with pytest.raises(ValueError, match="attempt_field_missing_or_invalid"):
        state(records(raw))


def test_witness_and_hash_integrity_remain_required():
    raw, witness, coverage = archive()
    with pytest.raises(ValueError, match="tail_or_high_water_mismatch"):
        replay_approved_archive(
            raw, trusted_release=coverage, witness=dict(witness, N=0)
        )
    with pytest.raises(ValueError):
        replay_approved_archive(
            raw.replace(b"\n", b"\r\n"), trusted_release=coverage, witness=witness
        )
