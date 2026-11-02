"""Explicit v4 fixtures for historical diagnostics; never a formal loader."""

import json

from .authority_ledger import (
    AuthorityLedger,
    FIXTURES,
    PROJECT_LEDGER,
    PUBLISHED,
    verify_ancestor,
)
from .contract import is_sha


HISTORICAL_V4_FIXTURES = FIXTURES.parent / "evo893"
HISTORICAL_V4_WITNESS_INPUT = HISTORICAL_V4_FIXTURES / "EVO891-B-ledger-v4.tip.json"


def historical_v4_witness():
    try:
        witness = json.loads(HISTORICAL_V4_WITNESS_INPUT.read_bytes())
        if (
            witness.get("ledger_id") != PUBLISHED["ledger_id"]
            or type(witness.get("sequence")) is not int
            or witness["sequence"] <= PUBLISHED["sequence"]
            or type(witness.get("n_high_water")) is not int
            or witness["n_high_water"] < PUBLISHED["n_high_water"]
            or not is_sha(witness.get("tip"))
            or not is_sha(witness.get("ledger_file_sha256"))
        ):
            raise ValueError
        return {key: witness[key] for key in PUBLISHED}
    except (OSError, TypeError, KeyError, ValueError):
        raise ValueError("ledger.historical_v4_witness_missing_or_invalid") from None


HISTORICAL_V4_PUBLISHED = historical_v4_witness()
HISTORICAL_V4_SOURCE_SHA = json.loads(HISTORICAL_V4_WITNESS_INPUT.read_bytes())[
    "ledger_file_sha256"
]


def historical_diagnostic_snapshot(ledger):
    """Frozen D input record, explicitly relative to the historical v4 cut.

    The legacy field names current_published_anchor/is_current_authority mean
    current *at that frozen cut*, not current deployment authority. This whole
    historical record is used only by the permanently diagnostic omitted-label
    public route. It is built from verified original rows, not by deleting
    provenance fields from the current snapshot or substituting a stored hash.
    Canonical project objects cannot enter this historical reader.
    """
    if type(ledger) is not AuthorityLedger or (
        ledger.path.resolve() == PROJECT_LEDGER.resolve()
    ):
        raise ValueError("ledger.historical_diagnostic_only")
    try:
        cur, rows, _ = ledger._verify()
        anchor = historical_v4_witness()
        try:
            verify_ancestor(rows, anchor)
            at_historical_cut = True
        except ValueError:
            at_historical_cut = False
        return {
            "authority_ledger": True,
            "genesis": rows[0],
            "events": rows[1:],
            "recorded_N": cur["N"],
            "n_high_water": cur["n_high_water"],
            "authority_tip": cur["tip"],
            "authority_sequence": cur["sequence"],
            "local_attempts_n": None,
            "local_counted_n": None,
            "cumulative_n": None,
            "cumulative_n_lower_bound": cur["n_high_water"],
            "n_complete": False,
            "complete_N": None,
            "n_ledger_hash": cur["snapshot_sha256"],
            "certifiable": False,
            "reasons": ["ledger_history_incomplete"]
            + (
                []
                if at_historical_cut
                else ["ledger.archival_snapshot_below_current_anchor"]
            ),
            "external_anchor": dict(PUBLISHED),
            "current_published_anchor": anchor,
            "is_current_authority": at_historical_cut,
        }
    except (ValueError, KeyError, TypeError, OSError):
        return {
            "genesis": None,
            "events": None,
            "cumulative_n": None,
            "cumulative_n_lower_bound": None,
            "n_ledger_hash": None,
            "certifiable": False,
            "reasons": ["ledger_unreadable_or_corrupt"],
        }
