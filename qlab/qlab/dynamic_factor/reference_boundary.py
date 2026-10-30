"""Host-side capability construction. No current-result reader or evaluator."""

import json
import subprocess
import sys
from pathlib import Path

from .contract import digest, sha256
from .fold_split import reference_view, train_dates


def calendar_sha(dates):
    return sha256("".join(d + "\n" for d in dates).encode())


def prepare_request(
    policy,
    fold,
    candidate_view,
    input_bindings,
    *,
    sealed_scope=None,
    sealed_manifest=None,
    reference_proofs=None,
):
    from .reference_check import verify_registry

    from .reference_registry import artifact, DISPATCH, member_spec, registered_request

    if policy.document["version"] == "v3.0.0":
        from .reference_registry_v3 import (
            artifact,
            DISPATCH,
            member_spec,
            registered_request,
        )
    r = registered_request()
    verify_registry(r["registry"], r["manifests"], policy, None)
    train, warmup = reference_view(candidate_view, fold, train_dates)
    declared = next(
        f
        for f in artifact("fold-bindings.json")["document"]["folds"]
        if str(f["fold_id"]) == str(fold["fold_id"])
    )
    for key, dates in (("train", train), ("warmup", warmup)):
        if calendar_sha(dates) != declared[key + "_calendar_sha256"]:
            raise ValueError("reference.only_complete_train_warmup_visible")
    receipt = {
        "fold_id": str(fold["fold_id"]),
        "fold_definition_sha256": digest(fold),
        "shared_object_verified": True,
        "splitter_source_sha256": sha256(
            (Path(__file__).parent / "fold_split.py").read_bytes()
        ),
        "train_days": declared["train_session_count"],
        "warmup_days": declared["warmup_sessions"],
        "train_calendar_sha256": declared["train_calendar_sha256"],
        "warmup_calendar_sha256": declared["warmup_calendar_sha256"],
    }
    request = {
        "view": {"train": list(train), "warmup": list(warmup), "receipt": receipt},
        "inputs": input_bindings,
        "profile_binding": {
            k: policy.binding[k]
            for k in (
                "conventions_version",
                "conventions_sha256",
                "prereg_sha256",
                "common_profile_sha256",
            )
        },
        "dispatch": {m: member_spec(m) for m in sorted(DISPATCH)},
    }
    if policy.document["version"] == "v3.0.0":
        from .reference_compile_v3 import seal_scope

        if sealed_manifest is None:
            raise ValueError("reference.shared_v3_scope_required")
        expected = seal_scope(sealed_manifest, train, warmup, policy)
        if sealed_scope is not None and sealed_scope != expected:
            raise ValueError("reference.same_B_and_E_t_required")
        request["sealed_scope"] = expected
        from .reference_noncash import actors, validate_packet

        if not isinstance(reference_proofs, dict) or set(reference_proofs) != set(
            actors()
        ):
            raise ValueError("reference.separate_three_proofs_required")
        for actor, packet in reference_proofs.items():
            validate_packet(expected["guard"], actor, packet, policy)
        request["reference_proofs"] = reference_proofs
    return request


def run_isolated(root, request):
    """No inherited credentials, user site, PYTHONPATH, callback or extra FDs.

    Imports finish before the worker installs its audit hook. Pinned static
    source has no data reads before that hook. Returns only preparation evidence.
    """
    from .reference_check import static_proof

    static_proof()
    package = str(Path(__file__).resolve().parents[2])
    module = (
        "reference_producer_v3"
        if request.get("profile_binding", {}).get("conventions_version") == "v3.0.0"
        else "reference_producer"
    )
    bootstrap = (
        "import sys;sys.dont_write_bytecode=True;sys.path.insert(0,"
        + repr(package)
        + ");from qlab.dynamic_factor."
        + module
        + " import main;raise SystemExit(main())"
    )
    child = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-c",
            bootstrap,
            "--inputs-root",
            str(Path(root).resolve()),
        ],
        input=json.dumps(request, allow_nan=False) + "\n",
        capture_output=True,
        text=True,
        cwd=str(Path(root).resolve()),
        env={},
        close_fds=True,
        timeout=30,
    )
    if child.returncode != 2:
        raise ValueError("reference.isolated_worker_failed")
    report = json.loads(child.stdout)
    if (
        report.get("returns") is not None
        or report.get("runtime_consumable") is not False
    ):
        raise ValueError("reference.unexpected_performance_output")
    from .reference_evidence import lineage_sources

    sources = lineage_sources()
    report["access_boundary_receipt"] = {
        "producer_code_sha256": digest(sources),
        "guard_source_sha256": sources["reference_guard.py"],
        "accessed_roles": report.get("accessed_roles", []),
        "input_file_sha256": {r: b["sha256"] for r, b in request["inputs"].items()},
        "shared_view_receipt_sha256": digest(request["view"]["receipt"]),
        "isolated_child": True,
    }
    return report
