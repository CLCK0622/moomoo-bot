import pytest

from b10_reference_helpers import wire_fixture
from lt50_harness import (
    SCOPE_CASES,
    downstream_negative,
    missing_member,
    positive,
    scope_negative,
)
from v3_reference_helpers import unit_scope

from qlab.dynamic_factor.reference_compile_v3 import compile_panel


@pytest.fixture(scope="module")
def wire(tmp_path_factory):
    root = tmp_path_factory.mktemp("lt50") / "inputs"
    return root, wire_fixture(root, verified=49)


def test_LT50_verified_day_prepares_but_never_becomes_runtime_reference(wire):
    positive(*wire)


@pytest.mark.parametrize("case", SCOPE_CASES)
def test_LT50_scope_rejects_invalid_day_before_host_or_worker_reads(wire, case):
    scope_negative(*wire, case)


def test_LT50_missing_family_member_is_not_a_complete_preparation(wire):
    missing_member(*wire)


@pytest.mark.parametrize(
    "case",
    [
        "missing_returns",
        "null",
        "nan",
        "inf",
        "preparation_complete_is_not_reference_usable",
    ],
)
def test_LT50_downstream_rejects_missing_performance_and_preparation_promotion(
    wire, case
):
    root, request = wire
    prepared = positive(root, request)["worker"]
    downstream_negative(request, prepared, case)


@pytest.mark.parametrize("verified", [1, 49, 50])
def test_scope_complete_accepts_verified_nonempty_days_without_GE50_admission(verified):
    scope = unit_scope(verified=verified)
    assert scope["complete"] is True
    assert len(compile_panel(scope, lambda *a: 100)["rows"][0]["prices"]) == verified


@pytest.mark.parametrize("kwargs", [dict(verified=0), dict(real=True)])
def test_scope_complete_remains_false_for_empty_or_unknown_days(kwargs):
    scope = unit_scope(**kwargs)
    assert scope["complete"] is False
    calls = []
    with pytest.raises(ValueError, match="quantity_unknown_or_insufficient"):
        compile_panel(scope, lambda *a: calls.append(a) or 100)
    assert calls == []
