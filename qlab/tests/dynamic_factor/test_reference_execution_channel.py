"""C09/C10: synthetic owned journals and a no-reader diagnostic worker.

No actual strategy/reference performance, source certification or runtime run.
"""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from projection_test_helpers import case
from qlab.dynamic_factor.contract import canonical, digest
from qlab.dynamic_factor.execution_receipts.reference_result import (
    ReferenceObservation,
    check_transport,
    read_observation,
    read_program,
)
from qlab.dynamic_factor.reference_boundary import (
    run_execution_result,
    run_execution_family,
)
from qlab.dynamic_factor.execution_receipts.input_data import require_resealed_evidence
from qlab.dynamic_factor.reference_execution import ReferenceExecution, replay_execution
from qlab.dynamic_factor.reference_registry_v3 import DISPATCH
from qlab.dynamic_factor.scope_proof import reference_execution_proof
from test_execution_accounting import model_origins
from test_execution_risk_history import history
from test_execution_startup import book


def born(member="CREF-F1-L020"):
    source = book(member, attempt="C10-SYNTHETIC-" + member)
    _, args = history(member, attempt=source.identity["attempt_id"])
    args["book_id"] = source.book_id
    risk = type(history()[0])(**args)
    return ReferenceExecution(
        source,
        risk,
        run_id="C10-SYNTHETIC-RUN",
        expected_startup_sha256=digest(source.snapshot()),
        expected_snapshot_sha256=risk.snapshot()["snapshot_sha256"],
    )


def no_tilt(reference):
    inputs, _, _ = case()
    risk = reference.history
    snap = risk.snapshot()
    state, date = snap["state"], snap["close_session"]
    nxt = risk._policy.calendar[risk._policy.calendar.index(date) + 1]
    inputs["close_state"].update(
        inventory=deepcopy(state["inventory"]),
        cash=state["cash"],
        NAV_anchor=state["nav"],
        age=deepcopy(state["age"]),
        origin=deepcopy(state["origin"]),
        rights=deepcopy(state["rights"]),
        receivables=deepcopy(state["receivables"]),
        unknown_components=[],
        signal_close_session=date,
        execution_open_session=nxt,
    )
    inputs["eligibility"].update(
        B=risk._guard["B"],
        E_t=[],
        named_count=0,
        quantity_state="VERIFIED_LT50",
        states={
            s: "B_GUARDED" if s in risk._guard["B"] else "VERIFIED_INELIGIBLE"
            for s in risk._policy.profile["universe"]
        },
    )
    inputs["locked_signal"].update(
        signal_session=date, scores={}, recipe_id=snap["scope"]["recipe_id"]
    )
    inputs["execution_open"].update(
        session=nxt, raw_open={"QQQ": "100"}, ADV20_usd_asof_close={"QQQ": "100000000"}
    )
    signal = dict(
        book_id=snap["book_id"],
        signal_session=date,
        execution_session=nxt,
        ranks={},
        origin_context=None,
    )
    return inputs, signal


@pytest.fixture(scope="module")
def owned_references():
    outputs = {}
    for member in sorted(DISPATCH):
        reference = born(member)
        account = reference.account
        for i, date in enumerate(reference.series._dates):
            if i < 3:
                facts = dict(
                    timestamp=date + "T14:30:00Z",
                    raw_open=100,
                    source_sha256=digest(["SYNTHETIC OPEN", date]),
                )
                reference.startup_open(
                    facts["timestamp"],
                    facts["raw_open"],
                    source_sha256=facts["source_sha256"],
                    expected_input_sha256=digest(facts),
                )
                opening = dict(
                    session=date,
                    asof=facts["timestamp"],
                    prices={"QQQ": "100"},
                    source_sha256=facts["source_sha256"],
                    price_kind="verified_tradable_raw_open",
                    origins=model_origins(account),
                )
                reference.model_open(opening, expected_evidence_sha256=digest(opening))
            if reference.history._book.decision_due()["order_intent_due"]:
                inputs, signal = no_tilt(reference)
                reference.lock_projection(
                    inputs,
                    signal,
                    expected_input_sha256=digest(inputs),
                    expected_signal_sha256=digest(signal),
                )
                assert account.intent()["ticket"]["orders"] == []
            evidence = dict(
                session=date,
                asof=date + "T20:00:00Z",
                prices={"QQQ": "100"},
                source_sha256=digest(["SYNTHETIC CLOSE", date]),
                price_kind="verified_raw_close",
                rights_complete=True,
                cash_events_complete=True,
                execution_outcomes={
                    key: dict(
                        filled_quantity=row["filled"],
                        status="verified_DAY_closed",
                        source_sha256=digest(["SYNTHETIC DAY", date]),
                    )
                    for key, row in account.intent()["orders"].items()
                    if row["session"] == date
                },
            )
            out = reference.close(
                evidence,
                expected_evidence_sha256=digest(evidence),
                startup_valuation=dict(
                    raw_close=100,
                    valuation=dict(
                        rights_value=0, receivables_value=0, components_known=True
                    ),
                )
                if i < 3
                else None,
            )
            assert out["trace"] == ["ACCOUNTING_AND_NAV", "C06_RISK_ONCE"]
            assert out["accounting"]["execution_verified"] is False
        benchmark = dict(
            schema="EVO884.BenchmarkDaily/v1",
            dates=list(reference.series._dates),
            values=[0.0] * 1260,
            basis="analytical_TR",
            symbol="QQQ",
            role="B1",
            source_sha256=digest("SYNTHETIC TR BENCHMARK"),
        )
        cap = reference.observe(benchmark, expected_benchmark_sha256=digest(benchmark))
        outputs[member] = (reference, cap)
    return outputs


@pytest.fixture(scope="module")
def worker_family(owned_references):
    return run_execution_family({m: cap for m, (_, cap) in owned_references.items()})


@pytest.fixture(scope="module")
def bound_reference(owned_references, tmp_path_factory):
    from reference_fact_helpers import four_file_program
    from qlab.dynamic_factor.conventions import load_conventions

    _, original = owned_references["CREF-F1-L020"]
    program, read, facts = four_file_program(
        tmp_path_factory.mktemp("four-files"), read_program(original)[0]
    )
    cap = replay_execution(program, load_conventions())
    return cap, read, facts


def test_C09_unowned_input_read_refuses_before_child(bound_reference, monkeypatch):
    from qlab.dynamic_factor.execution_receipts.input_facts import InputRead

    cap, _, facts = bound_reference
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: calls.append(a))
    for wire in (facts, object.__new__(InputRead)):
        with pytest.raises(ValueError, match="owned_four_file_read_required"):
            run_execution_result(cap, input_read=wire)
    with pytest.raises(TypeError, match="owned_four_file_read_required"):
        InputRead()
    assert calls == []


def test_C09_actual_worker_rejects_substituted_read_facts(
    bound_reference, monkeypatch, record_property
):
    import qlab.dynamic_factor.reference_boundary as boundary

    cap, read, _ = bound_reference
    original, seen = subprocess.run, []

    def child(*a, **kw):
        wire = json.loads(kw["input"])
        wire["facts"]["data"]["raw"]["records"][0]["values"]["raw_open"] = "999"
        kw["input"] = json.dumps(wire) + "\n"
        out = original(*a, **kw)
        result = json.loads(out.stdout)
        assert out.returncode == 2
        assert result["reason"] == "reference.worker_facts_binding_mismatch"
        assert result["returns"] is None and result["reader_calls"] == 0
        seen.append(result)
        return out

    monkeypatch.setattr(boundary.subprocess, "run", child)
    with pytest.raises(ValueError, match="worker_facts_binding_mismatch"):
        boundary.run_execution_result(cap, input_read=read)
    assert len(seen) == 1
    record_property(
        "C09_changed_fact_worker_actual", json.dumps(seen[0], sort_keys=True)
    )


def test_C09_original_right_passes_to_C04_without_emptying_declaration():
    reference = born()
    event = dict(
        symbol="QQQ",
        kind="split",
        ratio=None,
        source_sha256=digest("SYNTHETIC ORIGINAL"),
    )
    date = reference.series._dates[0]
    result = reference.cash_event(
        "rights", event, session=date, asof=date + "T14:30:00Z"
    )
    assert result["retained_state"]["rights"][digest(event)] == event
    assert result["NAV"] is result["cash"] is None
    assert result["complete"] is False
    assert reference._program[-1]["arguments"]["event"] == event


def test_C10_startup_cannot_inject_unearned_valuation():
    reference = born()
    d = reference.series._dates[0]
    facts = dict(
        timestamp=d + "T14:30:00Z", raw_open=100, source_sha256=digest("SYNTHETIC")
    )
    reference.startup_open(**facts, expected_input_sha256=digest(facts))
    opening = dict(
        session=d,
        asof=facts["timestamp"],
        prices={"QQQ": "100"},
        source_sha256=facts["source_sha256"],
        price_kind="verified_tradable_raw_open",
        origins=model_origins(reference.account),
    )
    reference.model_open(opening, expected_evidence_sha256=digest(opening))
    close = dict(
        session=d,
        asof=d + "T20:00:00Z",
        prices={"QQQ": "100"},
        source_sha256=facts["source_sha256"],
        price_kind="verified_raw_close",
        rights_complete=True,
        cash_events_complete=True,
        execution_outcomes={
            key: dict(
                filled_quantity=row["filled"],
                status="verified_DAY_closed",
                source_sha256=digest("SYNTHETIC DAY"),
            )
            for key, row in reference.account.intent()["orders"].items()
        },
    )
    with pytest.raises(ValueError, match="startup_valuation_not_from_same_account"):
        reference.close(
            close,
            expected_evidence_sha256=digest(close),
            startup_valuation=dict(
                raw_close=100,
                valuation=dict(
                    rights_value=0, receivables_value=1, components_known=True
                ),
            ),
        )
    assert reference.startup.snapshot()["startup_complete"] is False


def test_C09_C10_actual_read_facts_bind_before_real_worker_replay(
    bound_reference, record_property
):
    cap, read, facts = bound_reference
    report = run_execution_result(cap, input_read=read)
    binding = report["input_fact_binding"]
    assert binding["facts_sha256"] == digest(facts)
    assert binding["program_sha256"] == read_program(cap)[1]
    assert binding["original_reader_calls"] == 4
    assert binding["original_read_roles"] == ["raw", "rights", "adv", "cash"]
    assert len(binding["fact_cells"]) > 1260 * 3
    assert len(report["observation"]["returns"]) == 1260
    assert report["observation"]["execution_verified"] is False
    assert report["seal_status"] == "seal_pending"
    record_property(
        "C09_bound_worker_actual",
        json.dumps(
            dict(
                binding=binding,
                worker=report["worker_role"],
                replay_steps=report["execution_steps"],
            ),
            sort_keys=True,
        ),
    )


@pytest.mark.parametrize(
    "attack",
    [
        "price",
        "ADV",
        "event",
        "unknown",
        "future",
        "date",
        "scope",
        "book",
        "run",
        "raw_source",
    ],
)
def test_C09_fact_rebinding_or_omission_refuses_before_replay(
    bound_reference, monkeypatch, attack, record_property
):
    from qlab.dynamic_factor.execution_receipts import input_facts
    from qlab.dynamic_factor.execution_receipts import reference_result

    cap, read, original = bound_reference
    p, facts = read_program(cap)[0], deepcopy(original)
    role = "raw"
    if attack == "price":
        facts["data"][role]["records"][0]["values"]["raw_open"] = "101"
    elif attack == "ADV":
        first = next(e for e in p["operations"] if e["operation"] == "lock_projection")
        date = first["arguments"]["inputs"]["close_state"]["signal_close_session"]
        next(r for r in facts["data"]["adv"]["records"] if r["date"] == date)["values"][
            "adv20_dollar"
        ] = "1"
    elif attack == "event":
        from qlab.dynamic_factor.contract import sha256

        raw = '{"symbol":"QQQ","kind":"cash_available"}'
        facts["data"]["cash"]["records"][0]["values"]["cash_events"] = [
            dict(raw=raw, sha256=sha256(raw.encode()))
        ]
    elif attack == "unknown":
        facts["data"][role]["records"][0]["values"]["raw_close"] = None
    elif attack == "future":
        facts["data"][role]["records"][0]["available_at"] = "2099-01-01T00:00:00Z"
    elif attack == "date":
        facts["data"][role]["records"].pop()
    elif attack == "scope":
        e = next(e for e in p["operations"] if e["operation"] == "lock_projection")
        e["arguments"]["inputs"]["eligibility"]["E_t"] = []
    elif attack == "book":
        p["initial"]["history"]["book_id"] = digest("other book")
    elif attack == "run":
        p["initial"]["run_id"] = "other run"
    else:
        p["operations"][0]["arguments"]["source_sha256"] = digest("different source")
    # Bypass only the ownership hash in this semantic-guard mutation. Both
    # documents still pass their closed transport schema; use the public host
    # path to prove rejection before it creates a child or replays the engine.
    expected = {
        "price": "reference.execution_price_not_from_read",
        "ADV": "reference.execution_ADV_not_from_read",
        "event": "reference.unprocessed_original_event",
        "unknown": "reference.execution_cell_unknown",
        "future": "reference.execution_cell_not_yet_available",
        "date": "execution_input.exact_declared_date_symbol_batch_required",
        "scope": "reference.execution_E_t_not_from_scope",
        "book": "reference.input_execution_identity_mismatch",
        "run": "reference.input_execution_identity_mismatch",
        "raw_source": "reference.execution_raw_source_mismatch",
    }[attack]
    calls = []
    monkeypatch.setattr(input_facts, "read_facts", lambda _: (facts, digest(facts)))
    monkeypatch.setattr(reference_result, "read_program", lambda _: (p, digest(p)))
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: calls.append(a))
    with pytest.raises(ValueError) as exc:
        run_execution_result(cap, input_read=read)
    assert str(exc.value) == expected
    assert calls == []
    record_property(
        "C09_fact_refusal_actual",
        json.dumps(
            dict(attack=attack, reason=str(exc.value), worker_calls=0), sort_keys=True
        ),
    )


def test_C09_P4_P7_sidecar_retains_unaccepted_N_and_sources(
    bound_reference, record_property
):
    from qlab.dynamic_factor.execution_receipts.p4p7 import read_sidecar
    from qlab.dynamic_factor.reference_v3_evidence import (
        prepare_execution_sidecar as prepare_sidecar,
        receive_execution_sidecar as receive_sidecar,
    )
    from qlab.dynamic_factor.execution_receipts.n_binding import stage_budget_mapping

    cap, read, _ = bound_reference
    doc = read_observation(cap)[0]
    n = dict(
        host_context=None,
        installed_snapshot=None,
        run_pin=None,
        traces=[],
        expected_run_ids=[doc["run_id"]],
        stage_mapping=stage_budget_mapping(
            stage="independent_reference",
            producer_id="SYNTHETIC-DIAGNOSTIC",
            run_id=doc["run_id"],
        ),
    )
    sidecar = prepare_sidecar(cap, read, n_binding=n)
    actual, identity = read_sidecar(sidecar)
    from jsonschema import validate
    from qlab.dynamic_factor.execution_receipts import p4p7

    validate(
        actual,
        json.loads(
            (
                Path(p4p7.__file__).parent / "schemas/reference-p4p7.schema.json"
            ).read_bytes()
        ),
    )
    assert actual["P4"]["input_fact_binding"]["original_reader_calls"] == 4
    assert actual["P7"]["complete_N"] is None and actual["P7"]["reasons"]
    assert actual["source_reception"] is actual["permission_reception"] is None
    assert actual["series"]["active_series_sha256"] == digest(doc["returns"])
    assert actual["input_manifest_sha256"] != actual["series"]["active_series_sha256"]
    out = receive_sidecar(sidecar)
    assert out["sidecar_sha256"] == identity
    assert out["reasons"] == ["reference.seal_pending"]
    assert out["returns"] is out["formal_N"] is None
    assert out["reader_calls"] == out["worker_calls"] == 0
    actual["seal_status"] = "sealed"
    actual["source_reception"] = {"accepted": True}
    assert receive_sidecar(actual)["reasons"] == ["reference.owned_P4_P7_required"]
    record_property(
        "C09_P4_P7_actual",
        json.dumps(
            dict(sidecar=read_sidecar(sidecar)[0], reception=out), sort_keys=True
        ),
    )


@pytest.mark.parametrize("member", sorted(DISPATCH))
def test_C10_four_owned_nonempty_results_cross_real_isolated_worker(
    owned_references, worker_family, member, record_property
):
    reference, cap = owned_references[member]
    document, expected = read_observation(cap)
    out = worker_family["outputs"][member]
    assert out["observation_sha256"] == expected
    assert canonical(out["observation"]) == canonical(document)
    assert len(out["observation"]["returns"]) == 1260
    assert out["observation"]["returns"][0] < 0
    assert out["observation"]["scope"]["member_id"] == member
    assert out["observation"]["book_id"] == reference.startup.book_id
    assert out["reader_calls"] == 0 and out["accessed_roles"] == []
    assert out["worker_role"] == "reference_diagnostic_execution"
    assert out["execution_steps"] == len(read_program(cap)[0]["operations"])
    assert len(out["observation"]["eligibility_by_close"]) == 251
    assert out["protocol_read_paths"] and all(
        Path(p).name not in {"raw.json", "rights.json", "adv.json", "cash.json"}
        for p in out["protocol_read_paths"]
    )
    assert (
        out["observation"]["DAG"]["execution_location"]
        == "owned_host_and_isolated_replay"
    )
    assert out["observation"]["execution_verified"] is False
    assert out["runtime_consumable"] is out["certifiable"] is False
    assert out["observation"]["source_acceptance"] == "not_checked"
    assert out["observation"]["formal_N"] is None
    with pytest.raises(ValueError, match="seal_pending"):
        require_resealed_evidence(out)
    record_property("C10_actual_observation", json.dumps(out, sort_keys=True))
    record_property(
        "C10_actual",
        json.dumps(
            dict(
                member=member,
                book_id=document["book_id"],
                dates=1260,
                child_exit=0,
                reader=0,
                roles=[],
                source_acceptance="not_checked",
                seal_status="seal_pending",
            ),
            sort_keys=True,
        ),
    )


def test_C10_whole_family_preserves_independent_roles_books_and_run(worker_family):
    out = worker_family
    assert set(out["outputs"]) == set(DISPATCH)
    assert len({r["observation"]["book_id"] for r in out["outputs"].values()}) == 4
    assert {
        r["observation"]["scope"]["execution_role"] for r in out["outputs"].values()
    } == {
        "independent_candidate_reference",
        "independent_meta_reference_probe_component",
    }
    assert all(r["observation"]["returns"] for r in out["outputs"].values())


@pytest.mark.parametrize("attack", ["missing", "wire"])
def test_C09_whole_family_missing_or_unowned_reads_never_falls_back(
    owned_references, monkeypatch, attack
):
    caps = {m: cap for m, (_, cap) in owned_references.items()}
    reads = {} if attack == "missing" else {m: {} for m in caps}
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: calls.append(a))
    with pytest.raises(
        ValueError,
        match="closed_four_owned_input_reads_required|owned_four_file_read_required",
    ):
        run_execution_family(caps, input_reads=reads)
    assert calls == []


@pytest.mark.parametrize("attack", ["subset", "duplicate", "swap"])
def test_C10_family_rejects_incomplete_or_mixed_books_before_worker(
    owned_references, monkeypatch, attack
):
    caps = {m: cap for m, (_, cap) in owned_references.items()}
    members = sorted(caps)
    if attack == "subset":
        del caps[members[0]]
    elif attack == "duplicate":
        caps[members[0]] = caps[members[1]]
    else:
        caps[members[0]], caps[members[1]] = caps[members[1]], caps[members[0]]
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a))
    with pytest.raises(ValueError, match="closed_four|separate_books_same_family"):
        run_execution_family(caps)
    assert calls == []


@pytest.mark.parametrize(
    "attack",
    ["dict", "fake_cap", "candidate", "changed_returns", "other_book", "empty_dates"],
)
def test_C10_caller_results_and_cross_book_replacement_rejected(
    owned_references, attack
):
    _, cap = owned_references["CREF-F1-L020"]
    document, expected = read_observation(cap)
    if attack in {"dict", "candidate"}:
        if attack == "candidate":
            document["scope"]["member_id"] = "F1-L020"
        with pytest.raises(
            ValueError, match="owned_observation_required_no_result_input"
        ):
            run_execution_result(document)
    elif attack == "fake_cap":
        with pytest.raises(
            ValueError, match="owned_observation_required_no_result_input"
        ):
            run_execution_result(object.__new__(ReferenceObservation))
    else:
        if attack == "changed_returns":
            document["returns"][0] = 50.0
        elif attack == "other_book":
            document["book_id"] = digest("OTHER BOOK")
        else:
            document["dates"] = []
        with pytest.raises(ValueError, match="worker_observation_binding_mismatch"):
            check_transport(document, expected)


def test_C10_result_issuer_is_not_public_constructor():
    with pytest.raises(ValueError, match="owned_observation_required"):
        ReferenceObservation(None)
    candidate = book()
    _, args = history("F1-L020")
    with pytest.raises(
        ValueError,
        match="separate_preexecution_book_binding_required|execution_role_mismatch|member_not_registered",
    ):
        ReferenceExecution(
            candidate,
            type(history()[0])(**args),
            run_id="wrong",
            expected_startup_sha256=digest(candidate.snapshot()),
            expected_snapshot_sha256=type(history()[0])(**args).snapshot()[
                "snapshot_sha256"
            ],
        )


def test_C10_unfinished_startup_cannot_issue_returns():
    reference = born()
    benchmark = dict(
        schema="EVO884.BenchmarkDaily/v1",
        dates=reference.series._dates,
        values=[0.0] * 1260,
        basis="analytical_TR",
        symbol="QQQ",
        role="B1",
        source_sha256=digest("SYNTHETIC"),
    )
    with pytest.raises(ValueError, match="complete_owned_startup_required"):
        reference.observe(benchmark, expected_benchmark_sha256=digest(benchmark))
    assert reference.account.close_receipts() == []


def test_C10_missing_day_cannot_reuse_a_finished_observation(
    owned_references, monkeypatch
):
    reference, cap = owned_references["CREF-F1-L020"]
    monkeypatch.setattr(reference.account, "_closes", reference.account._closes[:-1])
    with pytest.raises(ValueError, match="exact_1260_dates_required"):
        run_execution_result(cap)


def test_C10_static_component_fourth_import_or_direct_reader_rejected(
    tmp_path, monkeypatch
):
    from qlab.dynamic_factor import reference_check

    original = Path.read_bytes
    path = Path(reference_check.__file__).parent / "reference_execution.py"
    for extra, reason in [
        (b"\nimport os\n", "static_import_not_whitelisted"),
        (
            b"\ndef hidden():\n    return Path('other').read_bytes()\n",
            "reader_or_dynamic_call_forbidden",
        ),
    ]:
        with monkeypatch.context() as patch:
            patch.setattr(
                Path,
                "read_bytes",
                lambda p: original(p) + extra if p == path else original(p),
            )
            with pytest.raises(ValueError, match=reason):
                reference_execution_proof(born().history._policy)


@pytest.mark.parametrize("attack", ["fifth_file", "other_contract", "contract_bytes"])
def test_C09_new_scope_segment_registers_each_exact_file_and_SHA(monkeypatch, attack):
    from qlab.dynamic_factor import reference_check

    original = Path.read_bytes
    base = Path(reference_check.__file__).parent
    if attack == "fifth_file":
        target = base / "execution_receipts/input_reader.py"
        changed = original(target).replace(
            b'("raw", "rights", "adv", "cash")',
            b'("raw", "rights", "adv", "cash", "fifth")',
        )
        reason = "execution_input_file_not_registered"
    elif attack == "other_contract":
        target = base / "execution_receipts/n_binding.py"
        changed = original(target).replace(
            b"EVO883-BRR-v30-archive-acceptance-v1.json", b"unapproved.json"
        )
        reason = "execution_fixed_file_not_registered"
    else:
        target = (
            base
            / "execution_receipts/contracts/EVO883-BRR-v30-archive-acceptance-v1.json"
        )
        changed = original(target) + b"\n"
        reason = "execution_fixed_file_identity_mismatch"
    monkeypatch.setattr(
        Path, "read_bytes", lambda p: changed if p == target else original(p)
    )
    with pytest.raises(ValueError, match=reason):
        reference_check.execution_proof()


def test_C10_account_drift_cannot_reuse_a_finished_observation(
    owned_references, monkeypatch
):
    reference, cap = owned_references["CREF-F1-L020"]
    monkeypatch.setattr(reference.account, "_cash", reference.account._cash + 1)
    with pytest.raises(ValueError, match="observation_account_drift"):
        run_execution_result(cap)


def test_C10_shared_due_clock_cannot_omit_a_required_D1_plan(owned_references):
    reference, cap = owned_references["CREF-F1-L020"]
    program, _ = read_program(cap)
    first = next(
        i
        for i, event in enumerate(program["operations"])
        if event["operation"] == "lock_projection"
    )
    del program["operations"][first]
    with pytest.raises(ValueError, match="same_D1_plan_required_for_due_open"):
        replay_execution(program, reference.history._policy)


def test_C10_family_cannot_mix_a_different_benchmark(owned_references, monkeypatch):
    reference, cap = owned_references["CREF-F1-L020"]
    program, _ = read_program(cap)
    benchmark = program["benchmark"]
    benchmark["values"][0] = 0.001
    different = reference.observe(
        benchmark, expected_benchmark_sha256=digest(benchmark)
    )
    caps = {m: cap for m, (_, cap) in owned_references.items()}
    caps["CREF-F1-L020"] = different
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a))
    with pytest.raises(ValueError, match="separate_books_same_family_binding_required"):
        run_execution_family(caps)
    assert calls == []


def test_C10_family_rejects_a_changed_eligibility_trace_before_worker(
    owned_references, monkeypatch
):
    reference, cap = owned_references["CREF-F1-L020"]
    program, _ = read_program(cap)
    operations = deepcopy(reference._program)
    first = next(e for e in operations if e["operation"] == "lock_projection")
    first["arguments"]["inputs"]["eligibility"]["named_count"] = 1
    monkeypatch.setattr(reference, "_program", operations)
    different = reference.observe(
        program["benchmark"], expected_benchmark_sha256=program["benchmark_sha256"]
    )
    caps = {m: cap for m, (_, cap) in owned_references.items()}
    caps["CREF-F1-L020"] = different
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a))
    with pytest.raises(ValueError, match="separate_books_same_family_binding_required"):
        run_execution_family(caps)
    assert calls == []


def test_C10_guard_drift_cannot_reuse_a_finished_observation(
    owned_references, monkeypatch
):
    reference, cap = owned_references["CREF-F1-L020"]
    changed = deepcopy(reference.account._guard)
    changed["guard_injected"] = True
    monkeypatch.setattr(reference.account, "_guard", changed)
    with pytest.raises(ValueError, match="observation_guard_drift"):
        run_execution_result(cap)


@pytest.mark.parametrize("field", ["returns", "M", "P"])
def test_C10_program_cannot_contain_caller_results(owned_references, field):
    reference, cap = owned_references["CREF-F1-L020"]
    program, _ = read_program(cap)
    program[field] = [50]
    with pytest.raises(ValueError, match="closed_execution_program_required"):
        replay_execution(program, reference.history._policy)


def test_C10_program_cannot_select_an_arbitrary_operation(owned_references):
    reference, cap = owned_references["CREF-F1-L020"]
    program, _ = read_program(cap)
    program["operations"] = [dict(operation="eval", arguments={})]
    with pytest.raises(ValueError, match="execution_operation_not_whitelisted"):
        replay_execution(program, reference.history._policy)


def test_C10_actual_worker_rejects_changed_program_before_execution(
    owned_references, monkeypatch, record_property
):
    _, cap = owned_references["CREF-F1-L020"]
    import qlab.dynamic_factor.reference_boundary as boundary

    original = subprocess.run
    actual = []

    def child(*args, **kwargs):
        program = json.loads(kwargs["input"])
        program["operations"] = []
        kwargs["input"] = json.dumps(program) + "\n"
        out = original(*args, **kwargs)
        report = json.loads(out.stdout)
        assert out.returncode == 2
        assert report["reason"] == "reference.worker_program_binding_mismatch"
        assert (
            report["returns"] is None
            and report["reader_calls"] == 0
            and report["accessed_roles"] == []
        )
        actual.append(report)
        return out

    monkeypatch.setattr(boundary.subprocess, "run", child)
    with pytest.raises(ValueError, match="worker_program_binding_mismatch"):
        boundary.run_execution_result(cap)
    assert len(actual) == 1
    record_property("C10_changed_program_actual", json.dumps(actual[0], sort_keys=True))


@pytest.mark.parametrize("attack", ["exit", "vector", "roles"])
def test_C10_child_result_must_match_owned_object_exactly(
    owned_references, worker_family, monkeypatch, attack
):
    _, cap = owned_references["CREF-F1-L020"]
    import qlab.dynamic_factor.reference_boundary as boundary

    def child(*args, **kwargs):
        report = deepcopy(worker_family["outputs"]["CREF-F1-L020"])
        del report["source_proof_sha256"]
        out = subprocess.CompletedProcess(args, 0, json.dumps(report), "")
        if attack == "exit":
            out.returncode = 2
        else:
            report = json.loads(out.stdout)
            if attack == "vector":
                report["observation"]["returns"][0] = 50
            else:
                report["accessed_roles"] = ["candidate_returns"]
            out.stdout = json.dumps(report)
        return out

    monkeypatch.setattr(boundary.subprocess, "run", child)
    with pytest.raises(
        ValueError, match="result_worker_failed|unexpected_result_worker_output"
    ):
        boundary.run_execution_result(cap)


@pytest.mark.parametrize(
    "operation", ["read", "write", "socket", "process", "compile", "exec"]
)
def test_C10_result_worker_has_no_data_or_process_capability(operation):
    package = str(Path(__file__).resolve().parents[2])
    bootstrap = (
        "import sys,subprocess,socket,ast;sys.path.insert(0,"
        + repr(package)
        + ");from qlab.dynamic_factor.execution_receipts.replay_guard import install;install({});"
    )
    actions = {
        "read": "open(__file__)",
        "write": "open('forbidden','w')",
        "socket": "socket.socket()",
        "process": "subprocess.run([sys.executable,'-V'])",
        "compile": "ast.parse('unapproved_name')",
        "exec": "eval(compile('b_k','<unknown>','eval'),{'b_k':0})",
    }
    # __file__ is not defined in -c; use an explicit harmless fixed test path.
    actions["read"] = "open('raw.json')"
    child = subprocess.run(
        [sys.executable, "-I", "-S", "-c", bootstrap + actions[operation]],
        capture_output=True,
        text=True,
        env={},
    )
    assert child.returncode != 0
    assert "reference.replay_" in child.stderr
