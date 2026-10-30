from copy import deepcopy

import pytest

from b10_reference_helpers import TIME_CASES, exercise, resign_scope, wire_fixture


@pytest.fixture(scope="module")
def wire(tmp_path_factory):
    root = tmp_path_factory.mktemp("b10-time") / "inputs"
    return root, wire_fixture(root)


@pytest.mark.parametrize("case", TIME_CASES)
def test_timing_in_real_compiler_and_isolated_worker_before_any_reader(wire, case):
    root, original = wire
    changes, accepted = TIME_CASES[case]
    request = deepcopy(original)
    request["sealed_scope"].update(changes)
    resign_scope(request)
    out = exercise(root, request)
    for side in ("host", "worker"):
        report = out[side]
        assert report["complete"] is accepted
        if not accepted:
            assert report["reader_calls"] == 0
            assert report["accessed_roles"] == []
            assert report["reason"]
        else:
            assert report["reader_calls"] > 0
    if accepted:
        assert out["worker"]["accessed_roles"] == ["benchmark", "panel", "profile"]
