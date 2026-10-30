import json
from copy import deepcopy

from qlab.dynamic_factor.conventions import FIXTURES, load_conventions
from qlab.dynamic_factor.contract import sha256


def replay(before, changes):
    value = deepcopy(before)
    for change in changes:
        parts = change["path"].strip("/").split("/")
        parent = value
        for part in parts[:-1]:
            parent = parent[part]
        key = parts[-1]
        if "before" in change:
            assert parent[key] == change["before"]
        else:
            assert key not in parent
        if change["operation"] == "remove":
            del parent[key]
        else:
            parent[key] = change["after"]
    return value


def test_frozen_55_and_61_changes_replay_exactly_without_editing_v2():
    diff = json.loads((FIXTURES / "v2-to-v3-diff.json").read_bytes())
    for role, old, new, count in [
        ("main", "prereg-v2.json", "prereg-v3.json", 55),
        ("interface", "conventions-v2.0.0.json", "conventions-v3.0.0.json", 61),
    ]:
        before, after = [(FIXTURES / x).read_bytes() for x in (old, new)]
        assert sha256(before) == diff["before_" + role + "_sha256"]
        assert sha256(after) == diff["after_" + role + "_sha256"]
        assert len(diff[role + "_changes"]) == count
        assert replay(json.loads(before), diff[role + "_changes"]) == json.loads(after)


def test_v3_is_a_new_profile_and_not_runtime_permission():
    p = load_conventions()
    v2 = load_conventions(FIXTURES / "conventions-v2.0.0.json")
    assert p.document["version"] == "v3.0.0"
    assert p.binding["common_profile_sha256"] != v2.binding["common_profile_sha256"]
    assert p.profile["universe"] == v2.profile["universe"]
    assert p.calendar == v2.calendar
    assert p.document["folds"] == v2.document["folds"]
    assert not p.document["noncash_exposure_policy"]["run_authorization"]
    assert not p.document["runtime_consumable"]
