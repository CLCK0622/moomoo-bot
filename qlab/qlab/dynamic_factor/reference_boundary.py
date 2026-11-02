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
            validate_packet(expected["guard"], actor, packet, policy, scope=expected)
        request["reference_proofs"] = reference_proofs
    return request


def run_isolated(
    root,
    request,
    *,
    host_context=None,
    installed_snapshot=None,
    run_pin=None,
    arm_tag=None,
    input_preparation=None,
):
    """No inherited credentials, user site, PYTHONPATH, callback or extra FDs.

    Imports finish before the worker installs its audit hook. Pinned static
    source has no data reads before that hook. Returns only preparation evidence.
    """
    from .reference_check import static_proof

    if input_preparation is not None:
        if any(
            v is not None for v in (host_context, installed_snapshot, run_pin, arm_tag)
        ):
            raise ValueError("execution_input.preparation_is_not_authority_reception")
        return _run_input_preparation(root, request, input_preparation)

    expected_authority_binding = None
    if any(
        value is not None
        for value in (host_context, installed_snapshot, run_pin, arm_tag)
    ):
        from .authority_binding import make_worker_binding

        if "authority_binding" in request:
            raise ValueError("ledger.worker_authority_unbound")
        expected_authority_binding = make_worker_binding(
            host_context, installed_snapshot, run_pin, arm_tag
        )
        request = dict(request, authority_binding=expected_authority_binding)
    elif "authority_binding" in request:
        raise ValueError("ledger.worker_authority_unbound")
    static_proof()
    package = str(Path(__file__).resolve().parents[2])
    module = (
        "reference_producer_v3"
        if request.get("profile_binding", {}).get("conventions_version") == "v3.0.0"
        else "reference_producer"
    )
    mechanisms = None
    if module == "reference_producer_v3":
        from .reference_noncash import mechanism_bindings

        mechanisms = mechanism_bindings()
    bootstrap = (
        "import sys;sys.dont_write_bytecode=True;sys.path.insert(0,"
        + repr(package)
        + ");from qlab.dynamic_factor."
        + module
        + " import main;raise SystemExit(main("
        + repr(mechanisms)
        + "))"
        if mechanisms is not None
        else "import sys;sys.dont_write_bytecode=True;sys.path.insert(0,"
        + repr(package)
        + ");from qlab.dynamic_factor."
        + module
        + " import main;raise SystemExit(main())"
    )
    if expected_authority_binding is not None:
        bootstrap = (
            "import sys;sys.dont_write_bytecode=True;sys.path.insert(0,"
            + repr(package)
            + ");from qlab.dynamic_factor.authority_binding import bind_stdin;bind_stdin("
            + repr(expected_authority_binding)
            + ");"
            + bootstrap
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
    if expected_authority_binding is not None:
        from .authority_host import check_pin

        check_pin(host_context, run_pin, arm_tag)
        report["authority_binding_sha256"] = expected_authority_binding[
            "binding_sha256"
        ]
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
        "seal_status": "seal_pending",
    }
    report["seal_status"] = "seal_pending"
    return report


def prepare_execution_inputs(profile, scope, manifest, **expected):
    """Apply the original B guard before issuing a diagnostic read capability."""
    from .execution_receipts.input_run import prepare

    return prepare(profile, scope, manifest, **expected)


def _run_input_preparation(root, request, preparation):
    from .execution_receipts.input_run import read_preparation
    from .reference_check import static_proof
    from .contract import canonical

    owned, expected = read_preparation(preparation)
    if canonical(request) != canonical(owned):
        raise ValueError("execution_input.host_request_binding_mismatch")
    proof = static_proof()
    package = str(Path(__file__).resolve().parents[2])
    bootstrap = (
        "import sys;sys.dont_write_bytecode=True;sys.path.insert(0,"
        + repr(package)
        + ");from qlab.dynamic_factor.reference_producer_v3 import execution_main;"
        + "raise SystemExit(execution_main("
        + repr(expected)
        + "))"
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
        input=json.dumps(owned, allow_nan=False) + "\n",
        capture_output=True,
        text=True,
        cwd=str(Path(root).resolve()),
        env={},
        close_fds=True,
        timeout=30,
    )
    if child.returncode != 2 or child.stderr:
        raise ValueError("reference.isolated_worker_failed")
    from .execution_receipts.input_data import strict_json

    report = strict_json(child.stdout)
    fields = {
        "schema",
        "transport_complete",
        "economic_content_validated",
        "accounting_executed",
        "evidence_accepted",
        "seal_status",
        "complete",
        "returns",
        "sr",
        "reason",
        "runtime_consumable",
        "certifiable",
        "accessed_roles",
        "reader_calls",
    }
    if type(report) is not dict or type(report.get("transport_complete")) is not bool:
        raise ValueError("execution_input.unexpected_worker_output")
    if report["transport_complete"]:
        fields |= {"run_id", "book_id", "member_id", "manifest_sha256", "data"}
    if (
        set(report) != fields
        or report.get("schema") != "EVO884.ExecutionInputTransport/v1"
        or report.get("seal_status") != "seal_pending"
        or report.get("returns") is not None
        or report.get("sr") is not None
        or any(
            report.get(k) is not False
            for k in (
                "economic_content_validated",
                "accounting_executed",
                "evidence_accepted",
                "complete",
                "runtime_consumable",
                "certifiable",
            )
        )
        or type(report.get("accessed_roles")) is not list
        or any(type(role) is not str for role in report["accessed_roles"])
        or not set(report["accessed_roles"]).issubset({"raw", "rights", "adv", "cash"})
        or len(report["accessed_roles"]) != len(set(report["accessed_roles"]))
        or type(report.get("reader_calls")) is not int
        or report.get("reader_calls") != len(report["accessed_roles"])
    ):
        raise ValueError("execution_input.unexpected_worker_output")
    if report.get("transport_complete") is True and (
        any(
            report.get(k) != expected[k]
            for k in ("run_id", "book_id", "member_id", "manifest_sha256")
        )
        or report["accessed_roles"] != ["raw", "rights", "adv", "cash"]
    ):
        raise ValueError("execution_input.worker_object_binding_mismatch")
    report["access_boundary_receipt"] = dict(
        schema="EVO884.ExecutionInputBoundary/v1",
        preparation_request_sha256=expected["request_sha256"],
        worker_source_sha256=proof["source_sha256"],
        declared_input_manifest=owned["manifest"],
        source_acceptance="not_checked",
        input_file_sha256={
            k: v["sha256"] for k, v in owned["manifest"]["inputs"].items()
        },
        declared_source_receipt_sha256={
            k: v["source_receipt_sha256"]
            for k, v in owned["manifest"]["inputs"].items()
        },
        accessed_roles=report["accessed_roles"],
        isolated_child=True,
        seal_status="seal_pending",
    )
    return report
