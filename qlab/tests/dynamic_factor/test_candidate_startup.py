"""C13 uses the owned C05 class, with byte-preserved reference startup."""

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

from qlab.dynamic_factor.contract import canonical, sha256
from qlab.dynamic_factor.execution_startup import StartupBook
from qlab.dynamic_factor.reference_registry_v3 import DISPATCH
from test_execution_startup import book, day


MEMBERS = [
    f"F{family}-L{window:03}" for family in (1, 2, 3, 4) for window in (5, 10, 20, 60)
] + ["META_POLICY_V3"]
BASELINE = (
    Path(__file__).parent / "fixtures/c13-startup-baseline/execution_startup.py.fixture"
)


def old_class():
    # Independent fixed parent bytes. Never use the DUT to generate its base.
    assert (
        sha256(BASELINE.read_bytes())
        == "8bce00e43fcb043327caada9dd29e8420c5a9969b93e2125200e6b0f5d706cf1"
    )
    loader = SourceFileLoader("qlab.dynamic_factor._startup_pre_C13", str(BASELINE))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module.StartupBook


def candidate_book(member):
    seed = book()
    return StartupBook(
        member,
        "0",
        "C13-SYNTHETIC-ONLY",
        seed.snapshot()["genesis"],
        seed._context,
        execution_binding=seed._execution_binding,
        execution_role="current_META_POLICY_execution_layer"
        if member == "META_POLICY_V3"
        else "candidate_solo_probe",
        policy=seed._policy,
    )


@pytest.mark.parametrize("member", MEMBERS)
def test_C13_17_candidates_use_same_class_and_three_day_algorithm(
    member, record_property
):
    seed = book()
    with pytest.raises(
        ValueError, match="reference.member_not_registered_or_incomplete"
    ):
        old_class()(
            member,
            "0",
            "C13-SYNTHETIC-ONLY",
            seed.snapshot()["genesis"],
            seed._context,
            execution_binding=seed._execution_binding,
            policy=seed._policy,
        )
    new = candidate_book(member)
    assert type(new) is StartupBook
    assert new.identity["member_id"] == member
    assert new.identity["execution_role"] == (
        "current_META_POLICY_execution_layer"
        if member == "META_POLICY_V3"
        else "candidate_solo_probe"
    )
    quantities = []
    for i in range(3):
        _, opened, _, reads = day(new, i)
        quantities.append(opened["quantity"])
        assert reads == [(new.sessions[i + 1], "QQQ")]
    assert quantities == [60, 59, 27]
    assert new.snapshot()["startup_complete"] is True
    assert new.snapshot()["complete_account_state"] is None
    assert new.snapshot()["current_risk_state"] is None
    raw = new.export_bytes()
    restored = StartupBook.restore(
        raw,
        expected_sha256=sha256(raw),
        member_id=member,
        fold_id="0",
        attempt_id="C13-SYNTHETIC-ONLY",
    )
    assert restored.export_bytes() == raw
    record_property("C13_startup_actual", member + ": old=refused/new=three_opens")


@pytest.mark.parametrize("member", sorted(DISPATCH))
def test_C13_four_reference_snapshots_and_summaries_keep_parent_raw_bytes(member):
    new = book(member)
    old = old_class()(
        member,
        "0",
        "C05-SYNTHETIC-ONLY",
        new.snapshot()["genesis"],
        new._context,
        execution_binding=new._execution_binding,
        policy=new._policy,
    )
    assert canonical(old.snapshot()) == canonical(new.snapshot())
    assert old.export_bytes() == new.export_bytes()
    for i in range(3):
        assert canonical(day(old, i)) == canonical(day(new, i))
        assert canonical(old.snapshot()) == canonical(new.snapshot())
        assert old.export_bytes() == new.export_bytes()


def test_C13_unregistered_member_and_role_relabel_are_rejected_before_read():
    with pytest.raises(
        ValueError, match="reference.member_not_registered_or_incomplete"
    ):
        candidate_book("F5-L020")
    seed = book()
    with pytest.raises(ValueError, match="reference.execution_role_mismatch"):
        StartupBook(
            "F1-L020",
            "0",
            "C13",
            seed.snapshot()["genesis"],
            seed._context,
            execution_binding=seed._execution_binding,
            execution_role="independent_candidate_reference",
            policy=seed._policy,
        )
