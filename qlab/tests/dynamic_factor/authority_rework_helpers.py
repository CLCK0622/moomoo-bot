"""B21R historical specimens and observed semantic stops, test-only."""

from collections import Counter
from copy import deepcopy
import gzip
import json
from pathlib import Path
import sys

from qlab.dynamic_factor import authority_host as host
from qlab.dynamic_factor.authority_ledger import FIELDS, records, state
from qlab.dynamic_factor.authority_record_types import _issue_coverage, _HOST_TOKEN
from qlab.dynamic_factor.contract import canonical, digest, sha256
from authority_stage1_helpers import raw_json


FIXTURES = Path(__file__).parent / "fixtures/authority-stage1/b21r"
CALLS = {
    ("authority_install_receipt.py", "validate_receipt"),
    ("authority_install_receipt.py", "validate_anchor"),
    ("reference_inputs.py", "read_inputs"),
    ("scope_reader.py", "read_strategy_inputs"),
    ("reference_boundary.py", "run_isolated"),
}


def fixture_bytes(name):
    manifest = json.loads((FIXTURES / "manifest.json").read_bytes())
    stored = (FIXTURES / name).read_bytes()
    assert sha256(stored) == manifest[name]["stored_sha256"]
    raw = gzip.decompress(stored) if name.endswith(".gz") else stored
    assert sha256(raw) == manifest[name]["original_sha256"]
    assert len(raw) == manifest[name]["original_bytes"]
    return raw


def ruling_archive(*, project_witness=False):
    raw = fixture_bytes("v24.jsonl.gz")
    witness = json.loads(fixture_bytes("v24.tip.json"))
    if project_witness:
        witness["ledger_file"] = "EVO891-B-ledger-v2.jsonl"
    coverage = _issue_coverage(raw, "PRIVATE-B21R-RULING-ARCHIVE", _HOST_TOKEN)
    return raw, witness, coverage


def observed_call(call):
    counts = Counter({name: 0 for _, name in CALLS})
    prior = sys.getprofile()

    def profile(frame, event, arg):
        if (
            event == "call"
            and (Path(frame.f_code.co_filename).name, frame.f_code.co_name) in CALLS
        ):
            counts[frame.f_code.co_name] += 1

    sys.setprofile(profile)
    try:
        result = call()
    finally:
        sys.setprofile(prior)
    return result, dict(counts)


def rebind_private_receipt(source, document, monkeypatch):
    # Only the private test source reissues the operation binding. The current
    # approved publication and independent top-level facts stay unchanged.
    source["independent_groups"] = deepcopy(document)
    source["installation_receipt_bytes"] = raw_json(document)
    monkeypatch.setattr(host, "_read_approved_deployment", lambda: deepcopy(source))
    return host.open_host_context()


def counterfeit_pair(source, *, wrong_branch):
    rows = records(source["chain_raw"])
    if wrong_branch:
        rows[0]["ledger_id"] = "8" * 64
        rows.append(
            dict(
                event="attempt",
                seq=len(rows),
                previous_hash=digest(rows[-1]),
                attempt_id="PRIVATE-WRONG-BRANCH",
                run_id="PRIVATE-NOT-A-RUN",
                n_trials_total=1,
                n_evaluated=1,
                n_contribution=5,
                n_after=1318,
                scope_labels=["SYNTHETIC_ONLY"],
                evidence=[{"sha256": "a" * 64}],
            )
        )
        rows.append(
            dict(
                event="checkpoint",
                seq=len(rows),
                previous_hash=digest(rows[-1]),
                N=1318,
                n_high_water=1318,
            )
        )
    else:
        rows[1149]["n_evaluated_null_reason"] += " PRIVATE-TAMPER"
    for index, row in enumerate(rows[1:], 1):
        row["previous_hash"] = digest(rows[index - 1])
    changed = b"".join(canonical(row) + b"\n" for row in rows)
    private_coverage = _issue_coverage(changed, "PRIVATE-UNADOPTED-PAIR", _HOST_TOKEN)
    current = state(rows, trusted_coverage=private_coverage)
    witness = {key: current[key] for key in FIELDS}
    witness.update(
        ledger_file="EVO891-B-ledger-v2.jsonl", ledger_file_sha256=sha256(changed)
    )
    return changed, witness, current
