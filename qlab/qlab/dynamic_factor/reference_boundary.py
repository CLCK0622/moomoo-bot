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


def run_execution_result(observation, *, input_read=None):
    """A separate nonempty diagnostic channel; old preparation stays empty.

    No JSON result, current candidate/meta output or evaluator is accepted.
    The worker replays only the immutable fact program issued by the owned book
    and must reproduce its full C07 result. No caller return vector is sent.
    """
    from .execution_receipts.reference_result import (
        read_observation,
        read_program,
        read_release,
    )
    from .scope_proof import reference_execution_proof
    from .conventions import load_conventions
    from .contract import canonical

    document, expected_sha256 = read_observation(observation)
    program, expected_program_sha256 = read_program(observation)
    context, identity = read_release(observation)
    preflight = (
        None
        if identity is None
        else dict(
            scope={"guard": program["initial"]["history"]["guard"]},
            identity_bytes=identity,
            a_raw=context.a_raw,
        )
    )
    facts = binding = None
    if input_read is not None:
        from .execution_receipts.input_facts import read_facts, bind_program

        facts, facts_sha256 = read_facts(input_read)
        binding = bind_program(
            program,
            facts,
            release_context=context,
            expected_release_identity_bytes=identity,
        )
    proof = reference_execution_proof(load_conventions())
    source_root = Path(__file__).parent
    expected_reads = {
        str((source_root / name).resolve()): value
        for name, value in proof["C09_C10"]["replay_file_sha256"].items()
    }
    package = str(Path(__file__).resolve().parents[2])
    bootstrap = (
        "import sys;sys.dont_write_bytecode=True;sys.path.insert(0,"
        + repr(package)
        + ");from qlab.dynamic_factor.reference_producer_v3 import result_main;"
        + "raise SystemExit(result_main("
        + repr(expected_sha256)
        + ","
        + repr(expected_program_sha256)
        + ","
        + repr(expected_reads)
        + ","
        + repr(facts_sha256 if facts is not None else None)
        + ","
        + repr(preflight)
        + "))"
    )
    child = subprocess.run(
        [sys.executable, "-I", "-S", "-c", bootstrap],
        input=canonical(
            dict(program=program, facts=facts) if facts is not None else program
        ).decode()
        + "\n",
        capture_output=True,
        text=True,
        env={},
        close_fds=True,
        timeout=600,
    )
    if child.returncode != 0 or child.stderr:
        raise ValueError(
            "reference.result_worker_failed:"
            + child.stdout[-500:]
            + child.stderr[-500:]
        )
    from .execution_receipts.input_data import strict_json

    report = strict_json(child.stdout)
    expected = dict(
        schema="EVO884.ReferenceResultTransport/v1",
        observation=document,
        observation_sha256=expected_sha256,
        accessed_roles=[],
        reader_calls=0,
        worker_role="reference_diagnostic_execution",
        execution_steps=len(program["operations"]),
        protocol_read_paths=report.get("protocol_read_paths"),
        seal_status="seal_pending",
        runtime_consumable=False,
        certifiable=False,
    )
    if binding is not None:
        expected["input_fact_binding"] = binding
    if identity is not None:
        expected.update(
            schema="EVO884.ReferenceResultTransport/v1-BR1",
            release_context_binding=json.loads(identity),
        )
    if (
        canonical(report) != canonical(expected)
        or type(report["protocol_read_paths"]) is not list
        or len(report["protocol_read_paths"]) != len(set(report["protocol_read_paths"]))
        or not set(report["protocol_read_paths"]) <= set(expected_reads)
    ):
        raise ValueError("reference.unexpected_result_worker_output")
    # Check the actual owned account again after the child exits.
    if read_observation(observation)[1] != expected_sha256:
        raise ValueError("reference.observation_account_drift")
    if read_release(observation)[1] != identity:
        raise ValueError("B.release_context_persistent_identity_mismatch")
    report["source_proof_sha256"] = digest(proof)
    return report


def read_execution_inputs(root, preparation):
    """Owned four-file read; diagnostic only, not SRC/AUTH permission."""
    from .execution_receipts.input_facts import read_files

    return read_files(root, preparation)


def run_execution_family(observations, *, input_reads=None):
    """Closed four-member family; bind the entire batch before any child."""
    from .execution_receipts.reference_result import read_observation
    from .reference_registry_v3 import DISPATCH

    if type(observations) is not dict or set(observations) != set(DISPATCH):
        raise ValueError("reference.closed_four_owned_observations_required")
    documents = {
        member: read_observation(cap)[0] for member, cap in observations.items()
    }
    first = documents[sorted(DISPATCH)[0]]
    if (
        len({d["book_id"] for d in documents.values()}) != 4
        or len({d["scope"]["attempt_id"] for d in documents.values()}) != 4
        or any(
            d["scope"]["member_id"] != member
            or d["scope"]["fold_id"] != first["scope"]["fold_id"]
            or d["run_id"] != first["run_id"]
            or d["dates"] != first["dates"]
            or d["benchmark_sha256"] != first["benchmark_sha256"]
            or d["shared_guard_sha256"] != first["shared_guard_sha256"]
            or d["eligibility_by_close"] != first["eligibility_by_close"]
            or d["DAG"]["sources"] != first["DAG"]["sources"]
            or d["execution_closure_sha256"] != first["execution_closure_sha256"]
            or d["clock_ruling_sha256"] != first["clock_ruling_sha256"]
            for member, d in documents.items()
        )
    ):
        raise ValueError("reference.separate_books_same_family_binding_required")
    if input_reads is not None:
        from .execution_receipts.input_facts import read_facts, bind_program
        from .execution_receipts.reference_result import read_program, read_release

        if type(input_reads) is not dict or set(input_reads) != set(DISPATCH):
            raise ValueError("reference.closed_four_owned_input_reads_required")
        # Preflight every member before the first result child. A missing or
        # foreign read capability cannot silently take the diagnostic fallback.
        for member in sorted(DISPATCH):
            context, identity = read_release(observations[member])
            bind_program(
                read_program(observations[member])[0],
                read_facts(input_reads[member])[0],
                release_context=context,
                expected_release_identity_bytes=identity,
            )
    outputs = {
        m: run_execution_result(observations[m], input_read=input_reads[m])
        if input_reads is not None
        else run_execution_result(observations[m])
        for m in sorted(DISPATCH)
    }
    return dict(
        schema="EVO884.ReferenceExecutionFamily/v1",
        run_id=first["run_id"],
        fold_id=first["scope"]["fold_id"],
        outputs=outputs,
        seal_status="seal_pending",
        execution_verified=False,
        runtime_consumable=False,
        certifiable=False,
    )


def _run_input_preparation(root, request, preparation):
    from .execution_receipts.input_run import (
        read_preparation,
        read_context,
        read_release,
    )
    from .reference_check import static_proof
    from .contract import canonical

    owned, expected = read_preparation(preparation)
    context, identity = read_release(preparation)
    if identity is not None:
        expected = dict(
            expected,
            release_preflight=dict(
                scope=read_context(preparation)[1],
                identity_bytes=identity,
                a_raw=context.a_raw,
            ),
        )
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
        if identity is not None:
            fields.add("release_context_binding")
            if report.get("release_context_binding") != json.loads(identity):
                raise ValueError("B.release_context_persistent_identity_mismatch")
    if (
        set(report) != fields
        or report.get("schema")
        != "EVO884.ExecutionInputTransport/v1"
        + ("-BR1" if identity is not None and report["transport_complete"] else "")
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
    if identity is not None:
        if read_release(preparation)[1] != identity:
            raise ValueError("B.release_context_persistent_identity_mismatch")
        report["access_boundary_receipt"].update(
            schema="EVO884.ExecutionInputBoundary/v1-BR1",
            release_context_binding=json.loads(identity),
        )
    return report
