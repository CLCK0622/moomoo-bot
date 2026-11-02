"""B propagation controls. No B01 receiver, A issuance or formal positive path.

The two explicitly named test doubles below only observe delegation/refusals.
They are never installed as the canonical ReleaseContext or a host issuer.
"""

from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path

import pytest

from qlab.dynamic_factor import noncash_v3
from qlab.dynamic_factor.contract import canonical, digest, sha256
from qlab.dynamic_factor.execution_amounts import ExactOrderCosts
from qlab.dynamic_factor.execution_candidate import CandidateIntent, CandidateOpen
from qlab.dynamic_factor.execution_cash import CashProof, check_cash_state
from qlab.dynamic_factor.execution_projection import project
from qlab.dynamic_factor.execution_risk import RiskBook
from qlab.dynamic_factor.execution_risk_history import RiskHistory
from qlab.dynamic_factor.execution_signals import fixed_scores
from projection_test_helpers import case
from test_execution_accounting import account
from test_execution_candidate import intent_case
from test_execution_risk_history import history


class ReleaseContextTestDouble:
    """No issuer and no canonical type; must fail the production entry."""


class ReleaseContextCheckerTestDouble:
    """A diagnostic delegation probe which always refuses, never returns a guard."""

    def __init__(self):
        self.calls = []

    def __call__(
        self, guard, policy, release_context=None, expected_release_identity_bytes=None
    ):
        self.calls.append((release_context, expected_release_identity_bytes))
        raise ValueError("TEST_ONLY.release_context_probe_refusal")


def identity(version="A-test-version-one"):
    """Untrusted identity data used only for serialization/mismatch controls."""
    _, args, _ = case()
    policy = args["policy"]
    binding = dict(
        policy.binding,
        date_manifest_sha256=sha256(policy.raw_date_manifest),
        common_calendar_sha256=policy.date_manifest["common_calendar_sha256"],
        universe=list(policy.profile["universe"]),
    )
    value = dict(
        schema="EVO884.BReleaseContextIdentity/v1",
        context_version=version,
        release_id="TEST_ONLY",
        release_version="TEST_ONLY",
        adoption_sha256=digest("TEST_ONLY"),
        h_a=digest(version),
        h_r=digest("R"),
        h_p=digest("P"),
        h_c=digest("C"),
        h_d=digest("D"),
        receiver_id="TEST_ONLY",
        implementation_id="TEST_ONLY",
        implementation_sha256=digest("TEST_ONLY"),
        accepted_at="2000-01-01T00:00:00Z",
        acceptance_time_evidence_sha256=digest("TEST_ONLY"),
        policy_binding=binding,
        annotation_binding=dict(
            issue_id="00000000-0000-0000-0000-000000000001",
            comment_id="00000000-0000-0000-0000-000000000002",
            revision=1,
            content_sha256=digest("TEST_ONLY"),
        ),
    )
    return canonical(
        dict(
            schema="EVO884.BReleaseContextBinding/v1",
            identity=value,
            identity_sha256=digest(value),
        )
    )


def unavailable(call):
    with pytest.raises(
        ValueError, match="^B.release_context_implementation_unavailable$"
    ):
        call()


@pytest.mark.parametrize("context", [None, {}, ReleaseContextTestDouble()])
def test_T10_real_bridge_without_B01_refuses_formal_guard_and_has_no_reader(context):
    _, args, _ = case()
    guard = deepcopy(args["guard"])
    guard["schema"] = "EVO883.BRuntimeGuard/v1"
    before = deepcopy(guard)
    unavailable(lambda: RiskBook.release_guard(guard, args["policy"], context))
    assert guard == before
    assert not hasattr(noncash_v3, "ReleaseContext")
    assert not hasattr(noncash_v3, "check_release_context")


@pytest.mark.parametrize(
    "role,member,recipe",
    [
        ("candidate_solo_probe", "F1-L020", "F1-L020"),
        ("independent_candidate_reference", "CREF-F1-L020", "F1-L020"),
        ("current_META_POLICY_execution_layer", "META_POLICY_V3", "META_POLICY_V3"),
    ],
)
def test_T13_each_role_uses_real_refusal_not_a_test_double_positive(
    role, member, recipe
):
    _, args, _ = case(role=role, member=member, recipe=recipe)
    before = deepcopy(args["state"])
    book = RiskBook(**args, release_context=ReleaseContextTestDouble())
    unavailable(book.snapshot)
    assert args["state"] == before
    assert book._state == before
    assert book._reasons == ["B.release_context_implementation_unavailable"]


@pytest.mark.parametrize("point", ["account", "history", "project", "candidate-cache"])
def test_T10_retained_book_refuses_before_advancing_or_returning_cached_success(point):
    if point == "history":
        book, _ = history()
        before = deepcopy(book._state), book._date, deepcopy(book._prior)
        book._book._release_context = ReleaseContextTestDouble()
        row = {
            k: deepcopy(book._state[k])
            for k in (
                "inventory",
                "cash",
                "nav",
                "rights",
                "receivables",
                "pending_orders",
                "unknown_components",
                "initialization_count",
            )
        }
        row.update(asof=book._date + "T20:00:00Z", fees_x2=book._fees)
        unavailable(
            lambda: book.observe_close(
                book._date,
                row,
                [],
                expected_accounting_sha256=digest(row),
                expected_fills_sha256=digest([]),
            )
        )
        assert (book._state, book._date, book._prior) == before
    elif point == "account":
        book, inputs, *_ = account()
        before = deepcopy(book._state), book._date, deepcopy(book._orders)
        book._release_context = ReleaseContextTestDouble()
        unavailable(book.snapshot)
        assert (book._state, book._date, book._orders) == before
    elif point == "project":
        inputs, args, signal = case()
        book = RiskBook(**args)
        snap = book.snapshot()
        book._release_context = ReleaseContextTestDouble()
        unavailable(
            lambda: project(
                inputs,
                risk_book=book,
                risk_signal=signal,
                execution_binding=args["scope"]["execution_binding"],
                expected_input_sha256=digest(inputs),
                expected_snapshot_sha256=snap["snapshot_sha256"],
                expected_signal_sha256=digest(signal),
            )
        )
        assert book._state == args["state"]
    else:
        inputs, _, template, kwargs = intent_case()
        intent = CandidateIntent(template, **kwargs)
        opened = CandidateOpen(
            inputs["execution_open"], expected_sha256=digest(inputs["execution_open"])
        )
        out = intent.next_open(opened)
        assert out["complete"] and out["seal_status"] == "seal_pending"
        intent._book._release_context = ReleaseContextTestDouble()
        unavailable(lambda: intent.next_open(opened))
        assert intent._result == out


def test_T11_diagnostic_probe_observes_the_same_context_and_bytes_then_refuses(
    monkeypatch,
):
    _, args, _ = case()
    context = ReleaseContextTestDouble()
    binding = identity()
    probe = ReleaseContextCheckerTestDouble()
    # Patch only the owned bridge for a named diagnostic refusal, never B01 exports.
    with monkeypatch.context() as m:
        m.setattr(CashProof, "release_guard", staticmethod(probe))
        with pytest.raises(ValueError, match="TEST_ONLY"):
            RiskBook.release_guard(args["guard"], args["policy"], context, binding)
    assert probe.calls == [(context, binding)]
    unavailable(
        lambda: RiskBook.release_guard(args["guard"], args["policy"], context, binding)
    )
    assert not hasattr(noncash_v3, "ReleaseContext")


@pytest.mark.parametrize(
    "bad", [b"{}", b'{"schema":1,"schema":2}', b'{"x":NaN}', b'{"x":Infinity}']
)
def test_T11_identity_decoder_rejects_malformed_data_without_creating_a_capability(bad):
    with pytest.raises(ValueError, match="B.release_context_encoding_invalid"):
        CashProof.binding_value(bad)


def test_T11_identity_bytes_are_stable_and_new_version_has_new_identity():
    raw = identity()
    assert CashProof.binding_bytes(CashProof.binding_value(raw)) == raw
    assert raw == identity()
    assert raw != identity("A-test-version-two")
    assert b"a_raw" not in raw and b"issuer" not in raw
    payload = RiskBook.release_payload(dict(schema="EVO884.CloseRiskSnapshot/v1"), raw)
    assert payload["schema"] == "EVO884.CloseRiskSnapshot/v1-BR1"
    assert CashProof.binding_bytes(payload["release_context_binding"]) == raw
    assert not isinstance(payload, ReleaseContextTestDouble)


@pytest.mark.parametrize(
    "mutation", ["host-absent", "A-mixed", "context-absent", "context-wire"]
)
def test_T11_restore_compares_disk_host_context_before_first_replay(
    monkeypatch, mutation
):
    book, args = history()
    payload = json.loads(book.export_bytes())
    payload = RiskBook.release_payload(payload, identity())
    if mutation == "context-wire":
        payload["initial"]["release_context"] = dict(approved=True)
    raw = canonical(payload)
    expected = (
        None
        if mutation == "host-absent"
        else identity(
            "A-test-version-two" if mutation == "A-mixed" else "A-test-version-one"
        )
    )
    context = None if mutation == "context-absent" else ReleaseContextTestDouble()
    touched = []
    with monkeypatch.context() as m:
        m.setattr(RiskHistory, "observe_close", lambda *a, **k: touched.append(True))
        with pytest.raises(ValueError, match="B.release_context_"):
            RiskHistory.restore(
                raw,
                expected_sha256=sha256(raw),
                expected_book_id=book._book_id,
                expected_scope=args["scope"],
                policy=args["policy"],
                release_context=context,
                expected_release_identity_bytes=expected,
            )
    assert touched == []


def test_T12_unknown_rights_still_refuse_without_changing_inventory_or_clock():
    _, args, _ = case()
    state = deepcopy(args["state"])
    state["rights"] = {"UNKNOWN_CHILD": 1}
    before = deepcopy(state)
    with pytest.raises(ValueError):
        check_cash_state(state, args["guard"], None)
    assert state == before


def test_T20_changed_history_source_is_refused_before_any_event_replay(monkeypatch):
    book, args = history()
    payload = json.loads(book.export_bytes())
    payload["history_source_sha256"] = digest("TEST_ONLY old source")
    raw = canonical(payload)
    calls = []
    monkeypatch.setattr(
        RiskHistory, "observe_close", lambda *a, **k: calls.append(True)
    )
    with pytest.raises(ValueError, match="^risk.history_replay_mismatch$"):
        RiskHistory.restore(
            raw,
            expected_sha256=sha256(raw),
            expected_book_id=book._book_id,
            expected_scope=args["scope"],
            policy=args["policy"],
        )
    assert calls == []


def test_T10_exact_cost_bridge_does_not_call_original_fee_when_context_is_unavailable(
    monkeypatch,
):
    from qlab.dynamic_factor import fee_model

    _, args, signal = case()
    calls = []
    monkeypatch.setattr(fee_model, "order_cost", lambda *a, **k: calls.append(True))
    cost = ExactOrderCosts(
        args["policy"], signal["execution_session"], "research_restored"
    )
    unavailable(
        lambda: cost.quote_exact(
            {"QQQ": 1},
            {"QQQ": Decimal("100")},
            guard=args["guard"],
            execution_binding=args["scope"]["execution_binding"],
            release_context=ReleaseContextTestDouble(),
        )
    )
    assert calls == []


def test_T13_fixed_signal_checks_context_before_consuming_history_numbers():
    _, args, _ = case()
    # Invalid values must not be consumed before the missing receiver is rejected.
    values = {"AAPL": ["NOT_A_NUMBER"] * 21, "COST": ["NOT_A_NUMBER"] * 21}
    unavailable(
        lambda: fixed_scores(
            "F1-L020",
            values,
            eligible=list(values),
            guard=args["guard"],
            policy=args["policy"],
            execution_binding=args["scope"]["execution_binding"],
            expected_histories_sha256=digest(values),
            release_context=ReleaseContextTestDouble(),
        )
    )


def test_B_step3_old_accounting_bytes_fail_the_exact_updated_source_pin(
    tmp_path, monkeypatch, record_property
):
    from qlab.dynamic_factor import scope_proof
    from qlab.dynamic_factor.conventions import load_conventions

    root = Path(scope_proof.__file__).parent
    before = (root / "execution_accounting.py").read_bytes()
    old = (
        Path(__file__).parent / "fixtures/b-release/old-execution-accounting.py.fixture"
    ).read_bytes()
    assert (
        sha256(old)
        == "36ba63882a55e97e6d040b48ed15fcdf7246ba1f27f16faa47414adb585d0e6d"
    )
    assert sha256(before) == scope_proof.FIXED_READER_SOURCES["execution_accounting.py"]
    assert sha256(old) != sha256(before)
    # Positive static source inspection, not a B01/A/runtime positive.
    assert (
        scope_proof.b2_isolation_proof(load_conventions())["seal_status"]
        == "seal_pending"
    )
    private = tmp_path / "B_STEP3_PRIVATE_AST_ONLY"
    private.mkdir()
    for source in root.glob("*.py"):
        (private / source.name).write_bytes(source.read_bytes())
    for _, relative, _ in scope_proof.FIXED_READS:
        target = private / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((root / relative).read_bytes())
    (private / "execution_accounting.py").write_bytes(old)
    # Only inspect these immutable old bytes; never import or execute the copy.
    with monkeypatch.context() as patch:
        patch.setattr(scope_proof, "__file__", str(private / "scope_proof.py"))
        with pytest.raises(
            ValueError, match="^scope.file_access_not_whitelisted$"
        ) as refused:
            scope_proof.b2_isolation_proof(load_conventions())
    assert (root / "execution_accounting.py").read_bytes() == before
    record_property(
        "B_step3_pin_actual",
        json.dumps(
            dict(
                old_raw_sha256=sha256(old),
                current_raw_sha256=sha256(before),
                reason=str(refused.value),
                scope="static inspection; private old source not executed",
            ),
            sort_keys=True,
        ),
    )
