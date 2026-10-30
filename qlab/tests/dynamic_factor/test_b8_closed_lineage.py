"""B8 scalar/alias escapes and nested closed-schema acceptance evidence."""

from copy import deepcopy

import pytest

from qlab.dynamic_factor.contract import digest
from qlab.dynamic_factor.continuity import continuous_path_check
from qlab.dynamic_factor.conventions import load_conventions
from qlab.dynamic_factor.scope_harness import continuity_fixture
from qlab.dynamic_factor.event_quarantine import normalize_dependencies


def last_state_case():
    request = continuity_fixture(load_conventions())
    row = request["folds"][-1]
    return request, row, row["output_state"]


def check(request, row, *, blocked):
    row["output_state_sha256"] = digest(row["output_state"])
    assert row["output_state_sha256"] == digest(row["output_state"])
    before = deepcopy(request)
    report = continuous_path_check(request)
    metrics = report["metrics"]
    assert request == before
    assert len(metrics["folds"]) == len(metrics["submitted_declarations"]) == 77
    for raw, submitted in zip(request["folds"], metrics["submitted_declarations"]):
        assert submitted["raw_declaration"] == raw
        for key in ("attempt_id", "attempted", "budget_state", "N_receipt"):
            assert submitted[key] == raw.get(key)
    assert report["ok"] is not blocked
    assert metrics["state_receipt_grid_complete"] is not blocked
    if blocked:
        assert report["reasons"]
        assert all(f["nav"] is None and f["reasons"] for f in metrics["folds"])
    else:
        assert all(f["nav"] is not None for f in metrics["folds"])
    return report


@pytest.mark.parametrize(
    "extra",
    [
        {"dependency_graph": "B|2023-08-30"},
        {"wrapper": {"dependency_graph": "B|2023-08-30"}},
        {"dependencies": ["B|2023-08-30"]},
        {"ancestry": {"source": "B|2023-08-30"}},
        {"Dependency_Graph": "B|2023-08-30"},
    ],
)
def test_B8_last_output_state_with_authentic_SHA_refuses(extra):
    request, row, state = last_state_case()
    state.update(deepcopy(extra))
    check(request, row, blocked=True)


@pytest.mark.parametrize(
    "scope", ["request", "fold", "state", "node", "value", "budget", "N", "checkpoint"]
)
@pytest.mark.parametrize("value", [None, False, 7, "B|2023-08-30", [], {}])
@pytest.mark.parametrize("key", ["dependency_graph", "ancestry", "unknown_key"])
def test_every_unknown_key_refuses_independently_of_value_type_and_depth(
    scope, value, key
):
    request, row, state = last_state_case()
    node = dict(
        id="clean",
        field="nav",
        symbol="QQQ",
        parents=[],
        value={"alias": {"cash": 7}},
        reconciliation_checkpoint={"verified": True, "sha256": "c" * 64},
    )
    state["dependency_nodes"] = [node]
    targets = dict(
        request=request,
        fold=row,
        state=state,
        node=node,
        value=node["value"]["alias"],
        budget=row["budget_state"],
        N=row["N_receipt"],
        checkpoint=node["reconciliation_checkpoint"],
    )
    targets[scope][key] = deepcopy(value)
    check(request, row, blocked=True)


@pytest.mark.parametrize("value", [0, False, "B", [], {"dependency_graph": "B"}])
@pytest.mark.parametrize(
    "field", ["budget_state", "N_receipt", "inventory", "input_state", "output_state"]
)
def test_known_record_names_do_not_allow_arbitrary_value_types(field, value):
    request, row, _ = last_state_case()
    row[field] = deepcopy(value)
    # Direct schema validation also checks malformed output_state before its
    # owner's state hashing/continuity checks can mask a schema failure.
    with pytest.raises(ValueError, match="lineage"):
        normalize_dependencies(request)


def test_clean_complete_control_preserves_nested_numeric_aliases_and_metadata():
    request, row, state = last_state_case()
    node = dict(
        id="clean",
        field="cash",
        symbol="QQQ",
        parents=[],
        value={
            "value": 912,
            "nav": 913,
            "NAV": 9,
            "alias": {"cash": 914},
            "nested_numeric": 777,
            "formal_alias": 888,
        },
        client_identity="B7-B8-control",
    )
    state["dependency_nodes"] = [node]
    report = check(request, row, blocked=False)
    projected = report["metrics"]["event_quarantine"]["metrics"]["projected_nodes"]
    assert projected[0]["submitted"] == node
    assert projected[0]["value"] == node["value"]


def test_deep_known_aliases_cannot_hide_an_unknown_key():
    request, row, state = last_state_case()
    value = {"dependency_graph": False}
    for _ in range(80):
        value = {"alias": value}
    state["panel_inputs"] = [dict(field="cash", symbol="QQQ", value=value)]
    check(request, row, blocked=True)
