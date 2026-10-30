import json

import pytest

from qlab.dynamic_factor.conventions import FIXTURES, load_conventions
from qlab.dynamic_factor.contract import digest
from qlab.dynamic_factor.harness_helpers import fixture_ledger
from qlab.dynamic_factor.reference_check import reference_manifest_check
from qlab.dynamic_factor.reference_registry import registered_request
from qlab.dynamic_factor.statistics import dsr_eval
from qlab.dynamic_factor.pipeline import _reference_variance, _n_snapshot


def test_default_is_exact_frozen_v3_and_original_contract_is_preserved():
    p = load_conventions()
    old = load_conventions(FIXTURES / "conventions-v1.0.1.json")
    assert (
        p.raw_sha256
        == "dd13affd23d77b3715a64ffe0403503ea3e6f5850bffdfb7f33bc6f4b44d9e0b"
    )
    assert (
        p.binding["prereg_sha256"]
        == "53e570f7d7c912a078606d167f039d65c56ed0f9f5dadcb7e2ae1091bd949421"
    )
    assert (
        p.binding["common_profile_sha256"]
        == "0fdf644c4c78524cf8a1b91e7f8a6e8275cb568662c1e6aafb2a75b4c8fdf464"
    )
    assert len(p.profile["universe"]) == 64
    assert len(p.calendar) == 3191 and len(p.fold_manifest()["folds"]) == 77
    for key in ("rebalance", "portfolio", "cost_model", "metrics"):
        assert p.profile[key] == old.profile[key]
    assert not p.document["runtime_consumable"]


@pytest.mark.parametrize("book", [47, 253, 1311, 1313])
def test_book_or_seed_is_never_complete_factor_N(tmp_path, book):
    p = load_conventions()
    ledger = fixture_ledger(tmp_path / "unit.sqlite", p)
    assert ledger.genesis["prior_n"] == 0
    assert (
        sum(x["n_trials_total"] for x in ledger.genesis["historical_seed_rows"]) == 47
    )
    ledger.observe_self_report_n(book)
    r = dsr_eval({"complete_N": book, "V": 0.01}, ledger, conventions=p)
    assert r["metrics"]["gate_N"] is None
    assert not r["metrics"]["factor_arm_N_complete"]
    assert r["metrics"]["dsr"] is r["metrics"]["trials_variance"] is None
    assert not r["certifiable"] and not r["runtime_consumable"]
    n = _n_snapshot(ledger, book, p)
    assert n["gate_n"] is None and not n["n_complete"]
    assert n["book_or_request_high_water"] == book


def test_old_registered_reference_does_not_become_v3_by_default():
    r = reference_manifest_check(registered_request())
    assert r["reasons"] == ["reference.profile_or_version_mismatch"]
    assert r["metrics"]["trials_variance"] is None


@pytest.mark.parametrize(
    "mismatch",
    ["old_profile", "v2_profile", "other_mask", "other_derivation", "other_B_release"],
)
def test_old_V_and_other_mask_reference_are_rejected(mismatch):
    p = load_conventions()
    context = dict(
        run_id="current",
        train_calendar=["a", "b", "c"],
        common_profile_sha256=p.binding["common_profile_sha256"],
        universe_and_data_sha256=digest("data"),
        cost_model_sha256=digest("fees"),
        quarantine_manifest_sha256=digest("mask"),
        eligible_set_derivation_sha256=digest("derive"),
        noncash_guard_manifest_sha256=digest("synthetic_guard"),
    )
    spec = p.document["variance_layers"]["independent_reference"]
    trials = {}
    for i in range(spec["minimum_finite_SR_per_complete_reference_family"]):
        tid = str(i)
        trials[tid] = dict(
            trial_id=tid,
            return_role=p.document["N"]["DSR_SR_basis"],
            source_run_id="external",
            profile_id_and_sha256={
                "id": spec["candidate_reference_profile"],
                "sha256": context["common_profile_sha256"],
            },
            universe_and_data_sha256=context["universe_and_data_sha256"],
            cost_model_sha256=context["cost_model_sha256"],
            train_calendar_sha256=digest(context["train_calendar"]),
            scale="daily",
            quarantine_manifest_sha256=context["quarantine_manifest_sha256"],
            eligible_set_derivation_sha256=context["eligible_set_derivation_sha256"],
            returns=[0.001, -0.002, 0.003],
            source_returns_sha256=digest([0.001, -0.002, 0.003]),
            noncash_guard_manifest_sha256=digest("synthetic_guard"),
            zero_exposure_and_consumer_dependency_receipt_sha256=digest(
                "synthetic_proof"
            ),
        )
    t = trials["0"]
    if mismatch in ("old_profile", "v2_profile"):
        t["profile_id_and_sha256"]["sha256"] = load_conventions(
            FIXTURES
            / (
                "conventions-v2.0.0.json"
                if mismatch == "v2_profile"
                else "conventions-v1.0.1.json"
            )
        ).binding["common_profile_sha256"]
    elif mismatch == "other_B_release":
        t["noncash_guard_manifest_sha256"] = digest("other_guard")
    else:
        t[
            "quarantine_manifest_sha256"
            if mismatch == "other_mask"
            else "eligible_set_derivation_sha256"
        ] = digest("other")
    doc = {"candidate": {"members": list(trials), "trials": trials}}
    with pytest.raises(ValueError, match="reference_.*mismatch"):
        _reference_variance(
            {"document": doc, "sha256": digest(doc)}, "candidate", context, p
        )


def test_diff_replays_both_documents_without_changing_v1_bytes():
    d = json.loads((FIXTURES / "v1-to-v2-diff.json").read_bytes())
    for filename, changes, after in [
        ("prereg-v1.json", d["main_changes"], "prereg-v2.json"),
        ("conventions-v1.0.1.json", d["interface_changes"], "conventions-v2.0.0.json"),
    ]:
        obj = json.loads((FIXTURES / filename).read_bytes())
        for c in changes:
            keys = [
                x.replace("~1", "/").replace("~0", "~")
                for x in c["path"].split("/")[1:]
            ]
            node = obj
            for key in keys[:-1]:
                node = node[key]
            if c["operation"] != "add":
                assert node[keys[-1]] == c["before"]
            if c["operation"] == "remove":
                del node[keys[-1]]
            else:
                node[keys[-1]] = c["after"]
        assert obj == json.loads((FIXTURES / after).read_bytes())
