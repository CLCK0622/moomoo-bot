"""Existing derivation and R-bound metadata, explicit private-host controls."""

from copy import deepcopy
import json

import pytest

from qlab.dynamic_factor import b_release_context as b, catalog_v21, noncash_v3
from qlab.dynamic_factor.contract import digest
from test_b01_release_context import private_host_source as private_host_source, request


def test_original_view_real_checker_and_unchanged_predicate(private_host_source):
    _, policy = private_host_source
    context = b.receive_release_context(policy=policy)
    req = request(context)
    raw = b.check_release_context(context, policy=policy, request=req)
    assert type(raw) is bytes
    assert req["catalog"] == catalog_v21.derive(policy)["catalog"]
    assert digest(json.loads(context.r_raw)["catalog"]) == context.h_c
    assert digest(req["catalog"]) != context.h_c
    guard = dict(request=req, B=[], unknown=[], children=[])
    state = dict(
        inventory={s: 0 for s in req["catalog"]["universe"]},
        cash=15000,
        nav=15000,
        age={},
        origin={},
        rights={},
        receivables={},
        pending_orders=[],
        unknown_components=[],
    )
    before = deepcopy(state)
    assert noncash_v3.zero_exposure(state, guard, initial=True) is None
    # Same lookup as the original forward_event; not an end-to-end event claim.
    assert next(r for r in req["catalog"]["entries"] if r["symbol"] == "ADP")
    assert state == before


@pytest.mark.parametrize("field", ["universe", "calendar_sha256", "entries"])
def test_changed_view_is_rejected(private_host_source, field):
    _, policy = private_host_source
    context = b.receive_release_context(policy=policy)
    req = request(context)
    req["catalog"][field] = None
    with pytest.raises(ValueError, match="^B.release_context_scope_mismatch$"):
        b.check_release_context(context, policy=policy, request=req)


@pytest.mark.parametrize("index", range(64))
def test_each_row_is_bound_not_only_view_hash(private_host_source, index):
    _, policy = private_host_source
    context = b.receive_release_context(policy=policy)
    req = request(context)
    req["catalog"]["entries"][index]["evidence_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="^B.release_context_scope_mismatch$"):
        b.check_release_context(context, policy=policy, request=req)


@pytest.mark.parametrize(
    "style", ["raw_R", "raw_R_with_old_fields", "other_view_version"]
)
def test_no_alternate_or_mixed_catalog_format(private_host_source, style):
    _, policy = private_host_source
    context = b.receive_release_context(policy=policy)
    req = request(context)
    if style == "other_view_version":
        req["catalog"]["entries"][0]["received_at"] = "2026-10-31T00:00:00Z"
    else:
        raw_catalog = json.loads(context.r_raw)["catalog"]
        if style == "raw_R_with_old_fields":
            raw_catalog.update(req["catalog"])
        req["catalog"] = raw_catalog
    with pytest.raises(ValueError, match="^B.release_context_scope_mismatch$"):
        b.check_release_context(context, policy=policy, request=req)


class TEST_ONLY_FixtureRoot:
    def __init__(self, originals, bad_name, reads, path=()):
        self.originals, self.bad_name, self.reads, self.path = (
            originals,
            bad_name,
            reads,
            path,
        )

    def __truediv__(self, name):
        return type(self)(
            self.originals, self.bad_name, self.reads, self.path + (name,)
        )

    def read_bytes(self):
        name = self.path[-1]
        self.reads.append(name)
        if name == self.bad_name:
            return self.originals[name] + b" "
        if (
            self.bad_name == "TEST_ONLY_TWO_INPUTS"
            and name == "EVO883-v21-final-receipt.json"
        ):
            raise FileNotFoundError("TEST_ONLY.two_input_capability")
        return self.originals[name]


@pytest.mark.parametrize(
    "bad_name",
    [
        "EVO893-B-noncash-catalog-v21.csv",
        "EVO893-B-CMI-guard-v21.json",
        "EVO883-v21-final-receipt.json",
        "TEST_ONLY_TWO_INPUTS",
    ],
)
def test_local_original_drift_refuses_before_derive(
    private_host_source, monkeypatch, bad_name
):
    source, policy = private_host_source
    context = b.receive_release_context(policy=policy)
    req = request(context)
    calls, reads = [], []
    monkeypatch.setattr(
        b,
        "_CATALOG_FIXTURES",
        TEST_ONLY_FixtureRoot(source["original_inputs"], bad_name, reads),
    )

    def forbidden_derive(policy):
        calls.append("derive")
        raise AssertionError("derive must not run with drifted inputs")

    monkeypatch.setattr(b, "_derive_catalog", forbidden_derive)
    with pytest.raises(ValueError, match="^B.release_context_release_mismatch$"):
        b.check_release_context(context, policy=policy, request=req)
    assert reads and calls == []
