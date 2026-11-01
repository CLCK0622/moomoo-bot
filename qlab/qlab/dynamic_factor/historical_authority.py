"""Explicit v4 fixtures for historical diagnostics; never a formal loader."""

import json

from .authority_ledger import FIXTURES, PUBLISHED
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
