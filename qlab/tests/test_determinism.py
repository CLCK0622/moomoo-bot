"""金标准复现 / 模型漂移告警（工部 2026-08-08 第三节）+ seed 名义化口径（第二节）。

重点全在 fail-open 的那一侧：护栏能不能被绕过、能不能在什么都没测到时显示通过。
"""
from __future__ import annotations

import json

import pytest

from qlab.llm_paper import determinism as D
from qlab.llm_paper.reporting import quantile_caliber, seed_semantics

OUT = '{"confidence":0.35,"risk":"margin","stance":"flat","top_driver":"margin"}'


@pytest.fixture()
def iso(tmp_path, monkeypatch):
    """隔离基线：单测**绝不**碰真基线（真基线写一次即冻结，被假输出建立起来就废了）。"""
    p = tmp_path / "baseline.json"
    monkeypatch.setenv(D.BASELINE_ENV, str(p))
    return p


# ---- 探针指纹：改一个字符即变（否则「探针被换过」抓不到） ----

def test_probe_fingerprint_changes_with_content():
    p = D.load_probe()
    fp = D.probe_fingerprint(p)
    p2 = json.loads(json.dumps(p))
    p2["prompt_template"] += " "                     # 改一个空格
    assert D.probe_fingerprint(p2) != fp
    assert D.probe_fingerprint(json.loads(json.dumps(p))) == fp   # 同内容不同排版 → 同指纹


def test_probe_request_carries_prompt_and_fingerprint():
    r = D.probe_request()
    assert r["probe_id"] == "gold_probe_v1" and r["prompt"] and r["fingerprint"].startswith("sha256:")
    assert r["params"]["temperature"] == 0.0


# ---- 首轮：建立基线，但**不得**报成通过 ----

def test_first_round_establishes_baseline_and_is_not_ok(iso):
    r = D.verify_or_establish(output=OUT, model="claude-opus-5")
    assert r["status"] == D.STATUS_BASELINE_ESTABLISHED
    assert r["verified"] is False and r["drift"] is False   # 什么都没验证到 ≠ 通过
    assert iso.exists()


def test_identical_rerun_is_determinism_ok(iso):
    D.verify_or_establish(output=OUT, model="claude-opus-5")
    r = D.verify_or_establish(output=OUT, model="claude-opus-5")
    assert r["status"] == D.STATUS_OK and r["verified"] and not r["drift"]


# ---- 漂移：必须报警，且**绝不**回写基线 ----

def test_changed_output_flags_drift_and_never_rewrites_baseline(iso):
    D.verify_or_establish(output=OUT, model="claude-opus-5")
    before = iso.read_text(encoding="utf-8")
    r = D.verify_or_establish(output=OUT.replace("0.35", "0.55"), model="claude-opus-5")
    assert r["status"] == D.STATUS_DRIFT and r["drift"] and "output_differs" in r["reasons"]
    assert iso.read_text(encoding="utf-8") == before     # 基线一字未动（否则漂移自动被接受）
    # 漂移后再跑原输出仍应判 ok —— 证明基线确实还是原来那份
    assert D.verify_or_establish(output=OUT, model="claude-opus-5")["status"] == D.STATUS_OK


def test_drift_diff_preview_points_at_divergence(iso):
    D.verify_or_establish(output=OUT, model="claude-opus-5")
    r = D.verify_or_establish(output=OUT.replace("flat", "long"), model="claude-opus-5")
    d = r["diff_preview"]
    assert d["first_divergence_index"] == OUT.index("flat")


def test_model_id_change_is_drift_even_if_output_matches(iso):
    """换了模型标识但输出恰好一样 —— 实验对象仍然变了，不能算通过。"""
    D.verify_or_establish(output=OUT, model="claude-opus-5")
    r = D.verify_or_establish(output=OUT, model="claude-opus-5.1")
    assert r["status"] == D.STATUS_DRIFT and "model_id_changed" in r["reasons"]
    assert "output_differs" not in r["reasons"]          # 两种原因不混为一谈


def test_raise_on_drift_option(iso):
    D.verify_or_establish(output=OUT, model="m")
    with pytest.raises(D.DriftAlarm):
        D.verify_or_establish(output=OUT + "x", model="m", raise_on_drift=True)


# ---- 假阴性那一侧：探针被换过时「相同」毫无意义 → fail-closed ----

def test_probe_input_changed_fails_closed(iso, monkeypatch):
    D.verify_or_establish(output=OUT, model="m")
    probe2 = json.loads(json.dumps(D.load_probe()))
    probe2["prompt_template"] = "完全不同的 prompt"
    with pytest.raises(D.ProbeUnverifiable, match="fail-closed|指纹"):
        D.verify_or_establish(output=OUT, model="m", probe=probe2)
    # 纯比对接口同样必须标出来，而不是悄悄判 ok
    assert D.check(output=OUT, model="m", probe=probe2)["status"] == D.STATUS_PROBE_CHANGED


def test_empty_output_is_not_a_pass(iso):
    for bad in ("", "   ", None):
        with pytest.raises(D.ProbeUnverifiable):
            D.verify_or_establish(output=bad, model="m")


def test_baseline_is_write_once(iso):
    D.record_baseline(output=OUT, model="m")
    with pytest.raises(D.BaselineImmutable):
        D.record_baseline(output="别的输出", model="m")


def test_missing_probe_file_fails_closed(tmp_path):
    with pytest.raises(D.ProbeUnverifiable):
        D.load_probe(str(tmp_path / "nope.json"))


# ---- 第二节：seed 名义化口径 ----

def test_lower_quartile_equals_worse_variant_on_frozen_grid():
    """工部第二节的数学论证，用**真** seed_distribution 现算成证据。"""
    c = quantile_caliber()
    assert c["lower_quartile_equals_worse_variant"] is True
    assert c["measured_judged"] == c["measured_min"]
    # 边界：等式要求较差变体占 >= 4/10；本轨 5/5 结构性满足
    assert c["min_worse_count_for_equality"] == 4 and c["worse_count_is"] == 5
    assert c["boundary_scan"]["worse_count_3"]["equals_worse"] is False


def test_seed_semantics_says_nominal_and_forbids_robustness_claim():
    s = seed_semantics(D.STATUS_OK)
    assert s["seed_status"] == "nominal" and s["effective_distinct_outputs"] == 2
    assert s["dsr_n_used"] == 10                       # 仍按冻结网格计，haircut 偏严
    assert any("seed 稳健性通过" in m for m in s["must_not_claim"])


def test_seed_semantics_flips_when_drift_detected():
    """漂移一旦发生，seed 就从名义变成实际 —— 由数据说，不由我们猜。"""
    s = seed_semantics(D.STATUS_DRIFT)
    assert s["seed_status"] == "nominal_assumption_broken"
    assert s["effective_distinct_outputs"] is None and "重新起算" in s["drift_consequence"]


def test_seed_semantics_unverified_is_not_verified():
    s = seed_semantics(D.STATUS_BASELINE_ESTABLISHED)
    assert s["seed_status"] == "nominal" and "假设" in s["drift_consequence"]
