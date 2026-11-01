"""Shared strict writes and byte-covered historical unknowns.

Coverage is an opaque host-owned object. Public request dictionaries and receipt
JSON cannot construct it. The private issuer belongs to the reviewed host path;
this is not isolation from an operator replacing that trusted Python code.
"""

from dataclasses import dataclass
from weakref import WeakKeyDictionary

from .contract import canonical, is_sha, sha256


_HOST_TOKEN = object()
_COVERAGES = WeakKeyDictionary()


@dataclass(frozen=True, eq=False)
class TrustedCoverage:
    def __init__(self):
        raise TypeError("ledger.trusted_archive_coverage_required")


def _issue_coverage(raw, provenance, token):
    if (
        token is not _HOST_TOKEN
        or not isinstance(provenance, str)
        or not provenance.strip()
    ):
        raise ValueError("ledger.trusted_archive_coverage_required")
    from .authority_ledger import records

    rows = records(raw)
    coverage = object.__new__(TrustedCoverage)
    _COVERAGES[coverage] = (
        sha256(raw),
        provenance,
        {
            (row.get("seq"), row.get("attempt_id")): sha256(canonical(row))
            for row in rows
            if row.get("event") == "attempt"
        },
    )
    return coverage


def covered_archive(raw, coverage):
    if type(coverage) is not TrustedCoverage or coverage not in _COVERAGES:
        raise ValueError("ledger.trusted_archive_coverage_required")
    identity = _COVERAGES[coverage]
    if identity[0] != sha256(raw):
        raise ValueError("ledger.approved_archive_bytes_mismatch")
    return identity


def validate_attempt_fields(row, *, mode, trusted_coverage):
    from .authority_ledger import ATTEMPT_FIELDS

    if mode not in ("new_write", "historical_replay"):
        raise ValueError("ledger.attempt_field_missing_or_invalid")
    if (
        any(key not in row for key in ATTEMPT_FIELDS)
        or any(
            type(row[key]) is not str or not row[key]
            for key in ("attempt_id", "run_id")
        )
        or type(row["n_trials_total"]) is not int
        or row["n_trials_total"] < 0
        or type(row["evidence"]) is not list
        or not row["evidence"]
        or any(
            type(item) is not dict or not is_sha(item.get("sha256"))
            for item in row["evidence"]
        )
    ):
        raise ValueError("ledger.attempt_field_missing_or_invalid")
    value = row["n_evaluated"]
    if type(value) is int and value >= 0:
        return "KNOWN"
    if value is not None or mode != "historical_replay":
        raise ValueError("ledger.attempt_field_missing_or_invalid")
    if (
        type(trusted_coverage) is not TrustedCoverage
        or trusted_coverage not in _COVERAGES
    ):
        raise ValueError("ledger.trusted_archive_coverage_required")
    identity = _COVERAGES[trusted_coverage]
    key = (row.get("seq"), row.get("attempt_id"))
    if identity[2].get(key) != sha256(canonical(row)):
        raise ValueError("ledger.approved_archive_bytes_mismatch")
    reason = row.get("n_evaluated_null_reason")
    if type(reason) is not str or not reason.strip():
        raise ValueError("ledger.attempt_field_missing_or_invalid")
    contribution = row["n_contribution"]
    if type(contribution) is not int or contribution < max(row["n_trials_total"], 1):
        raise ValueError("ledger.contribution_or_attempt_id_invalid")
    return "CONTROLLED_HISTORICAL_UNKNOWN"
