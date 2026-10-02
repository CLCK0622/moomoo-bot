"""EVO-8 方向(b) — multi-factor LONG-BIAS 首轮回测 CLI，接 research/gate.certify()。

管线：build_qlib_data → factor_export(我的因子集，登记诚实 N 到**共享**账本) → multifactor
adapter → certify()。落实工部 2026-07-29 四条硬前提：
  1. 全候选**共用一个账本** research/gate/state/trial_ledger.json；开跑前补登历史轮次
     (GEM 2 + 残差动量 4 + EVO-162 family + ~7 条人肉死因)，让 cumulative_n() 真累计。
  2. 账本被 gitignore → 把最终 N 与各轮登记明细**写进 report.json**（供都察院复核 N 来源）。
  3. adv_notional / required_notional **如实填**（不留默认 0 跳过容量门）。
  4. cost_per_turnover 与预注册冻结口径一致(含 x1/x2)；ledger= 传入且 n_trials_cumulative=None；kernels=1。
"""
from __future__ import annotations

import sys
import json
import argparse
import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from research.gate import (certify, Candidate, TrialLedger, OOSBudget,   # noqa: E402
                           freeze_config, GateThresholds, project_ledger, DEFAULT_LEDGER_PATH)
from qlab.swing.momentum_signals import load_daily                        # noqa: E402
from qlab.swing.multifactor_signals import MultiFactorParams, multifactor_curve, FACTOR_DIRECTION  # noqa: E402

# 全候选唯一共享账本 = 项目规范路径（repo 根的 committed trial_ledger.jsonl，cumulative 14 起）
SHARED_LEDGER = str(_REPO_ROOT / DEFAULT_LEDGER_PATH)

# 我的多因子长偏因子集（Qlib 表达式）——预注册冻结，方向见 FACTOR_DIRECTION
MULTIFACTOR_FACTORS = {
    "mom12_1": "Ref($close,21)/Ref($close,252)-1",
    "mom6_1":  "Ref($close,21)/Ref($close,126)-1",
    "prox52w": "$close/Max($close,252)",
    "trend200": "$close/Mean($close,200)-1",
    "rev21":   "$close/Ref($close,21)-1",
    "vol60":   "Std($close/Ref($close,1)-1,60)",
    "vol120":  "Std($close/Ref($close,1)-1,120)",
    "ltrev":   "Ref($close,252)/Ref($close,756)-1",
}


def _json_default(o):
    if isinstance(o, np.bool_): return bool(o)
    if isinstance(o, np.integer): return int(o)
    if isinstance(o, np.floating): return float(o)
    if isinstance(o, np.ndarray): return o.tolist()
    return str(o)


def seed_shared_ledger(ledger: TrialLedger) -> list:
    """把历史轮次的诚实 N 补登进共享账本（幂等：按 run_id 去重）。返回登记明细。"""
    existing = {r.run_id for r in ledger.runs}
    # EVO-162 residual reversal family size（动态取）
    try:
        from qlab.swing.residual_evaluate import FAMILY as RR_FAMILY
        rr_n = len(RR_FAMILY)
    except Exception:
        rr_n = 6
    seeds = [
        ("hist/GEM-dual-momentum", "manual", 2,
         "GEM 首轮 family {6m,12m}; 结论 NEGATIVE(7.98%/32.05%)"),
        ("hist/residual-reversal-EVO162", "manual", rr_n,
         f"EVO-162 残差反转 family({rr_n} cells); 结论 NEGATIVE"),
        ("hist/residual-momentum", "manual", 4,
         "残差动量 family (F,cut) grid; 结论 REJECTED_cost"),
        ("hist/human-screened-directions", "manual", 7,
         "翰林院人肉筛除的方向(死因): VRP/0DTE/CEF折价/跨场套利 等 ~7 条候选，均负向归档"),
    ]
    detail = []
    for run_id, src, n, note in seeds:
        if run_id in existing:
            detail.append({"run_id": run_id, "n_trials_total": n, "status": "already_present"})
            continue
        ledger.register_run(run_id=run_id, source=src, n_trials_total=n, n_evaluated=n, note=note)
        detail.append({"run_id": run_id, "n_trials_total": n, "status": "registered", "note": note})
    return detail


def _adv_notional(ddir: Path, universe: list, n_long: int, aum: float) -> tuple:
    """如实容量：per-name 部署额 vs 持仓名保守 ADV。从原始 parquet 读 volume
    （load_daily 会丢弃 volume 列，故此处直接读盘）。返回 (required_notional, adv_notional, meta)。"""
    advs = []
    for s in universe:
        p = ddir / f"{s}_1d.parquet"
        if not p.exists():
            continue
        df = pd.read_parquet(p)
        if "volume" not in df.columns or "close" not in df.columns or not len(df):
            continue
        tail = df.tail(252)
        dv = (pd.to_numeric(tail["close"], errors="coerce") *
              pd.to_numeric(tail["volume"], errors="coerce")).dropna()
        if len(dv):
            advs.append(float(dv.mean()))
    advs = np.array(sorted(advs))
    per_name = aum / max(1, n_long)                       # 单名部署额
    adv_floor = float(np.quantile(advs, 0.20)) if len(advs) else 0.0   # 20 分位保守 ADV
    return per_name, adv_floor, {"aum": aum, "n_long_typ": n_long,
                                 "adv_p20_usd": adv_floor, "adv_median_usd": float(np.median(advs)) if len(advs) else 0.0,
                                 "n_names_with_adv": int(len(advs))}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="EVO-8(b) multi-factor long-bias via certify()")
    ap.add_argument("--data-dir", default="data/daily_full")
    ap.add_argument("--universe-file", default="RESIDUAL_UNIVERSE_RESOLVED.txt")
    ap.add_argument("--store", default="data/qlib_store")
    ap.add_argument("--factors-out", default="qlab/reports/multifactor/qlib_factors")
    ap.add_argument("--out", default="qlab/reports/multifactor")
    ap.add_argument("--start", default="2006-01-01")
    ap.add_argument("--end", default="2024-12-31")
    ap.add_argument("--aum", type=float, default=10_000_000.0)
    ap.add_argument("--prereg-commit", default="PENDING")
    ap.add_argument("--ledger", default=SHARED_LEDGER,
                    help="共享台账路径（默认项目规范 jsonl）；仅验证/复核时指向 scratch 副本")
    args = ap.parse_args(argv)

    ddir = Path(args.data_dir)
    universe = [l.strip() for l in Path(args.universe_file).read_text(encoding="utf-8").splitlines()
                if l.strip() and not l.startswith("#")]
    universe = [s for s in universe if (ddir / f"{s}_1d.parquet").exists()]
    stock_frames = {s: load_daily(ddir / f"{s}_1d.parquet") for s in universe}
    spy_frame = load_daily(ddir / "SPY_1d.parquet")

    # 1) build qlib store
    from tools.qlib_gen import build_qlib_data, factor_export
    build_qlib_data.build(ddir, Path(args.store))
    store_bin = Path(args.store) / "bin"

    # 2) factor_export（注入我的因子集）→ 登记诚实 N 到共享账本
    ledger = project_ledger(args.ledger)              # 项目规范共享台账（committed jsonl；工部已合一 N=29）
    # 不再自行补登历史：canonical ledger 已有权威计数（pre_gate_manual_history 9 含残差反转/跨场套利等
    # 9 个证伪方向 + gem_firstround 1 + residmom_evo162_r1 4 = 14）。本轮只由 factor_export 登记 multifactor。
    seed_detail = ("canonical project_ledger 已含权威历史 N=14（9 人肉证伪 + GEM 1 + 残差动量 4）；"
                   "本轮不重复补登，仅登记 multifactor 因子轮次")
    factor_export.FACTOR_SETS["multifactor_longbias"] = dict(MULTIFACTOR_FACTORS)
    man = factor_export.export(store_bin, Path(args.factors_out), start=args.start, end=args.end,
                               factor_set="multifactor_longbias", ledger=ledger,
                               run_id=f"multifactor-longbias-{args.prereg_commit}", source="qlib",
                               repo_root=_REPO_ROOT)
    factors_df = pd.read_parquet(Path(args.factors_out) / "factors.parquet")
    n_cumulative = ledger.cumulative_n()

    # 3) multifactor 曲线：x2 决策口径 + gross(cost_mult=0) + turnover
    params = MultiFactorParams()
    net = multifactor_curve(factors_df, stock_frames, spy_frame, universe, params,
                            cost_mult=2.0, start=args.start, end=args.end)
    gross = multifactor_curve(factors_df, stock_frames, spy_frame, universe, params,
                              cost_mult=0.0, start=args.start, end=args.end)
    edf = net["equity_df"]
    diag = net["diagnostics"]
    n_long_typ = max(1, int(round(diag["mean_n_long_when_on"])))

    # 每因子单独跑一遍拿标准化 Sharpe（DSR 的 V：机器批量挖因子必须吐全量试验 SR）
    trial_sharpes = []
    per_factor_sr = {}
    for f in MULTIFACTOR_FACTORS:
        try:
            c = multifactor_curve(factors_df, stock_frames, spy_frame, universe, params,
                                  cost_mult=2.0, start=args.start, end=args.end, factors_subset=[f])
            r = c["equity_df"]["ret"].to_numpy(float)
            r = r[np.isfinite(r)]
            # DSR 单位契约（工部 2026-07-29）：trial Sharpe 必须与门用的 sr_per_period 同尺度=**每期**。
            # 之前 ×sqrt(252) 是年化，会把 expected_max 抬高 √252≈15.9 倍 → 系统性误杀真 alpha（假阴性）。
            sr = float(r.mean() / r.std(ddof=1)) if len(r) > 1 and r.std(ddof=1) > 0 else 0.0
        except Exception:
            sr = 0.0
        trial_sharpes.append(sr)
        per_factor_sr[f] = sr

    # 4) 如实容量
    req_notional, adv_notional, cap_meta = _adv_notional(ddir, universe, n_long_typ, args.aum)

    # 5) 预注册冻结 + Candidate + certify
    cfg = {
        "candidate": "multifactor_longbias", "universe": list(universe), "leverage_cap": 1.0,
        "signal_params": {"factors": MULTIFACTOR_FACTORS, "direction": FACTOR_DIRECTION,
                          "compose": "equal-weight z-score of directional factors",
                          "cut": params.cut, "trend_overlay": f"SPY {params.trend_ma_days}dMA gate",
                          "risk_off_exposure": params.risk_off_exposure},
        "rebalance": "monthly",
        # 用注册表登记的标签；门 resolve_cost_per_turnover=max(floor 5bps, 自报 0.001)=10bps（工部裁定口径）
        "cost_model": "moomoo_retail_x1",
        "train_test_split": "NO-FIT waiver: factors + equal-weight composite are literature "
                            "conventions frozen pre-results; full-sample net curve IS OOS; single OOS eval",
        "gate_thresholds": "official_50_20 + shadow_report_25_20 + shadow_floor_15_20",
    }
    fhash = freeze_config(cfg)
    rationale = (
        "多因子长偏：把文献稳健的横截面预测因子（12-1/6-1 动量、52 周高邻近、200d 趋势、"
        "短期反转、低波异象、长期反转/价值代理）等权 z-score 合成，做多复合分 top 分位（long-tilt、"
        "无做空无杠杆），叠加组合级 200d 绝对动量趋势闸控回撤。预先假设：多因子分散 + 右侧趋势闸在"
        "成本后仍有正的、优于静态多头基准的风险调整收益。")
    cand = Candidate(
        name="multifactor_longbias_decile_trend200",
        oos_net_returns=edf["ret"].to_numpy(float).tolist(),
        oos_dates=[str(d.date()) for d in pd.DatetimeIndex(edf["date"])],
        gross_returns=gross["equity_df"]["ret"].to_numpy(float).tolist(),
        turnover=gross["equity_df"]["traded_notional"].to_numpy(float).tolist(),
        cost_per_turnover=0.001,                      # 与预注册 10bps/side 冻结口径一致
        required_notional=req_notional, adv_notional=adv_notional,   # 如实(工部规矩#3)
        prereg_config=cfg, frozen_hash=fhash, economic_rationale=rationale,
        n_trials_cumulative=None,                     # 门自去共享台账取 N（工部规矩#4）
        trial_sharpes=trial_sharpes,                  # 每因子标准化 Sharpe → DSR 的 V（全量吐 SR）
    )
    assert cand.n_trials_cumulative is None and adv_notional > 0, "ADV 必须如实、N 不自报"
    verdict = certify(cand, ledger=ledger, thresholds=GateThresholds(), oos_budget=OOSBudget(max_evals=1))

    met = verdict.metrics or {}
    shadow_floor = bool(met.get("shadow_floor_pass", False))
    dec = verdict.decision
    if dec == "REPORT_5020":
        action = "REPORT_5020 → 直接清官方 50/20；但按工部规矩先回工部、不自行上报 Kevin"
    elif dec == "DECISION_POINT":
        action = "DECISION_POINT → 过影子上报门未过官方门；带真实数字先回工部（户部收口成本/容量门前不自行上报 Kevin）"
    elif dec == "FAIL":
        action = ("FAIL 但 shadow_floor_pass=True → 记兜底带 sleeve 候选留档" if shadow_floor
                  else "FAIL 且未过兜底带 → NEGATIVE 随轮回流")
    else:
        action = f"{dec}（硬门拒绝）→ 按门原因整改/回报"

    report = {
        "issue": "EVO-8", "sleeve": "multifactor_longbias", "candidate": cand.name,
        "preregistration_commit": args.prereg_commit, "frozen_hash": fhash,
        "rebased_on": "agent/evo-162-residual-reversal @ 27cecc4 (merged gate+generator, N/V fail-open fixed)",
        "honest_trial_count": {
            "shared_ledger": SHARED_LEDGER, "cumulative_n": n_cumulative,
            "this_run_factor_expressions": man.get("n_expressions_attempted"),
            "factor_manifest_run_id": man.get("ledger_run_id"),
            "ledger_registrations": [{"run_id": r.run_id, "source": r.source,
                                      "n_trials_total": r.n_trials_total, "note": r.note}
                                     for r in ledger.runs],
            "seed_detail": seed_detail,
            "per_factor_sharpe_x2": per_factor_sr,
            "note": "N 取自共享 TrialLedger.cumulative_n()；账本 gitignore，故全量登记明细+每因子试验 SR "
                    "写此供都察院复核（DSR 的 V 来自这批 SR）。",
        },
        "capacity_honest": {"required_notional": req_notional, "adv_notional": adv_notional, **cap_meta},
        "cost_model": "10bps/side ×2 决策口径，cost_per_turnover=0.001（与冻结一致）",
        "certify_verdict": {"certified": verdict.certified, "decision": dec,
                            "reasons": verdict.reasons, "gates": verdict.gates},
        "metrics": met, "shadow_floor_pass": shadow_floor, "action": action,
        "diagnostics": diag, "factor_manifest": man,
        "run_date": dt.date.today().isoformat(),
    }
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2,
                                                default=_json_default), encoding="utf-8")
    print(verdict.summary())
    if met.get("cagr") is not None:
        print(f"CAGR={met['cagr']:.2%} MDD={met['mdd']:.2%} sharpe_ann={met.get('sharpe_ann',0):.2f} "
              f"shadow_floor_pass={shadow_floor}")
        print("crisis:", {k: (round(v.get('mdd'), 3) if isinstance(v.get('mdd'), (int, float))
                              and v.get('mdd') == v.get('mdd') else 'tail_incomplete')
                          for k, v in met.get("crisis", {}).items()})
    else:
        print("rejected before metrics; gates:", list((verdict.gates or {}).keys()))
    print(f"cumulative_N={n_cumulative} (factor expr this run={man.get('n_expressions_attempted')})")
    print("ACTION:", action, "\nreport →", out / "report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
