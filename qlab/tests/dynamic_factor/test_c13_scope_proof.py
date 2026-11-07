"""Actual C13 source mutations over private bytes, never imported/executed."""

import ast
from contextlib import contextmanager
import json
from pathlib import Path

import pytest

from qlab.dynamic_factor import scope_proof
from qlab.dynamic_factor.conventions import load_conventions
from qlab.dynamic_factor.contract import sha256


ROOT = Path(scope_proof.__file__).parent


def test_C13_filename_registration_has_no_artifact_SHA_and_R055_literal_is_unique():
    out = scope_proof.b2_isolation_proof(load_conventions())
    names = out["C13_filename_registration_scope"]
    assert names["registrations"] == {
        "conventions": ["provenance.json", "provenance-v2.json", "provenance-v3.json"],
        "input_disposition": ["qqq-events-v1.csv"],
        "historical_authority": ["EVO891-B-ledger-v4.tip.json"],
    }
    witness = names["historical_witness"]
    assert witness["assignments"] == 1
    assert witness["literal_filename"] == "EVO891-B-ledger-v4.tip.json"
    assert witness["source_identity_bound"] is True
    assert names["unverified_not_in_table"] == ["R056", "R057", "R058", "R059", "R060"]
    assert out["non_market_read_whitelist"]["execution"].count("fee_schedule.json") == 1


@pytest.mark.parametrize(
    "mutation", ["replacement", "reassignment", "dynamic_injection"]
)
def test_C13_R055_source_override_or_injection_is_rejected(
    private_sources, monkeypatch, record_property, mutation
):
    original = (private_sources / "historical_authority.py").read_bytes()
    if mutation == "replacement":
        raw = original.replace(b'"EVO891-B-ledger-v4.tip.json"', b'"other.tip.json"')
    elif mutation == "reassignment":
        raw = (
            original + b'\nHISTORICAL_V4_WITNESS_INPUT = FIXTURES / "other.tip.json"\n'
        )
    else:
        raw = (
            original
            + b'\nglobals()["HISTORICAL_V4_WITNESS_INPUT"] = FIXTURES / "other.tip.json"\n'
        )
    with changed(
        private_sources, "historical_authority.py", raw, monkeypatch
    ) as identity:
        with pytest.raises(
            ValueError, match="scope.file_access_not_whitelisted"
        ) as refused:
            scope_proof.b2_isolation_proof(load_conventions())
    observed(record_property, "R055:" + mutation, identity, refused)


REGISTRATION = Path(__file__).parent / "fixtures/c13-registration"
REGISTERED_IMPORTS = json.loads((REGISTRATION / "import-delta.json").read_bytes())
FIXED = json.loads((REGISTRATION / "fixed-reads.json").read_bytes())
EDGES = REGISTERED_IMPORTS["per_edge_negative_plan"]


@pytest.fixture(scope="module")
def private_sources(tmp_path_factory):
    root = tmp_path_factory.mktemp("C13_PRIVATE_AST_ONLY")
    for source in ROOT.glob("*.py"):
        (root / source.name).write_bytes(source.read_bytes())
    for _, relative, _ in scope_proof.FIXED_READS + scope_proof.B_RELEASE_FIXED_READS:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    return root


@contextmanager
def changed(root, path, raw, monkeypatch):
    path = root / path
    original = path.read_bytes()
    try:
        path.write_bytes(raw)
        with monkeypatch.context() as patch:
            patch.setattr(scope_proof, "__file__", str(root / "scope_proof.py"))
            yield dict(before_sha256=sha256(original), after_sha256=sha256(raw))
    finally:
        path.write_bytes(original)


def observed(record_property, label, mutation, refusal):
    record_property(
        "C13_actual",
        json.dumps(
            dict(
                label=label,
                **mutation,
                reason=str(refusal.value),
                component="static source/registered artifact inspection only",
                market_reader_calls=0,
                worker_started=False,
            ),
            sort_keys=True,
        ),
    )


def test_C13_registered_proof_has_exact_ten_reads_and_three_registry_files():
    proof = scope_proof.b2_isolation_proof(load_conventions())
    assert len(proof["C13_registered_fixed_reads"]) == 10
    assert proof["C13_registry_call_scope"]["literal_filenames"] == [
        "candidate_reference_manifest.json",
        "meta_reference_manifest.json",
        "predeclared_reference_registry.json",
    ]
    assert proof["C13_registry_call_scope"]["other_HASHES_granted"] is False
    assert proof["C13_registry_call_scope"]["registered_request_is_entry"] is False
    assert proof["seal_status"] == "seal_pending"
    assert scope_proof.FIXED_READS == tuple(
        (r["module"], r["target"].split("dynamic_factor/", 1)[1], r["expected_sha256"])
        for r in FIXED
    )
    for module, row in REGISTERED_IMPORTS["entries"].items():
        assert scope_proof.IMPORTS[module] == set(row["proposed"])


def test_A20_C13_old_manifest_identity_is_rejected_before_any_market_reader(
    record_property,
):
    from qlab.dynamic_factor.contract import digest
    from qlab.dynamic_factor.input_scope import ROLES
    import sys

    policy = load_conventions()
    old = json.loads((REGISTRATION / "old-B2-proof.json.fixture").read_bytes())
    manifest = dict(
        status="unavailable",
        reason="UNIT_EVENT_EVIDENCE_MISSING",
        missing_fields=["dividend_amount"],
        source_sha256=digest("SYNTHETIC_UNIT_SOURCE"),
        dates=list(policy.calendar),
        calendar_sha256=digest(list(policy.calendar)),
        affected_scope=["B2"],
        strategy_dependencies={r: [] for r in ROLES},
        isolation_source_sha256=old["source_sha256"],
    )
    calls = []
    previous = sys.getprofile()

    def observe(frame, event, arg):
        if (
            event == "call"
            and frame.f_globals.get("__name__", "").startswith("qlab.")
            and frame.f_code.co_name
            in {
                "read_inputs",
                "read_strategy_inputs",
                "run_isolated",
            }
        ):
            calls.append(frame.f_code.co_name)

    try:
        sys.setprofile(observe)
        with pytest.raises(
            ValueError, match="scope.B2_isolation_manifest_missing_or_invalid"
        ) as refused:
            scope_proof.b2_manifest_check(manifest, policy)
    finally:
        sys.setprofile(previous)
    assert calls == []
    assert (
        old["source_sha256"] != scope_proof.b2_isolation_proof(policy)["source_sha256"]
    )
    record_property(
        "C13_old_manifest_actual",
        json.dumps(
            dict(
                reason=str(refused.value),
                market_reader_calls=len(calls),
                worker_roles=[],
                scope="actual B2 manifest reception, not C09 execution acceptance",
            )
        ),
    )


@pytest.mark.parametrize("edge", EDGES, ids=[e["id"] for e in EDGES])
def test_C13_each_registered_import_rejects_unknown_replacement(
    private_sources, monkeypatch, record_property, edge
):
    module, token = edge["module"], edge["exact_import_module"]
    path = private_sources / (module + ".py")
    tree = ast.parse(path.read_bytes())
    replaced = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == token:
            node.module = "__C13_UNLISTED_" + edge["id"]
            replaced = True
            break
        if isinstance(node, ast.Import):
            for name in node.names:
                if name.name == token:
                    name.name = "__C13_UNLISTED_" + edge["id"]
                    replaced = True
                    break
            if replaced:
                break
    assert replaced, (module, token)
    raw = (ast.unparse(tree) + "\n").encode()
    with changed(private_sources, path.name, raw, monkeypatch) as mutation:
        with pytest.raises(
            ValueError, match="^scope.static_import_not_whitelisted$"
        ) as refusal:
            scope_proof.b2_isolation_proof(load_conventions())
        observed(
            record_property,
            dict(edge_id=edge["id"], module=module, token=token),
            mutation,
            refusal,
        )


@pytest.mark.parametrize("module", ["execution", "pipeline"])
def test_C13_old_entry_keeps_unlisted_extra_import_rejection(
    private_sources, monkeypatch, record_property, module
):
    raw = (
        private_sources / (module + ".py")
    ).read_bytes() + b"\nimport __C13_EXTRA_UNLISTED\n"
    with changed(private_sources, module + ".py", raw, monkeypatch) as mutation:
        with pytest.raises(
            ValueError, match="^scope.static_import_not_whitelisted$"
        ) as refusal:
            scope_proof.b2_isolation_proof(load_conventions())
        observed(record_property, dict(existing_entry=module), mutation, refusal)


@pytest.mark.parametrize(
    "module,function",
    [
        ("reference_definition_v301", "member_definition"),
        ("reference_registry_v3", "member_spec"),
    ],
)
def test_C13_fourth_registry_name_is_rejected_at_reached_call_site(
    private_sources, monkeypatch, record_property, module, function
):
    tree = ast.parse((private_sources / (module + ".py")).read_bytes())
    fn = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == function
    )
    call = next(
        n
        for n in ast.walk(fn)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "artifact"
    )
    call.args[0] = ast.Constant("lineage-plan.json")
    raw = (ast.unparse(tree) + "\n").encode()
    with changed(private_sources, module + ".py", raw, monkeypatch) as mutation:
        with pytest.raises(
            ValueError, match="^scope.file_access_not_whitelisted$"
        ) as refusal:
            scope_proof.b2_isolation_proof(load_conventions())
        # Prove the new fourth-name control fired before the conservative
        # helper-source pin, rather than attributing any hash failure to it.
        cause = refusal.value.__cause__
        assert type(cause) is ValueError
        stop = cause.__traceback__
        while stop.tb_next is not None:
            stop = stop.tb_next
        source = ast.parse((ROOT / "scope_proof.py").read_bytes())
        names_guard = next(
            n
            for n in ast.walk(source)
            if isinstance(n, ast.If)
            and isinstance(n.test, ast.Compare)
            and isinstance(n.test.left, ast.Name)
            and n.test.left.id == "names"
        )
        assert stop.tb_frame.f_code.co_name == "_candidate_registry_scope"
        assert stop.tb_lineno == names_guard.body[0].lineno
        mutation["literal_domain_guard_line"] = stop.tb_lineno
        observed(
            record_property,
            dict(function=module + "." + function, forbidden_name="lineage-plan.json"),
            mutation,
            refusal,
        )


@pytest.mark.parametrize("row", FIXED, ids=[r["id"] for r in FIXED])
def test_C13_each_fixed_artifact_byte_drift_is_rejected(
    private_sources, monkeypatch, record_property, row
):
    relative = row["target"].split("dynamic_factor/", 1)[1]
    raw = (private_sources / relative).read_bytes() + b"\n"
    with changed(private_sources, relative, raw, monkeypatch) as mutation:
        with pytest.raises(
            ValueError, match="^scope.file_access_not_whitelisted$"
        ) as refusal:
            scope_proof.b2_isolation_proof(load_conventions())
        observed(
            record_property, dict(read_id=row["id"], path=relative), mutation, refusal
        )


def test_C13_third_module_cannot_read_protocol_file(
    private_sources, monkeypatch, record_property
):
    raw = (
        (private_sources / "execution_candidate.py").read_bytes()
        + b"\n(ROOT / 'EVO883-C06-CLOCK-adopted-protocol-v1.0.0.json').read_bytes()\n"
    )
    with changed(
        private_sources, "execution_candidate.py", raw, monkeypatch
    ) as mutation:
        with pytest.raises(
            ValueError, match="^scope.file_access_not_whitelisted$"
        ) as refusal:
            scope_proof.b2_isolation_proof(load_conventions())
        observed(
            record_property,
            dict(unregistered_reader="execution_candidate"),
            mutation,
            refusal,
        )


def test_C13_actual_withdrawn_envelope_cannot_replace_formal_adoption(
    private_sources, monkeypatch, record_property
):
    raw = (REGISTRATION / "withdrawn-e364.json.fixture").read_bytes()
    assert (
        sha256(raw)
        == "e3646dc3a1381e508e59b2adceb04d29b3ea357949065ce83728950a038653ec"
    )
    relative = next(
        path
        for module, path, _ in scope_proof.FIXED_READS
        if module == "execution_closure" and path.endswith(".json")
    )
    with changed(private_sources, relative, raw, monkeypatch) as mutation:
        with pytest.raises(
            ValueError, match="^scope.file_access_not_whitelisted$"
        ) as refusal:
            scope_proof.b2_isolation_proof(load_conventions())
        observed(
            record_property,
            dict(withdrawn_attachment="01a19a99-fc51-7c2d-9c31-5601bbc02316"),
            mutation,
            refusal,
        )


@pytest.mark.parametrize("module", ["execution_clock", "execution_closure"])
def test_C13_registered_reader_cannot_substitute_outside_file(
    private_sources, monkeypatch, record_property, module
):
    tree = ast.parse((private_sources / (module + ".py")).read_bytes())
    call = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "read_bytes"
    )
    call.func.value = ast.parse("ROOT / 'UNREGISTERED.json'", mode="eval").body
    raw = (ast.unparse(tree) + "\n").encode()
    with changed(private_sources, module + ".py", raw, monkeypatch) as mutation:
        with pytest.raises(
            ValueError, match="^scope.file_access_not_whitelisted$"
        ) as refusal:
            scope_proof.b2_isolation_proof(load_conventions())
        observed(
            record_property,
            dict(module=module, forbidden_file="UNREGISTERED.json"),
            mutation,
            refusal,
        )
