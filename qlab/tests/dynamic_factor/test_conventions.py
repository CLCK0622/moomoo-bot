import json
from copy import deepcopy

import pytest

from qlab.dynamic_factor.contract import sha256
from qlab.dynamic_factor.conventions import (
    ConventionConflict,
    arithmetic,
    load_conventions,
)
from qlab.dynamic_factor.dsr_v0 import formula
from qlab.dynamic_factor.folds import run_walk_forward
from qlab.dynamic_factor.fees import FIXTURES, fee_frontier
from qlab.dynamic_factor.harness import _wf, numerical_fixture
from qlab.dynamic_factor.ledger import AttemptLedger
from qlab.dynamic_factor.statistics import dsr_eval, prereg_check
from qlab.dynamic_factor.validation import wf_manifest_check


def test_exact_policy_seed_identity_and_incomplete_count(tmp_path):
    policy = load_conventions()
    assert (
        policy.raw_sha256
        == "2e65c77849b936d44c864b056be134e030ddf7f27e746072b70fffe631acf69b"
    )
    assert len(policy.seed_rows) == 8
    ledger = AttemptLedger.from_conventions(tmp_path / "ledger.sqlite", policy)
    snapshot = ledger.snapshot()
    assert (
        snapshot["cumulative_n"] is None and snapshot["cumulative_n_lower_bound"] == 47
    )
    assert not snapshot["n_complete"] and not snapshot["certifiable"]
    assert len(snapshot["genesis"]["historical_seed_rows"]) == 8
    assert (
        ledger.readout()["metric_availability"]["trials_variance"]["reason"]
        == "dsr_run_context_required"
    )
    ledger.begin("new", {"factor": "same"})
    ledger.finish("new", "nan", sharpe=float("nan"))
    assert (
        AttemptLedger.from_conventions(ledger.path, policy).snapshot()[
            "cumulative_n_lower_bound"
        ]
        == 48
    )
    assert (
        prereg_check(policy.document, policy.raw_sha256, conventions=policy)[
            "certifiable"
        ]
        is False
    )


def test_policy_objects_do_not_allow_mutating_the_pinned_json():
    policy = load_conventions()
    copy = policy.document
    copy["DSR"]["gamma"] = 10
    assert policy.document["DSR"]["gamma"] != 10


def test_declared_proposals_survive_partial_registration_without_double_counting_invocation(
    tmp_path,
):
    policy = load_conventions()
    ledger = AttemptLedger.from_conventions(tmp_path / "ledger.sqlite", policy)
    ledger.begin(
        "fold/invocation", {}, kind="fold_invocation", context={"run_id": "fold"}
    )
    assert ledger.snapshot()["cumulative_n_lower_bound"] == 48
    members = [f"fold/{i}" for i in range(policy.family_size)]
    ledger.declare_family("fold", members, basis=policy.document["N"]["DSR_SR_basis"])
    ledger.begin(members[0], {}, context={"run_id": "fold"})
    ledger.finish(members[0], "failed")
    snapshot = AttemptLedger.from_conventions(ledger.path, policy).snapshot()
    assert snapshot["local_attempts_n"] == 2
    assert snapshot["local_counted_n"] == 17
    assert (
        snapshot["cumulative_n_lower_bound"] == 64
    )  # no lost proposed members or extra invocation trial


def test_unusable_jump_configuration_does_not_silently_disable_detection():
    manifest = _wf()
    manifest.pop("jump_reversal_policy")
    assert "data.jump_reversal_policy_missing" in wf_manifest_check(manifest)["reasons"]
    manifest["jump_reversal_policy"] = {}
    assert "data.jump_reversal_policy_invalid" in wf_manifest_check(manifest)["reasons"]


@pytest.mark.parametrize(
    "mutate,reason",
    [
        (lambda p: p["DSR"].update(threshold=0), "internal_conflict"),
        (lambda p: p["N"].update(N_seed_min=0), "internal_conflict"),
        (
            lambda p: p["N"].update(supersedes_deletes_prior_attempt=True),
            "internal_conflict",
        ),
        (
            lambda p: p["units"].update(annual_to_daily_V="divide365_exactly_once"),
            "scale_conflict",
        ),
        (
            lambda p: p["labels"].update(primary_horizon_days=9),
            "label_or_minimum_fold_conflict",
        ),
    ],
)
def test_conflicting_json_is_rejected_before_use(tmp_path, mutate, reason):
    p = load_conventions().document
    mutate(p)
    raw = json.dumps(p).encode()
    path = tmp_path / "conventions.json"
    path.write_bytes(raw)
    with pytest.raises(ConventionConflict, match=reason):
        load_conventions(path, expected_sha256=sha256(raw))


def test_unpinned_or_unsafe_expression_rejected(tmp_path):
    path = tmp_path / "changed.json"
    path.write_text("{}")
    with pytest.raises(ConventionConflict, match="hash_mismatch"):
        load_conventions(path)
    with pytest.raises(ConventionConflict):
        arithmetic("__import__('os').system('false')", {})


def test_dsr_numbers_and_annual_conversion_once(tmp_path):
    policy = load_conventions()
    daily = AttemptLedger.from_conventions(tmp_path / "daily.sqlite", policy)
    r = dsr_eval(numerical_fixture(daily, policy), daily, conventions=policy)
    m = r["metrics"]
    assert m["family_variance"] == pytest.approx(0.00255)
    assert m["independent_variance"] == pytest.approx(0.0102)
    assert m["sr0"] == pytest.approx(0.24799876432939677)
    assert m["sharpe"] == pytest.approx(0.2903200204700225)
    assert m["kurt"] == pytest.approx(
        1.7314285714285709
    )  # ordinary population kurtosis
    assert m["dsr"] == pytest.approx(0.6265006201845557)
    assert m["gate_n"] == 81 and m["cumulative_n"] is None
    annual = AttemptLedger.from_conventions(tmp_path / "annual.sqlite", policy)
    a = dsr_eval(
        numerical_fixture(annual, policy, annual=True), annual, conventions=policy
    )
    assert a["metrics"]["trials_variance"] == pytest.approx(m["trials_variance"])
    assert a["metrics"]["dsr"] == pytest.approx(m["dsr"])
    assert r["metric_availability"]["dsr"]["available"] and not r["certifiable"]
    assert "ledger_history_incomplete" in r["reasons"]


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"return_scale": "annual"}, "scale_or_basis_mismatch"),
        ({"self_report_n": None}, "self_report_n_missing_or_invalid"),
        ({"returns": [1]}, "insufficient_or_nonfinite_observations"),
        ({"returns": [0, 0, 0]}, "zero_return_variance"),
        ({"returns": [0, float("nan")]}, "insufficient_or_nonfinite_observations"),
        ({"v": 0}, "scalar_v_forbidden"),
        ({"return_basis": "raw_strategy_SR"}, "scale_or_basis_mismatch"),
    ],
)
def test_numerical_invalids_return_null_with_reason(tmp_path, change, reason):
    policy = load_conventions()
    ledger = AttemptLedger.from_conventions(tmp_path / "ledger.sqlite", policy)
    request = numerical_fixture(ledger, policy)
    r = dsr_eval(dict(request, **change), ledger, conventions=policy)
    assert r["metrics"]["dsr"] is None and not r["certifiable"]
    assert any(reason in x for x in r["reasons"])


def test_missing_SR_retained_and_historical_raw_SR_never_used_as_V(tmp_path):
    policy = load_conventions()
    ledger = AttemptLedger.from_conventions(tmp_path / "missing.sqlite", policy)
    req = numerical_fixture(ledger, policy, missing=True)
    r = dsr_eval(req, ledger, conventions=policy)
    assert r["metrics"]["dsr"] is None
    assert "dsr.family_or_independent_sr_missing" in r["reasons"]
    assert ledger.snapshot()["local_attempts_n"] == 34
    historical = AttemptLedger.from_conventions(tmp_path / "history.sqlite", policy)
    request = numerical_fixture(historical, policy, include_independent=False)
    r = dsr_eval(request, historical, conventions=policy)
    assert r["metrics"]["independent_variance"] is None
    assert "dsr.independent_variance_unavailable" in r["reasons"]


def test_second_annual_conversion_is_refused(tmp_path):
    policy = load_conventions()
    ledger = AttemptLedger.from_conventions(tmp_path / "ledger.sqlite", policy)
    req = numerical_fixture(ledger, policy, annual=True, conversions=1)
    r = dsr_eval(req, ledger, conventions=policy)
    assert r["metrics"]["dsr"] is None
    assert "dsr.scale_mismatch_or_repeated_conversion" in r["reasons"]


def test_high_diagnostic_does_not_certify_incomplete_N(tmp_path):
    policy = load_conventions()
    ledger = AttemptLedger.from_conventions(tmp_path / "ledger.sqlite", policy)
    req = numerical_fixture(ledger, policy)
    req["returns"] = [x + 0.1 for x in req["returns"]]
    r = dsr_eval(req, ledger, conventions=policy)
    assert r["metrics"]["diagnostic_passed"]
    assert not r["metrics"]["passed"] and not r["certifiable"]


def test_membership_sealed_before_performance_and_extra_trials_cannot_be_hidden(
    tmp_path,
):
    policy = load_conventions()
    ledger = AttemptLedger.from_conventions(tmp_path / "ledger.sqlite", policy)
    req = numerical_fixture(ledger, policy)
    ledger.begin("extra", {"expr": "loser"}, context={"run_id": "own"})
    ledger.finish("extra", "failed", reason="fixture failure")
    r = dsr_eval(req, ledger, conventions=policy)
    assert "dsr.family_extra_or_unregistered_attempt" in r["reasons"]
    assert r["metrics"]["cumulative_n_lower_bound"] == 82
    with pytest.raises(ValueError, match="membership_conflict"):
        ledger.declare_family(
            "own", ["winner"], basis=policy.document["N"]["DSR_SR_basis"]
        )
    ledger.begin("late", {}, context={"run_id": "late-run"})
    with pytest.raises(ValueError, match="declared_after_attempts"):
        ledger.declare_family(
            "late-run", ["late"], basis=policy.document["N"]["DSR_SR_basis"]
        )


def test_cli_reads_v0_and_preserves_lower_bound_N(tmp_path):
    import subprocess
    import sys

    policy = load_conventions()
    ledger = AttemptLedger.from_conventions(tmp_path / "ledger.sqlite", policy)
    request = numerical_fixture(ledger, policy)
    source = tmp_path / "request.json"
    source.write_text(json.dumps({"metrics": request}))
    cli = subprocess.run(
        [
            sys.executable,
            "-m",
            "qlab.dynamic_factor",
            "dsr_eval",
            "--input",
            str(source),
            "--ledger",
            str(ledger.path),
            "--conventions",
            str(FIXTURES / "conventions-v0.1.json"),
            "--conventions-sha256",
            policy.raw_sha256,
        ],
        capture_output=True,
        text=True,
    )
    assert cli.returncode == 2
    r = json.loads(cli.stdout)
    assert r["conventions_sha256"] == policy.raw_sha256
    assert r["metrics"]["cumulative_n"] is None
    assert r["metrics"]["dsr"] == pytest.approx(0.6265006201845557)


def test_v0_per_order_cost_floor_and_param_binding(tmp_path):
    policy = load_conventions()
    request = dict(
        price=1375,
        ticket_usd=1375,
        gross_edge_bps=10,
        sell_date="2027-01-01",
        rate_basis="effective_date",
        pnl_basis="reference",
    )
    old = fee_frontier(request, FIXTURES / "fee_params_x1.json")
    bound = fee_frontier(request, FIXTURES / "fee_params_x1.json", conventions=policy)
    assert bound["metrics"]["gate_cost_bps"] > old["metrics"]["gate_cost_bps"]
    assert bound["conventions_sha256"] == policy.raw_sha256
    altered = tmp_path / "params.json"
    altered.write_text((FIXTURES / "fee_params_x1.json").read_text() + "\n")
    assert fee_frontier(request, altered, conventions=policy)["reasons"] == [
        "fee_params_not_bound_to_conventions"
    ]


def test_self_report_never_decreases_across_restart(tmp_path):
    policy = load_conventions()
    ledger = AttemptLedger.from_conventions(tmp_path / "ledger.sqlite", policy)
    req = numerical_fixture(ledger, policy)
    a = dsr_eval(dict(req, self_report_n=500), ledger, conventions=policy)
    ledger = AttemptLedger.from_conventions(ledger.path, policy)
    b = dsr_eval(req, ledger, conventions=policy)
    assert a["metrics"]["gate_n"] == b["metrics"]["gate_n"] == 500
    assert a["metrics"]["dsr"] == b["metrics"]["dsr"]


def test_formula_invalid_N1_and_negative_V():
    policy = load_conventions()
    args = dict(SR=0.1, n=20, N=1, V=0.01, skew=0, kurt=3, n_complete=False)
    with pytest.raises(ValueError, match="n_eq1_requires_complete_audit"):
        formula(policy, **args)
    assert formula(policy, **dict(args, n_complete=True))[0] == 0
    with pytest.raises(ValueError, match="invalid_sample_or_variance"):
        formula(policy, **dict(args, N=2, V=-1))


def test_fold_gap_and_label_template_purge_come_from_policy(tmp_path):
    policy = load_conventions()
    manifest = policy.fold_manifest()
    idx = {d: i for i, d in enumerate(manifest["calendar"])}
    assert len(manifest["folds"]) == policy.document["folds"]["fold_count"] == 77
    for fold in manifest["folds"]:
        assert (
            idx[fold["test_start"]] - idx[fold["history_end"]] - 1
            == policy.document["folds"]["gap_days"]
        )
        assert (
            idx[fold["history_end"]] - idx[fold["train_end"]]
            == manifest["template_path_offset"]
        )
    bad = deepcopy(manifest)
    bad["embargo"] = 0
    called = []
    r = run_walk_forward(
        bad,
        [],
        miner_factory=lambda ctx: called.append(ctx),
        fitter_factory=lambda ctx: called.append(ctx),
        ledger=AttemptLedger.from_conventions(tmp_path / "ledger.sqlite", policy),
        run_id="bad",
        conventions=policy,
    )
    assert "wf.conventions_manifest_mismatch" in r["reasons"] and not called


def test_bound_fold_only_exposes_labels_and_paths_mature_in_original_train(tmp_path):
    policy = load_conventions()
    manifest = policy.fold_manifest()
    calendar = manifest["calendar"]
    fold = manifest["folds"][0]
    seen = []
    rows = [
        dict(
            date=d,
            features={"x": i},
            target=1,
            label_entry=calendar[
                min(i + manifest["label_entry_offset"], len(calendar) - 1)
            ],
            label_end=calendar[min(i + manifest["label_horizon"], len(calendar) - 1)],
            template_end=calendar[
                min(i + manifest["template_path_offset"], len(calendar) - 1)
            ],
        )
        for i, d in enumerate(calendar)
    ]

    class Mine:
        def mine(self, train):
            assert (
                len(train)
                == policy.document["folds"]["train_days"]
                - manifest["template_path_offset"]
            )
            assert train[-1].date == fold["train_end"]
            assert train[-1].template_end == fold["history_end"]
            assert all(
                r.label_end <= fold["history_end"]
                and r.template_end <= fold["history_end"]
                for r in train
            )
            seen.append("train_verified")
            return [{"recipe": i} for i in range(policy.family_size - 1)]

    class Fit:
        def fit(self, train, proposals):
            # Stop this toy adapter here: no historical strategy or predictions.
            raise ValueError("fixture_stop_after_train_verification")

    ledger = AttemptLedger.from_conventions(tmp_path / "ledger.sqlite", policy)
    r = run_walk_forward(
        manifest,
        rows,
        miner_factory=lambda ctx: Mine(),
        fitter_factory=lambda ctx: Fit(),
        ledger=ledger,
        run_id="fixture",
        conventions=policy,
    )
    assert seen == ["train_verified"]
    assert "fixture_stop_after_train_verification" in r["reasons"]
    assert ledger.snapshot()["local_counted_n"] == 17
    assert ledger.snapshot()["local_attempts_n"] == 18


def test_trading_day_jump_independent_of_calendar_and_parameter_driven():
    manifest = _wf()
    for i, row in enumerate(manifest["series"]["SPY"]):
        row["close"] = [100, 100, 80, 100, 100][i]
    before = deepcopy(manifest)
    r = wf_manifest_check(manifest)
    assert "data.jump_reversal" in r["reasons"]
    assert "data.nontrading_bar" not in r["reasons"]
    assert manifest == before
    manifest["jump_reversal_policy"]["min_abs_jump"] = 0.3
    assert "data.jump_reversal" not in wf_manifest_check(manifest)["reasons"]


def test_v0_calendar_cannot_be_replaced_by_intersection():
    policy = load_conventions()
    manifest = policy.fold_manifest()
    manifest.update(
        portfolio="portfolio",
        benchmarks=["QQQ", "SPY", "VTI"],
        series={
            k: [{"date": d, "close": 100} for d in manifest["calendar"]]
            for k in ("portfolio", "QQQ", "SPY", "VTI")
        },
        jump_reversal_policy=_wf()["jump_reversal_policy"],
    )
    r = wf_manifest_check(manifest, conventions=policy)
    assert r["ok"] and not r["certifiable"]
    manifest["calendar"].pop(50)
    for rows in manifest["series"].values():
        rows.pop(50)
    r = wf_manifest_check(manifest, conventions=policy)
    assert "wf.conventions_manifest_mismatch" in r["reasons"]
