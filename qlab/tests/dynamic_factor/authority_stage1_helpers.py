"""Private synthetic host fixtures; never a production approval source."""

import json

from qlab.dynamic_factor.authority_ledger import FIXTURES, FIELDS, records, state
from qlab.dynamic_factor.authority_record_types import _issue_coverage, _HOST_TOKEN
from qlab.dynamic_factor.contract import canonical, digest, sha256


def archive(unknowns=101):
    rows = records((FIXTURES / "EVO891-B-ledger-v2.jsonl").read_bytes())
    count = state(rows)["N"]
    while len(rows) < 1149:
        rows.append(
            dict(
                event="gap_update",
                seq=len(rows),
                previous_hash=digest(rows[-1]),
                gap_id="PRIVATE-PADDING",
                status="open",
            )
        )
    for index in range(unknowns):
        contribution = 10 if index < unknowns - 1 else 1238 - 10 * (unknowns - 1)
        count += contribution
        row = dict(
            event="attempt",
            seq=len(rows),
            previous_hash=digest(rows[-1]),
            attempt_id="PRIVATE-UNKNOWN-" + str(index),
            run_id="PRIVATE-HOST-FIXTURE",
            n_trials_total=1,
            n_evaluated=None,
            n_evaluated_null_reason="original evaluation count not recoverable",
            n_contribution=contribution,
            n_after=count,
            scope_labels=["UNKNOWN"],
            evidence=[{"sha256": "a" * 64}],
            performance_viewed=True,
        )
        rows.append(row)
        rows.append(
            dict(
                event="checkpoint",
                seq=len(rows),
                previous_hash=digest(rows[-1]),
                N=count,
                n_high_water=count,
            )
        )
        if index == 0:
            for suffix in range(2):
                rows.append(
                    dict(
                        event="gap_update",
                        seq=len(rows),
                        previous_hash=digest(rows[-1]),
                        gap_id="PRIVATE-INTERVAL-" + str(suffix),
                        status="open",
                    )
                )
    raw = b"".join(canonical(row) + b"\n" for row in rows)
    coverage = _issue_coverage(raw, "PRIVATE-SYNTHETIC-ADOPTION", _HOST_TOKEN)
    current = state(rows, trusted_coverage=coverage)
    witness = {key: current[key] for key in FIELDS}
    witness.update(
        ledger_file="EVO891-B-ledger-v2.jsonl", ledger_file_sha256=sha256(raw)
    )
    return raw, witness, coverage


def rewrite(raw, mutate):
    rows = records(raw)
    mutate(rows)
    for index, row in enumerate(rows[1:], 1):
        row["previous_hash"] = digest(rows[index - 1])
    return b"".join(canonical(row) + b"\n" for row in rows)


def raw_json(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
