from copy import deepcopy

import pytest

from qlab.dynamic_factor.contract import digest
from qlab.dynamic_factor.conventions import load_conventions
from qlab.dynamic_factor.event_quarantine import quarantine_check


def manifest(nodes=None):
    p = load_conventions()
    row = dict(
        symbol="AAPL",
        field_role="selection",
        from_date=p.calendar[600],
        to_date_or_null_with_reason=p.calendar[600],
        reason="SYNTHETIC",
        source_sha256=digest("synthetic_source"),
        evidence_version="SYNTHETIC/v3",
        state="UNKNOWN",
        gates_by_date={},
        received_at="2026-10-01T00:00:00Z",
        dependency_lineage=nodes
        or [dict(id="source", field="raw_open", symbol="AAPL", parents=[], value=5)],
    )
    request = dict(
        role="test_meta",
        records=[row],
        mode="history",
        sealed_at="2026-10-02T00:00:00Z",
        first_performance_at="2026-10-03T00:00:00Z",
    )
    value = dict(request=request, **p.binding)
    return dict(value, quarantine_manifest_sha256=digest(value))


def test_registered_lineage_enters_the_same_graph_and_propagates_to_cash():
    m = manifest(
        [dict(id="B-source", field="raw_open", symbol="B", parents=[], value=10)]
    )
    request = dict(
        isolation_manifest=m,
        dependency_nodes=[
            dict(id="cash", field="cash", parents=["B-source"], value=100)
        ],
    )
    before = deepcopy(request)
    report = quarantine_check(request)
    assert request == before and not report["ok"]
    nodes = {r["id"]: r for r in report["metrics"]["projected_nodes"]}
    assert nodes["cash"]["value"] is None
    assert "inherited:B" in nodes["cash"]["event_keys"]


def test_valid_independent_v3_lineage_is_inspected():
    report = quarantine_check(dict(isolation_manifest=manifest()))
    assert report["ok"]
    assert [r["id"] for r in report["metrics"]["projected_nodes"]] == ["source"]


@pytest.mark.parametrize("scope", ["root", "manifest"])
def test_unregistered_guard_refuses_without_importing_future_block(scope):
    # This commit predates noncash_v3. Unknown structures must be refused by
    # the closed schema, never imported or treated as an unbound exemption.
    request = {"noncash_guard_manifest": {}}
    if scope == "manifest":
        m = manifest()
        m["request"].update(request)
        request = {"isolation_manifest": m}
    assert not quarantine_check(request)["ok"]


@pytest.mark.parametrize(
    "hidden", [{"lineage": []}, {"dependency_receipt": {}}, {"nested": {"parents": []}}]
)
def test_unknown_container_keywords_still_refuse(hidden):
    report = quarantine_check(dict(unregistered=hidden))
    assert report["reasons"] == ["data.v10_unknown_lineage_structure"]


@pytest.mark.parametrize(
    "attack",
    [
        "extra_root",
        "extra_record",
        "hash_list",
        "missing_field",
        "wrong_binding",
        "wrong_type",
        "late",
    ],
)
def test_malformed_isolation_manifest_refuses(attack):
    m = manifest()
    if attack == "extra_root":
        m["not_registered"] = []
    if attack == "extra_record":
        m["request"]["records"][0]["hidden"] = {"lineage": []}
    if attack == "hash_list":
        m["request"]["records"][0]["dependency_lineage"] = [digest("opaque")]
    if attack == "missing_field":
        del m["request"]["records"][0]["source_sha256"]
    if attack == "wrong_binding":
        m["common_profile_sha256"] = digest("other")
    if attack == "wrong_type":
        m["request"]["records"][0]["gates_by_date"] = []
    if attack == "late":
        m["request"]["sealed_at"] = m["request"]["first_performance_at"]
    assert not quarantine_check(dict(isolation_manifest=m))["ok"]


@pytest.mark.parametrize("location", ["fold", "state", "unknown", "input"])
def test_manifest_outside_registered_top_level_refuses(location):
    item = dict(isolation_manifest=manifest())
    request = (
        dict(folds=[item])
        if location == "fold"
        else dict(input_state=item)
        if location == "state"
        else dict(inputs=[item])
        if location == "input"
        else dict(unregistered=item)
    )
    assert not quarantine_check(request)["ok"]


@pytest.mark.parametrize("conflict", [False, True])
def test_lineage_duplicate_and_conflicting_existing_node_refuse(conflict):
    node = dict(
        id="source",
        field="raw_open",
        symbol="AAPL",
        parents=[],
        value=6 if conflict else 5,
    )
    report = quarantine_check(
        dict(isolation_manifest=manifest(), dependency_nodes=[node])
    )
    assert report["reasons"] == ["data.v10_duplicate_dependency_identity"]


@pytest.mark.parametrize(
    "nodes,reason",
    [
        ([dict(id="source", field="cash", parents=["missing"])], "parent_missing"),
        ([dict(id="source", field="cash", parents=["source"])], "cycle"),
    ],
)
def test_lineage_nodes_obey_original_parent_and_cycle_checks(nodes, reason):
    report = quarantine_check(dict(isolation_manifest=manifest(nodes)))
    assert not report["ok"] and reason in report["reasons"][0]
