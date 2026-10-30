"""B7 audit 01a18c4d-486d-70b6-b279-567d00832006, plus consumer variants."""

from copy import deepcopy

import pytest

from qlab.dynamic_factor.contract import digest
from qlab.dynamic_factor.continuity import continuous_path_check
from qlab.dynamic_factor.conventions import load_conventions
from qlab.dynamic_factor.event_quarantine import field_rules, sources
from qlab.dynamic_factor.scope_harness import continuity_fixture


SEED = dict(
    id="unresolved-origin",
    field="raw_open",
    parents=[],
    symbol="B",
    date="2010-01-04",
    value=5,
)
FIELDS = field_rules(sources()[0])


def assert_blocked(request):
    before = deepcopy(request)
    report = continuous_path_check(request)
    assert request == before
    assert not report["ok"]
    m = report["metrics"]
    assert not m["state_receipt_grid_complete"]
    assert len(m["folds"]) == 77
    assert all(row["nav"] is None and row["reasons"] for row in m["folds"])
    assert all(m[k] is None for k in ("A", "IR", "interval"))
    for index, (raw, got) in enumerate(
        zip(request["folds"], m["submitted_declarations"])
    ):
        assert got["input_index"] == index and got["raw_declaration"] == raw
        assert all(
            got[k] == raw.get(k)
            for k in ("fold_id", "attempt_id", "attempted", "budget_state", "N_receipt")
        )
    q = m["event_quarantine"]
    assert not q["ok"] and len(FIELDS) == 42
    for field in FIELDS:
        assert q["metrics"]["readouts"][field] is None
        assert not q["metric_availability"][field]["available"]
        assert q["metric_availability"][field]["reason"]
    return q


@pytest.mark.parametrize("scope", ["row", "all_states"])
def test_original_B7_continuity_reproductions(scope):
    request = continuity_fixture(load_conventions())
    if scope == "row":
        request["folds"][0]["dependency_nodes"] = [deepcopy(SEED)]
    else:
        # Exact audit construction: repeated identities in every state, with
        # authentic recomputed hashes. It is not a hash-corruption negative.
        for row in request["folds"]:
            for key in ("input_state", "output_state"):
                row[key]["dependency_nodes"] = [deepcopy(SEED)]
                row[key + "_sha256"] = digest(row[key])
    assert_blocked(request)


@pytest.mark.parametrize("scope", ["row", "input_state", "output_state"])
@pytest.mark.parametrize("kind", ["dependency_nodes", "panel_inputs"])
def test_each_supported_scope_consumes_all_42_fields_before_any_fold_NAV(scope, kind):
    request = continuity_fixture(load_conventions())
    row = request["folds"][0]
    target = row if scope == "row" else row[scope]
    target["dependency_nodes"] = [deepcopy(SEED)]
    target.setdefault(kind, []).extend(
        dict(id=field, field=field, symbol="QQQ", parents=[SEED["id"]], value=123)
        for field in FIELDS
    )
    if scope != "row":
        row[scope + "_sha256"] = digest(target)
    q = assert_blocked(request)
    projections = {r["field"]: r for r in q["metrics"]["projected_nodes"]}
    for field in FIELDS:
        assert projections[field]["value"] is None
        assert projections[field]["reasons"]
        assert "inherited:B" in projections[field]["event_keys"]


def test_ancestor_in_prior_fold_is_consumed_by_later_state():
    request = continuity_fixture(load_conventions())
    request["folds"][0]["dependency_nodes"] = [deepcopy(SEED)]
    request["folds"][1]["input_state"]["panel_inputs"] = [
        dict(symbol="QQQ", field="cross_fold_state", parents=[SEED["id"]], value=999)
    ]
    row = request["folds"][1]
    row["input_state_sha256"] = digest(row["input_state"])
    q = assert_blocked(request)
    carried = next(
        r for r in q["metrics"]["projected_nodes"] if r["field"] == "cross_fold_state"
    )
    assert carried["value"] is None and "inherited:B" in carried["event_keys"]


@pytest.mark.parametrize(
    "extra",
    [
        {"lineage": {"source": "B"}},
        {"wrapper": {"dependency_nodes": [SEED]}},
        {"dependency_nodes": {"nodes": [SEED]}},
        {"panel_inputs": None},
        {"dependency_graph": [SEED]},
    ],
)
def test_unknown_or_malformed_lineage_is_never_an_empty_dependency_graph(extra):
    request = continuity_fixture(load_conventions())
    request["folds"][0]["input_state"].update(deepcopy(extra))
    q = assert_blocked(request)
    assert any("lineage" in r for r in q["reasons"])


@pytest.mark.parametrize("conflicting", [False, True])
def test_cross_scope_duplicate_and_conflicting_identity_explicitly_refuse(conflicting):
    request = continuity_fixture(load_conventions())
    request["dependency_nodes"] = [dict(SEED, symbol="QQQ")]
    request["folds"][0]["dependency_nodes"] = [
        dict(SEED, symbol="B" if conflicting else "QQQ")
    ]
    q = assert_blocked(request)
    assert q["reasons"] == ["data.v10_duplicate_dependency_identity"]


def test_clean_cross_fold_graph_still_accepts_structural_receipt():
    request = continuity_fixture(load_conventions())
    request["folds"][0]["dependency_nodes"] = [dict(SEED, symbol="QQQ")]
    request["folds"][1]["panel_inputs"] = [
        dict(field="cross_fold_state", symbol="QQQ", parents=[SEED["id"]], value=123)
    ]
    report = continuous_path_check(request)
    assert report["ok"] and report["metrics"]["state_receipt_grid_complete"]
    projected = report["metrics"]["event_quarantine"]["metrics"]["projected_nodes"]
    assert (
        next(r for r in projected if r["field"] == "cross_fold_state")["value"] == 123
    )


def test_explicit_panel_identity_cannot_replace_a_prior_dependency():
    request = continuity_fixture(load_conventions())
    request["dependency_nodes"] = [dict(SEED, symbol="QQQ")]
    request["folds"][0]["panel_inputs"] = [dict(SEED)]
    assert assert_blocked(request)["reasons"] == [
        "data.v10_duplicate_dependency_identity"
    ]
