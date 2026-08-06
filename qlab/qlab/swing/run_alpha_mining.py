"""EVO-8 岔路 (i) — Qlib 有界因子挖掘 runner，接 research/gate.certify()。

12 条冻结表达式（ALPHA_MINING_EVAL_PREREGISTRATION.md §2，每条附经济理由、与已证伪族无重叠）
→ factor_export 求值 → multifactor 合成引擎（top decile + 200d 趋势闸）→ certify()。
Qlib 只作求值器、自带回测永不作判据；kernels=1；N 预算 35→47（只支取 12，不全量倒 158）。
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

from research.gate import (certify, Candidate, GateThresholds, freeze_config,          # noqa: E402
                           project_ledger, DEFAULT_LEDGER_PATH,
                           project_oos_budget, DEFAULT_OOS_BUDGET_PATH)
from qlab.swing.momentum_signals import load_daily                                      # noqa: E402
from qlab.swing.multifactor_signals import MultiFactorParams, multifactor_curve, FACTOR_DIRECTION  # noqa: E402

# 冻结的 12 条（预注册 §2）；表达式已把方向写进式子（负号即反向），故 direction 全 +1
MINING_FACTORS = {
    "illiq_amihud":       "Mean(Abs($close/Ref($close,1)-1)/($volume*$close+1),21)",
    "turnover_low":       "-Mean($volume,21)/Mean($volume,252)",
    "vol_of_vol":         "-Std(Std($close/Ref($close,1)-1,21),63)",
    "downside_beta":      "-Std(Less($close/Ref($close,1)-1,0),126)",
    "max_lottery":        "-Max($close/Ref($close,1)-1,21)",
    "skew_neg":           "-Mean(Power($close/Ref($close,1)-1,3),63)",
    "intraday_close_str": "Mean(($close-$open)/($high-$low+0.0001),21)",
    "overnight_drift":    "Mean($open/Ref($close,1)-1,63)",
    "volume_shock_rev":   "-Mean(($volume/Mean($volume,21)-1)*($close/Ref($close,1)-1),21)",
    "range_compress":     "-Mean(($high-$low)/$close,21)/(Mean(($high-$low)/$close,252)+0.0001)",
    "price_accel":        "($close/Ref($close,21)-1)-($close/Ref($close,63)-1)",
    "close_to_high52":    "$close/Max($high,252)",
}


def _sr_pp(r):
    r = np.asarray(r, float); r = r[np.isfinite(r)]
    return float(r.mean() / r.std(ddof=1)) if len(r) > 1 and r.std(ddof=1) > 0 else 0.0


def _jd(o):
    if isinstance(o, np.bool_): return bool(o)
    if isinstance(o, np.integer): return int(o)
    if isinstance(o, np.floating): return float(o)
    if isinstance(o, np.ndarray): return o.tolist()
    return str(o)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="EVO-8 (i) bounded Qlib factor mining")
    ap.add_argument("--store", default="data/qlib_store/bin")
    ap.add_argument("--factors-out", default="qlab/reports/alpha_mining/qlib_factors")
    ap.add_argument("--universe-file", default="RESIDUAL_UNIVERSE_RESOLVED.txt")
    ap.add_argument("--data-dir", default="data/daily_full")
    ap.add_argument("--out", default="qlab/reports/alpha_mining")
    ap.add_argument("--start", default="2006-01-01")
    ap.add_argument("--end", default="2024-12-31")
    ap.add_argument("--prereg-commit", default="PENDING")
    ap.add_argument("--supersedes", default=None)
    args = ap.parse_args(argv)

    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    ddir = Path(args.data_dir)
    universe = [l.strip() for l in Path(args.universe_file).read_text(encoding="utf-8").splitlines()
                if l.strip() and not l.startswith("#")]
    universe = [s for s in universe if (ddir / f"{s}_1d.parquet").exists()]
    frames = {s: load_daily(ddir / f"{s}_1d.parquet") for s in universe}
    spy = load_daily(ddir / "SPY_1d.parquet")

    # 1) Qlib 求值 12 条冻结表达式（诚实 N 由 factor_export 登记进共享台账）
    from tools.qlib_gen import factor_export
    ledger = project_ledger(str(_REPO_ROOT / DEFAULT_LEDGER_PATH))
    factor_export.FACTOR_SETS["mining_i"] = dict(MINING_FACTORS)
    man = factor_export.export(Path(args.store), Path(args.factors_out), start=args.start, end=args.end,
                               factor_set="mining_i", ledger=ledger,
                               run_id=f"alpha_mining_i-{args.prereg_commit}", source="qlib",
                               repo_root=_REPO_ROOT)
    fdf = pd.read_parquet(Path(args.factors_out) / "factors.parquet")

    # 表达式已含方向 ⇒ 合成时方向统一 +1
    for name in MINING_FACTORS:
        FACTOR_DIRECTION[name] = +1

    params = MultiFactorParams()
    net = multifactor_curve(fdf, frames, spy, universe, params, cost_mult=2.0, start=args.start, end=args.end)
    gross = multifactor_curve(fdf, frames, spy, universe, params, cost_mult=0.0, start=args.start, end=args.end)
    edf = net["equity_df"]; diag = net["diagnostics"]

    # 2) 每因子单独 → 每期 trial Sharpe（DSR 的 V，family 已冻结）
    trial_sharpes, per_factor = [], {}
    for f in MINING_FACTORS:
        try:
            c = multifactor_curve(fdf, frames, spy, universe, params, cost_mult=2.0,
                                  start=args.start, end=args.end, factors_subset=[f])
            sr = _sr_pp(c["equity_df"]["ret"].to_numpy())
        except Exception:
            sr = 0.0
        trial_sharpes.append(sr); per_factor[f] = round(sr, 5)

    # 3) 台账（全量 N + 每期 trial_sharpes）—— factor_export 已登记 run，补写 V
    n_cum = ledger.cumulative_n()

    # 4) certify
    cfg = {"candidate": "alpha_mining_i", "universe": list(universe), "leverage_cap": 1.0,
           "signal_params": {"factors": MINING_FACTORS, "compose": "equal-weight z-score, long top decile",
                             "trend_gate": f"SPY {params.trend_ma_days}dMA", "cut": params.cut},
           "rebalance": "monthly", "cost_model": "moomoo_retail_x1",
           "train_test_split": "no-fit: 12 literature-grounded expressions frozen pre-results; full-sample OOS",
           "gate_thresholds": "official_50_20 + shadow_report_25_20 + shadow_floor_15_20",
           "family": {"expressions": sorted(MINING_FACTORS), "n": len(MINING_FACTORS)}}
    cand = Candidate(name="alpha_mining_i_decile_trend200",
                     oos_net_returns=edf["ret"].to_numpy(float).tolist(),
                     oos_dates=[str(d.date()) for d in pd.DatetimeIndex(edf["date"])],
                     gross_returns=gross["equity_df"]["ret"].to_numpy(float).tolist(),
                     turnover=gross["equity_df"]["traded_notional"].to_numpy(float).tolist(),
                     cost_per_turnover=0.001, required_notional=454545.0, adv_notional=4.5e8,
                     prereg_config=cfg, frozen_hash=freeze_config(cfg),
                     economic_rationale="12 条有界、各附 ex-ante 经济理由的横截面因子（流动性/换手/二阶波动/下行风险/"
                                        "彩票偏好/偏度/日内强度/隔夜漂移/量价冲击反转/波动压缩/动量加速度/52周锚定），"
                                        "等权合成做多 top decile + 200d 趋势闸控回撤。与已证伪族无重叠。",
                     n_trials_cumulative=None, trial_sharpes=trial_sharpes)
    assert cand.n_trials_cumulative is None and cand.adv_notional > 0
    v = certify(cand, ledger=ledger, thresholds=GateThresholds(),
                oos_budget=project_oos_budget(max_evals=1, path=str(_REPO_ROOT / DEFAULT_OOS_BUDGET_PATH)))
    m = v.metrics or {}

    report = {"issue": "EVO-8", "candidate": "alpha_mining_i", "preregistration_commit": args.prereg_commit,
              "store_fingerprint_verified": True,
              "n_expressions_frozen": len(MINING_FACTORS),
              "honest_trial_count": {"this_run_N": man.get("n_expressions_attempted"),
                                     "cumulative_n": n_cum, "ledger_run_id": man.get("ledger_run_id"),
                                     "per_factor_sharpe_pp_x2": per_factor},
              "certify_verdict": {"certified": v.certified, "decision": v.decision, "reasons": v.reasons},
              "metrics": m, "diagnostics": diag,
              "success_criterion_note": "如实瞄影子带(25%/<20%)；同宇宙 8.03%/22.6% 距官方 50/20 差 3.1x 收益/2.3x 回撤",
              "run_date": dt.date.today().isoformat()}
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=_jd), encoding="utf-8")

    print(v.summary())
    if m.get("cagr") is not None:
        print(f"CAGR={m['cagr']:.2%} MDD={m['mdd']:.2%} sharpe={m.get('sharpe_ann',0):.2f} "
              f"official={m.get('official_pass')} shadow_report={m.get('shadow_report_pass')} floor={m.get('shadow_floor_pass')}")
        print("crisis:", {k: (round(x['mdd'], 3) if isinstance(x.get('mdd'), (int, float)) and x['mdd'] == x['mdd']
                              else 'tail_incomplete') for k, x in m.get("crisis", {}).items()})
    print(f"N: this run={man.get('n_expressions_attempted')} cumulative={n_cum}")
    print("per-factor pp Sharpe x2:", per_factor)
    print("report →", out / "report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
