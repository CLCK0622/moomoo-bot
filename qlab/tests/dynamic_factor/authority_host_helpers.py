"""Synthetic approved-source adapter for exercising real public receivers.

No fixture can be selected by production requests. Replacing this private host
source is a test assumption, not a grant of deployment/installation permission.
"""

from copy import deepcopy
from pathlib import Path
import sys
from types import SimpleNamespace

from qlab.dynamic_factor import authority_host as host
from qlab.dynamic_factor.authority_ledger import (
    replay_approved_archive,
    state,
    records,
    PUBLISHED,
    SOURCE_SHA,
)
from qlab.dynamic_factor.contract import sha256
from qlab.dynamic_factor.reception_schema import contract
from authority_stage1_helpers import archive, raw_json


def private_host(tmp_path, monkeypatch, *, complete=False, prefix_stub=True):
    raw, witness, coverage = archive()
    chain = tmp_path / "ledger.jsonl"
    witness_path = tmp_path / "witness.json"
    chain.write_bytes(raw)
    witness_path.write_bytes(raw_json(witness))
    module_path = (
        Path(__file__).resolve().parents[2] / "qlab/dynamic_factor/authority_ledger.py"
    )
    cur = state(records(raw), trusted_coverage=coverage)
    identities = dict.fromkeys(
        contract("N-01.v3.schema.json")["properties"]["input_identities"]["required"],
        "a" * 64,
    )
    identities.update(
        ledger_id=cur["ledger_id"],
        genesis_sha256=cur["genesis_sha256"],
        tip=cur["tip"],
        chain_sha256=sha256(raw),
        witness_sha256=sha256(witness_path.read_bytes()),
        sequence=cur["sequence"],
        host_deployment_id="PRIVATE-DEPLOYMENT",
        deployment_commit="4cdfcbc0726abeadfff9e143b49281fab815bc43",
        freeze_manifest_version="PRIVATE-APPROVED-FREEZE",
        canonical_chain_realpath=str(chain.resolve()),
        canonical_witness_realpath=str(witness_path.resolve()),
        module_realpath=str(module_path),
        reader_source_sha256=sha256(module_path.read_bytes()),
    )
    reconciliation = (
        b"PRIVATE_APPROVED_RECONCILIATION_FOR_ALL_101_ROWS" if complete else None
    )
    projection = dict(
        arm_tag="EVO883_FACTOR",
        complete=complete,
        relevant_unknowns=0 if complete else 101,
        reconciliation_sha256=sha256(reconciliation) if reconciliation else None,
        acceptance_version="PRIVATE-1",
        N_rows=[
            dict(
                role="PRIMARY_GATE",
                basis="N_config_own_arm",
                value=7 if complete else None,
                known=complete,
            ),
            dict(
                role="SENSITIVITY",
                basis="N_generation_requests_own_arm",
                value=101,
                known=True,
            ),
        ],
    )
    source = dict(
        source_verified=True,
        approval_bytes=raw_json({"approval": "PRIVATE-AUTHORITY"}),
        projection_bytes=raw_json(projection),
        published_anchor_bytes=raw_json(dict(PUBLISHED, ledger_file_sha256=SOURCE_SHA)),
        chain_raw=raw,
        witness=witness,
        identities=identities,
        anchor=dict(PUBLISHED, ledger_file_sha256=SOURCE_SHA),
        observation={},
        module_path=str(module_path),
        module_sha256=sha256(module_path.read_bytes()),
        chain_path=str(chain.resolve()),
        chain_sha256=sha256(raw),
        witness_path=str(witness_path.resolve()),
        witness_sha256=sha256(witness_path.read_bytes()),
        reconciliation_bytes=reconciliation,
        diagnostic_snapshot=dict(
            genesis=records(raw)[0],
            events=records(raw)[1:],
            recorded_N=1313,
            n_high_water=1313,
            authority_tip=cur["tip"],
            n_ledger_hash=cur["snapshot_sha256"],
            reasons=["ledger_history_incomplete"],
        ),
    )
    monkeypatch.setattr(host, "_read_approved_deployment", lambda: deepcopy(source))
    if prefix_stub:
        # Unit tests of the N adapter isolate the separately owned V5 function.
        # The joint receiver harness must explicitly disable this stub.
        monkeypatch.setitem(
            sys.modules,
            "qlab.dynamic_factor.authority_prefix",
            SimpleNamespace(
                verify_anchor_prefix=lambda *args: {"status": "PASS", "reasons": []}
            ),
        )
    context = host.open_host_context()
    replay = replay_approved_archive(raw, trusted_release=coverage, witness=witness)
    snapshot = host._retain_snapshot(context, {"accepted": True}, replay, coverage)
    pin = host.pin_run(context, arm_tag="EVO883_FACTOR", run_id="PRIVATE-RUN")
    return context, snapshot, pin, source
