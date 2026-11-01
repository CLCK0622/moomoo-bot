"""Synthetic source observations for the actual N03 receiver."""

from copy import deepcopy
from pathlib import Path
import json
import sys
from types import SimpleNamespace

from qlab.dynamic_factor import authority_host as host
from qlab.dynamic_factor.contract import digest, sha256
from authority_host_helpers import private_host
from authority_stage1_helpers import raw_json


def installation_host(tmp_path, monkeypatch, *, source_fail=None, prefix_stub=True):
    context, snapshot, pin, source = private_host(
        tmp_path, monkeypatch, prefix_stub=prefix_stub
    )
    # Discard the unit N01 assumption: this fixture must mint its snapshot by
    # executing verify_installation_readonly, not by trusting receipt JSON.
    replay = host._SNAPSHOTS.pop(snapshot)[2]
    document = json.loads(
        (
            Path(__file__).parent
            / "fixtures/authority-stage1/private-installation.json"
        ).read_bytes()
    )
    raw = source["chain_raw"]
    witness = source["witness"]
    current = source["identities"]
    deployment = document["deploy_root"]
    deployment.update(
        deploy_root_realpath=str(tmp_path.resolve()),
        project_root_realpath=str(tmp_path.resolve()),
        module_realpath=source["module_path"],
        module_sha256=source["module_sha256"],
        deploy_commit=current["deployment_commit"],
    )
    ledger = document["ledger"]
    ledger.update(
        ledger_path=source["chain_path"],
        ledger_sha256=sha256(raw),
        ledger_bytes=len(raw),
        source_archive_path=source["chain_path"],
        source_archive_sha256=sha256(raw),
        sequence=witness["sequence"],
        tip=witness["tip"],
        N=witness["N"],
        n_high_water=witness["n_high_water"],
        snapshot_sha256=witness["snapshot_sha256"],
        genesis_sha256=witness["genesis_sha256"],
        ledger_id=witness["ledger_id"],
    )
    document["witness"].update(
        witness_path=source["witness_path"],
        witness_sha256=source["witness_sha256"],
        witness_fields=deepcopy(witness),
    )
    document["readback"]["nonauthor_readback_agent_id"] = (
        "11111111-1111-4111-8111-111111111111"
    )
    source["anchor"] = {
        key: witness[key] for key in ("ledger_id", "sequence", "tip", "n_high_water")
    }
    source["anchor"]["ledger_file_sha256"] = sha256(raw)
    source["published_anchor_bytes"] = raw_json(source["anchor"])
    source["identities"]["anchor_sha256"] = sha256(source["published_anchor_bytes"])
    source["observation"].update(
        anchor_raw=source["published_anchor_bytes"],
        anchor_ref="sha256:" + sha256(source["published_anchor_bytes"]),
        anchor_payload_sha256=sha256(source["published_anchor_bytes"]),
        approved_anchor_sha256=sha256(source["published_anchor_bytes"]),
    )

    document["anchor"]["anchor_bytes_sha256"] = sha256(source["published_anchor_bytes"])
    document["anchor"]["anchor_L2_path"] = str(
        tmp_path / "published-authority-tip.json"
    )
    document["approved_release"].update(
        L1_anchor_file_sha256=sha256(source["published_anchor_bytes"]),
        L2_path=document["anchor"]["anchor_L2_path"],
        sequence=witness["sequence"],
        archive_bytes=len(raw),
        archive_sha256=sha256(raw),
        release_id="EVO891-B@seq" + str(witness["sequence"]),
    )
    document["t1"]["null_rows_seq_range"] = "1149..1351"
    document["t1"]["null_rows_list_sha256"] = digest(replay["unknown_rows"])
    anchor = document["anchor"]
    v1, v2, v3, v4, v6 = [
        anchor[name]["measured"] for name in ("V1", "V2", "V3", "V4", "V6")
    ]
    v1.update(
        L1_artifact_sha256=sha256(source["published_anchor_bytes"]),
        L2_sha256=anchor["anchor_L2_sha256"],
        approved_L2_commit=anchor["anchor_L2_commit"],
        actual_L2_path=anchor["anchor_L2_path"],
        approved_release_sha256=source["identities"]["approved_release_sha256"],
        module_sha256=source["module_sha256"],
    )
    v2.update(
        publication_actor_id=anchor["anchor_L1_author_id"],
        revision=anchor["anchor_L1_revision"],
        current_release_sha256=source["identities"]["approved_release_sha256"],
    )
    v3.update(
        L1_created_at_utc=anchor["anchor_L1_created_at"],
        installation_at_utc=document["identity"]["installed_at_utc"],
    )
    v4.update(
        ledger_id=witness["ledger_id"],
        anchor_sequence=source["anchor"]["sequence"],
        observed_prefix_sequence=source["anchor"]["sequence"],
        tip=source["anchor"]["tip"],
        n_high_water=source["anchor"]["n_high_water"],
    )
    v6.update(
        ledger_id=witness["ledger_id"],
        genesis_sha256=witness["genesis_sha256"],
        current_sequence=witness["sequence"],
        anchor_sequence=source["anchor"]["sequence"],
        current_high_water=witness["n_high_water"],
        anchor_high_water=source["anchor"]["n_high_water"],
        chain_sha256=source["chain_sha256"],
        witness_sha256=source["witness_sha256"],
        current_release_sha256=source["identities"]["approved_release_sha256"],
    )
    readback = document["readback"]["nonauthor_readback_result"]["measured"]
    for group in ("deploy_root", "ledger", "witness", "anchor"):
        for key, value in document[group].items():
            if key in readback:
                readback[key] = deepcopy(value)

    # V5 is stubbed only in focused tests owned by the N receiver author.
    # Joint tests replace these observations with the real shared result.
    prefix = document["v5_mandatory_check"]["formal_reception"]
    if not prefix_stub:
        from qlab.dynamic_factor.authority_prefix import verify_anchor_prefix

        prefix = verify_anchor_prefix(
            source["chain_raw"], source["anchor"], source["observation"]
        )
        assert prefix["status"] == "PASS", prefix["reasons"]
        for phase in ("install", "formal_reception", "readback"):
            document["v5_mandatory_check"][phase] = deepcopy(prefix)
    document["anchor"]["V5"] = deepcopy(prefix)

    if prefix_stub:
        monkeypatch.setitem(
            sys.modules,
            "qlab.dynamic_factor.authority_prefix",
            SimpleNamespace(verify_anchor_prefix=lambda *args: deepcopy(prefix)),
        )
    source.update(
        installation_receipt_bytes=raw_json(document),
        installation_acceptance_bytes=source["approval_bytes"],
        installation_operation="PRIVATE-INSTALLATION-OBSERVATION",
        release_verified=True,
        coverage_ref="PRIVATE-SYNTHETIC-ADOPTION",
        independent_groups=deepcopy(document),
        independent_group_results={
            name: {
                "status": "PASS",
                "evidence_refs": [
                    "sha256:" + digest(["PRIVATE-INDEPENDENT-SOURCE", name])
                ],
            }
            for name in document
        },
    )
    if source_fail:
        source["independent_group_results"][source_fail]["status"] = "FAIL"
    monkeypatch.setattr(host, "_read_approved_deployment", lambda: deepcopy(source))
    context = host.open_host_context()
    return context, source, document
