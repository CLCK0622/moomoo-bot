import json

import pytest

from qlab.dynamic_factor.contract import canonical, digest, sha256
from qlab.dynamic_factor.conventions import load_conventions, FIXTURES
from qlab.dynamic_factor.fold_split import shared_views
from qlab.dynamic_factor.reference_check import reference_manifest_check, static_proof
from qlab.dynamic_factor.reference_registry import registered_request as legacy_request
from qlab.dynamic_factor.reference_registry_v3 import (
    registered_request,
    HASHES,
    artifact,
    DISPATCH,
    member_spec,
)
from qlab.dynamic_factor.reference_compile_v3 import (
    compile_panel,
    compile_inputs,
    seal_scope,
)
from qlab.dynamic_factor.reference_boundary import (
    run_isolated,
    prepare_request,
    calendar_sha,
)
from qlab.dynamic_factor.reference_v3_evidence import lineage_proof, runtime_check
from qlab.dynamic_factor.reference_v3_scope import check_panel
from qlab.dynamic_factor.isolation import eligible_day, score_day
from v3_reference_helpers import sealed, unit_scope, protocol_scope, reference_proofs
from test_v2_isolation import synthetic_scores


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_current_reference_rejects_authentic_old_registry_bytes(version):
    r = legacy_request() if version == "v1" else registered_request()
    if version == "v2":
        raw = (FIXTURES / "evo892-v2/predeclared_reference_registry.json").read_text()
        r["registry"] = dict(
            raw=raw, document=json.loads(raw), sha256=sha256(raw.encode())
        )
    assert not reference_manifest_check(r)["ok"]


def test_v3_exact_registry_new_anchor_roles_and_static_worker_boundary():
    r = registered_request()
    assert reference_manifest_check(r)["ok"]
    assert (
        r["registry"]["sha256"]
        == "f531d65a5ad54fc68a8be40bc25cbb3987d0aeedd4c2c345ed334b1599445c48"
    )
    assert r["registry"]["platform_anchor"]["created_at"] == "2026-10-30T10:58:31Z"
    assert all(
        member_spec(m)["execution_profile_id"] == "CANDIDATE_PROBE_V3" for m in DISPATCH
    )
    assert all(artifact(name)["sha256"] == h for name, h in HASHES.items())
    proof = static_proof()
    assert "reference_producer_v3" in proof["import_graph"]
    assert proof["read_whitelist"] == dict(
        panel="panel.json", benchmark="benchmark.json", profile="profile.json"
    )


def test_reference_and_all16_factor_recipes_share_exact_daily_derivation():
    p = load_conventions()
    m = sealed()
    scope = seal_scope(m, [p.calendar[600]], [], p)
    factor = score_day(m, p.calendar[600], lambda names: synthetic_scores(p, names), p)
    assert (
        scope["days"][p.calendar[600]]
        == factor["day"]
        == eligible_day(m, p.calendar[600], p)
    )
    assert all(
        set(row) - set(scope["days"][p.calendar[600]]["eligible"])
        for row in factor["ranks"].values()
    )
    seen = []
    panel = compile_panel(
        scope, lambda date, symbol: seen.append((date, symbol)) or 100
    )
    assert {s for _, s in seen} == set(scope["days"][p.calendar[600]]["eligible"])
    assert set(panel["rows"][0]["prices"]) == {s for _, s in seen}


def test_real_v21_unknown_blocks_before_panel_or_benchmark_callbacks():
    scope = unit_scope(real=True)
    seen = []
    with pytest.raises(ValueError, match="quantity_unknown"):
        compile_inputs(
            scope, lambda *a: seen.append(a) or 100, lambda *a: seen.append(a) or 100
        )
    assert not seen and scope["days"][scope["train"][0]]["quantity_state"] == "UNKNOWN"


def test_real_v21_worker_reads_no_files_and_does_not_substitute_QQQ(tmp_path):
    p = load_conventions()
    fold = p.fold_manifest()["folds"][0]
    view = shared_views(p.calendar, fold, train_days=1260, warmup_days=252)
    manifest = sealed(real=True)
    request = prepare_request(
        p,
        fold,
        view,
        {},
        sealed_manifest=manifest,
        reference_proofs=reference_proofs(
            manifest["request"]["noncash_guard_manifest"]
        ),
    )
    report = run_isolated(tmp_path, request)
    assert "quantity_unknown" in report["reason"]
    assert report["access_boundary_receipt"]["accessed_roles"] == []
    assert report["returns"] is None and not report["runtime_consumable"]


def test_parent_refuses_a_reference_mask_different_from_the_factor_manifest():
    p = load_conventions()
    fold = p.fold_manifest()["folds"][0]
    view = shared_views(p.calendar, fold, train_days=1260, warmup_days=252)
    with pytest.raises(ValueError, match="same_B_and_E_t"):
        prepare_request(
            p,
            fold,
            view,
            {},
            sealed_manifest=sealed(real=True),
            sealed_scope=unit_scope(),
        )


@pytest.mark.parametrize(
    "attack", ["current_returns", "unknown_graph", "changed_E", "old_V"]
)
def test_scope_or_result_substitution_refuses_before_numeric_reader(attack):
    s = unit_scope()
    seen = []
    if attack == "current_returns":
        s["candidate_returns"] = [100]
    if attack == "unknown_graph":
        next(iter(s["days"].values()))["dependency_graph"] = False
    if attack == "changed_E":
        s["numeric_symbols"][s["train"][0]] = s["universe"]
    if attack == "old_V":
        s["V"] = 0.1
    s["scope_sha256"] = digest({k: v for k, v in s.items() if k != "scope_sha256"})
    with pytest.raises(ValueError):
        compile_panel(s, lambda *a: seen.append(a) or 100)
    assert not seen


def test_guarded_field_names_reject_before_attempting_their_numeric_values():
    scope = unit_scope()
    date = scope["train"][0]

    class Canary(dict):
        def __getitem__(self, key):
            raise AssertionError("numeric value was touched")

    with pytest.raises(ValueError, match="guarded_or_unknown"):
        check_panel(
            scope, [dict(date=date, prices=Canary(FORBIDDEN_CHILD=12.0298))], [date]
        )


def test_v3_full_protocol_positive_is_train_only_and_prepares_no_performance(tmp_path):
    p = load_conventions()
    fold = p.fold_manifest()["folds"][0]
    view = shared_views(p.calendar, fold, train_days=1260, warmup_days=252)
    scope = protocol_scope(view.train, view.warmup)
    files = compile_inputs(scope, lambda *a: 100, lambda *a: 100, p)
    bindings = {}
    for role, data in files.items():
        raw = canonical(data)
        (tmp_path / (role + ".json")).write_bytes(raw)
        bindings[role] = dict(file=role + ".json", sha256=sha256(raw))
    declared = artifact("fold-bindings.json")["document"]["folds"][0]
    request = dict(
        view=dict(
            train=list(view.train),
            warmup=list(view.warmup),
            receipt=dict(
                fold_id=fold["fold_id"],
                train_days=1260,
                warmup_days=252,
                shared_object_verified=True,
                train_calendar_sha256=calendar_sha(view.train),
                warmup_calendar_sha256=calendar_sha(view.warmup),
            ),
        ),
        inputs=bindings,
        profile_binding={
            k: p.binding[k]
            for k in (
                "conventions_version",
                "conventions_sha256",
                "prereg_sha256",
                "common_profile_sha256",
            )
        },
        dispatch={m: member_spec(m) for m in sorted(DISPATCH)},
        sealed_scope=scope,
        reference_proofs=reference_proofs(scope["guard"]),
    )
    assert declared["train_session_count"] == 1260
    report = run_isolated(tmp_path, request)
    assert report["schema"] == "reference.producer/v3.0.0"
    assert report["train_rows"] == 1260 and len(report["warmup_dates"]) == 252
    assert (
        report["returns"] is report["sr"] is None and not report["runtime_consumable"]
    )
    assert report["access_boundary_receipt"]["accessed_roles"] == [
        "benchmark",
        "panel",
        "profile",
    ]


def test_v3_lineage_preserves_77_shared_views_and_P4_P7_validator_status():
    scope = unit_scope(real=True)
    proof = lineage_proof(scope, "2026-10-30T12:10:00Z")
    statuses = {p["id"]: p["status"] for p in proof["propositions"]}
    assert (
        len(proof["fold_view_receipts"]) == 77
        and statuses["P4"] == statuses["P7"] == "仅校验器"
    )
    request = registered_request()
    request.update(scope=scope, static_seal=proof["static_seal"])
    report = runtime_check(request)
    assert not report["ok"] and "runtime_B_release" in report["reasons"][0]
    assert report["metrics"]["dsr"] is report["metrics"]["trials_variance"] is None
