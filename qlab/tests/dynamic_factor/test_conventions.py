from dataclasses import replace
import pytest
from qlab.dynamic_factor.conventions import (
    ConventionConflict,
    load_conventions,
    arithmetic,
    FIXTURES,
)
from qlab.dynamic_factor.contract import sha256
from qlab.dynamic_factor.harness_helpers import fixture_ledger
from qlab.dynamic_factor.ledger import AttemptLedger
from qlab.dynamic_factor.dsr_v0 import formula, daily_sr
from qlab.dynamic_factor.statistics import dsr_eval, prereg_check


def test_exact_v1_identity_profile_and_incomplete_seed(tmp_path):
    p = load_conventions()
    assert (
        p.raw_sha256
        == "1767b7cf844721468f506e984c303c49e8ff58c395515404187d403661abe97b"
    )
    assert (
        p.binding["prereg_sha256"]
        == "3139ab15b8cb53b3c7cdc81816ce9fa4a6ad1862fb836dcde88f1cc31235447f"
    )
    assert (
        p.binding["common_profile_sha256"]
        == "4292eb477baffafaeff24441ab36936580608f70d2c8672d94d596fc772686b3"
    )
    ledger = fixture_ledger(tmp_path / "l.sqlite", p)
    a = ledger.snapshot()
    assert (
        len(p.seed_rows) == 8
        and a["cumulative_n_lower_bound"] == 47
        and a["cumulative_n"] is None
    )
    assert (
        a["genesis"]["count_complete"] is False
        and len(a["genesis"]["historical_seed_rows"]) == 8
    )
    ledger.begin("nan", {})
    ledger.finish("nan", "nan", sharpe=float("nan"))
    assert fixture_ledger(ledger.path, p).snapshot()["cumulative_n_lower_bound"] == 48
    report = dsr_eval({}, ledger, conventions=p)
    assert (
        report["metrics"]["dsr"] is None
        and report["metrics"]["trials_variance"] is None
    )
    assert not report["runtime_consumable"] and not report["certifiable"]
    assert not prereg_check(p.document, p.raw_sha256, conventions=p)["certifiable"]


def test_bound_bootstrap_cannot_be_silently_created(tmp_path):
    with pytest.raises(ValueError, match="project_path_migration_receipt_required"):
        AttemptLedger.from_conventions(tmp_path / "fresh.sqlite", load_conventions())
    assert not (tmp_path / "fresh.sqlite").exists()


def test_raw_policy_and_seed_are_immutable_and_authoritative(tmp_path):
    p = load_conventions()
    copy = p.document
    copy["DSR"]["gamma"] = 0
    assert p.document["DSR"]["gamma"] != 0
    with pytest.raises(ValueError, match="seed_bytes_mismatch"):
        AttemptLedger.from_conventions(
            tmp_path / "forged.sqlite", replace(p, seed_raw=b"")
        )
    path = tmp_path / "forged.json"
    path.write_text("{}")
    with pytest.raises(ConventionConflict):
        load_conventions(path)
    changed = p.raw_document + b"\n"
    path.write_bytes(changed)
    with pytest.raises(ConventionConflict, match="authority_hash"):
        load_conventions(path, expected_sha256=sha256(changed))
    with pytest.raises(ConventionConflict):
        arithmetic("__import__('os').system('true')", {})


def test_formula_is_pure_external_V_arithmetic_only():
    p = load_conventions()
    sr0, dsr = formula(
        p,
        SR=0.2903200204700225,
        n=60,
        N=81,
        V=0.0102,
        skew=0,
        kurt=1.7314285714285709,
        n_complete=False,
    )
    assert sr0 == pytest.approx(0.24799876432939677)
    assert dsr == pytest.approx(0.6265006201845557)
    args = dict(SR=0.1, n=20, N=1, V=0.01, skew=0, kurt=3, n_complete=False)
    with pytest.raises(ValueError, match="n_eq1"):
        formula(p, **args)
    assert formula(p, **dict(args, n_complete=True))[0] == 0
    with pytest.raises(ValueError, match="invalid_sample"):
        formula(p, **dict(args, N=2, V=-1))


def test_daily_scale_converts_once_and_missing_is_not_zero():
    p = load_conventions()
    observation = {
        "sharpe_per_period": 0.01 * p.annual_periods**0.5,
        "details": {"sharpe_scale": "annual"},
    }
    assert daily_sr(observation, p.annual_periods) == pytest.approx(0.01)
    observation["details"]["scale_conversions"] = 1
    with pytest.raises(ValueError, match="repeated_conversion"):
        daily_sr(observation, p.annual_periods)
    with pytest.raises(ValueError, match="sr_missing"):
        daily_sr({"sharpe_per_period": None, "details": {}}, p.annual_periods)


def test_bound_calendar_gap_and_purge_derive_from_v1():
    p = load_conventions()
    m = p.fold_manifest()
    index = {d: i for i, d in enumerate(m["calendar"])}
    assert len(m["folds"]) == p.document["folds"]["fold_count"] == 77
    for f in m["folds"]:
        assert (
            index[f["test_start"]] - index[f["history_end"]] - 1
            == p.document["folds"]["gap_days"]
        )
        assert (
            index[f["history_end"]] - index[f["train_end"]] == m["template_path_offset"]
        )
    assert p.document["benchmark_replacement"] == p.profile["benchmarks"]
    assert "VTI_fixed_B2" in p.document["benchmark_replacement"]["B2_freeze_rule"]


@pytest.mark.parametrize("version", ["v0.1", "v0.2"])
def test_old_profile_is_retained_as_original_bytes_only(version):
    p = load_conventions(FIXTURES / ("conventions-" + version + ".json"))
    assert (
        p.binding["common_profile_sha256"]
        != load_conventions().binding["common_profile_sha256"]
        if p.raw_profile
        else True
    )
