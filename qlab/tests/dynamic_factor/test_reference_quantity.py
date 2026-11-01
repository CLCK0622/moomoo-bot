import json
from copy import deepcopy

import pytest

from b10_reference_helpers import wire_fixture
from lt50_quantity_harness import CASES, attack, rehash, refused
from v3_reference_helpers import unit_scope

from qlab.dynamic_factor.reference_compile_v3 import compile_panel


@pytest.fixture(scope="module")
def wire(tmp_path_factory):
    root = tmp_path_factory.mktemp("quantity") / "inputs"
    return root, wire_fixture(root, verified=49)


@pytest.mark.parametrize("case", CASES)
def test_recomputed_quantity_rejects_resigned_attack_before_both_readers(wire, case):
    root, original = wire
    request = attack(original, case)
    before = deepcopy(request)
    refused(root, request)
    assert request == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("verified_count", 49.0),
        ("upper_bound", 49.0),
        ("upper_bound", 48),
        ("upper_bound", 50),
        ("new_tilt_allowed", 0),
    ],
)
def test_summary_types_and_bounds_cannot_replace_individual_facts(wire, field, value):
    root, original = wire
    request = deepcopy(original)
    day = request["sealed_scope"]["days"][request["sealed_scope"]["train"][0]]
    day[field] = value
    rehash(request)
    refused(root, request)


def test_recomputed_UNKNOWN_is_rejected_even_when_reported_honestly():
    scope = unit_scope(verified=49)
    day = next(iter(scope["days"].values()))
    symbol = next(s for s, state in day["states"].items() if state == "QUARANTINED")
    day["states"][symbol] = "UNKNOWN"
    day.update(upper_bound=50, quantity_state="UNKNOWN")
    request = {"sealed_scope": scope}
    rehash(request)
    calls = []
    with pytest.raises(ValueError) as error:
        compile_panel(scope, lambda *a: calls.append(a) or 100)
    details = json.loads(str(error.value).split(": ", 1)[1])
    assert details["reported"] == details["recomputed"]
    assert details["recomputed"]["quantity_state"] == "UNKNOWN"
    assert calls == []
