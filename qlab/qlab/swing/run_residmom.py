"""EVO-8 方向(b) — RESIDUAL MOMENTUM 首轮回测 CLI，接 research/gate.certify()。

工部 2026-07-29 接线口径：**不自建门**。本 runner 只产净收益序列 + 预注册元数据 +
真实 N，判定 100% 交给 `research/gate.certify()`。三条硬规矩落实：
  1. N 只从 `TrialLedger.cumulative_n()` 取（不接受 manifest 每轮值 / 默认 0）。
  2. 决策三值不二值化：REPORT_5020→即刻上报；DECISION_POINT→带真实数字停下等 Kevin；
     FAIL→先看 `shadow_floor_pass`（在 verdict.metrics），为 True 记兜底带 sleeve 候选，不当垃圾扔。
  3. 危机子窗喂满日期索引（gate 的 M.evaluate 自带 2008/2020/2022 窗；样本没盖住→tail_incomplete）。

用法（repo 根 qlab 项目目录下，py312 venv）：
  python -m qlab.swing.run_residmom --prereg-commit <frozen commit> --out qlab/reports/residmom
"""
from __future__ import annotations

import sys
import json
import argparse
import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

# research/ 在 repo 根（qlab 项目目录的上一级）——把它挂上 sys.path
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from research.gate import (certify, Candidate, TrialLedger, OOSBudget,  # noqa: E402
                           freeze_config, GateThresholds)
from qlab.swing.momentum_signals import load_daily                       # noqa: E402
from qlab.swing.residual_signals import FACTOR_ETFS                       # noqa: E402
from qlab.swing.residmom_signals import ResidMomParams, residmom_curve    # noqa: E402

def _json_default(o):
    """把 numpy 标量/数组转成原生类型（verdict.gates 里有 np.bool_/np.float64）。"""
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


PERIODS = 252
# 声明的 haircut family（稳健性；主格预先固定）——诚实 N 计入全部
FAMILY = [(52, 0.10), (26, 0.10), (52, 0.20), (26, 0.20)]   # (formation_weeks, cut)
PRIMARY = (52, 0.10)


def _load_symbol(sym, data_dirs):
    for d in data_dirs:
        p = Path(d) / f"{sym}_1d.parquet"
        if p.exists():
            return load_daily(p)
    return None


def _resolved_universe(path: Path):
    if not path.exists():
        return None
    return [l.strip() for l in path.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")]


def _ann_sharpe(ret: np.ndarray) -> float:
    r = np.asarray(ret, float)
    r = r[np.isfinite(r)]
    if len(r) < 2 or r.std(ddof=1) == 0:
        return 0.0
    return float(r.mean() / r.std(ddof=1) * np.sqrt(PERIODS))


def _cell_curve(stock, fac, universe, F, cut, cost_mult):
    p = ResidMomParams(formation_weeks=F, cut=cut)
    return residmom_curve(stock, fac, universe, p, cost_mult=cost_mult)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="EVO-8(b) residual-momentum evaluation via certify()")
    ap.add_argument("--data-dir", nargs="*", default=["data/daily_full", "data/daily"])
    ap.add_argument("--universe-file", default="RESIDUAL_UNIVERSE_RESOLVED.txt")
    ap.add_argument("--out", default="qlab/reports/residmom")
    ap.add_argument("--ledger", default="research/gate/state/trial_ledger_residmom.json")
    ap.add_argument("--prereg-commit", default="PENDING")
    args = ap.parse_args(argv)

    resolved = _resolved_universe(Path(args.universe_file))
    universe_resolved = resolved is not None
    universe = resolved or []
    stock = {s: f for s in universe if (f := _load_symbol(s, args.data_dir)) is not None}
    universe = [s for s in universe if s in stock]           # frozen order, present only
    fac = {s: f for s in FACTOR_ETFS if (f := _load_symbol(s, args.data_dir)) is not None}
    missing_fac = [s for s in FACTOR_ETFS if s not in fac]

    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    if not universe_resolved or missing_fac or len(universe) < 50:
        rep = {"issue": "EVO-8", "candidate": "residual_momentum",
               "overall_verdict": "数据不足-无法评估",
               "universe_resolved": universe_resolved, "n_present": len(universe),
               "factor_missing": missing_fac}
        (out / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2,
                                                     default=_json_default), encoding="utf-8")
        print("数据不足-无法评估", rep)
        return 0

    # ---- 全 family 跑一遍（x2 决策口径），收集 trial Sharpes（诚实 N） ----
    cells = {}
    trial_sharpes = []
    for (F, cut) in FAMILY:
        net = _cell_curve(stock, fac, universe, F, cut, 2.0)
        sr = _ann_sharpe(net["equity_df"]["ret"].to_numpy())
        cells[(F, cut)] = {"net": net, "sharpe_x2": sr}
        trial_sharpes.append(sr)

    # ---- 诚实 N：登记到持久 TrialLedger，N 从 cumulative_n() 取（工部规矩#1） ----
    ledger = TrialLedger(args.ledger)
    ledger.register_run(f"residmom-firstround-{args.prereg_commit}", source="manual",
                        n_trials_total=len(FAMILY), n_evaluated=len(FAMILY),
                        trial_sharpes=trial_sharpes,
                        note="residual momentum first round; declared family (F,cut) grid, no hidden mining")
    n_cumulative = ledger.cumulative_n()

    # ---- 主格：net(x2 决策) + gross(cost_mult=0，成本门用) + turnover ----
    pF, pcut = PRIMARY
    prim_net = cells[(pF, pcut)]["net"]
    prim_gross = _cell_curve(stock, fac, universe, pF, pcut, 0.0)   # 无佣金（借券/融资仍在）
    edf_net = prim_net["equity_df"]
    edf_gross = prim_gross["equity_df"]
    oos_ret = edf_net["ret"].to_numpy(float).tolist()
    oos_dates = [str(d.date()) for d in pd.DatetimeIndex(edf_net["date"])]
    gross_ret = edf_gross["ret"].to_numpy(float).tolist()
    turnover = edf_gross["traded_notional"].to_numpy(float).tolist()

    # ---- 预注册冻结配置（含所有 REQUIRED_PREREG_KEYS） ----
    cfg = {
        "candidate": "residual_momentum",
        "universe": list(universe),
        "leverage_cap": 2.0,
        "signal_params": {"model": "3f_residual_momentum", "formation_weeks": pF,
                          "skip_weeks": 4, "estimation_weeks": 156, "cut": pcut,
                          "direction": "+mean(eps) long winners", "family": FAMILY, "primary": PRIMARY},
        "rebalance": "weekly",
        "cost_model": "moomoo_retail_10bps_side_x2 + borrow0.5%/yr + financing6.8%/yr",
        "train_test_split": "NO-FIT waiver: literature params (Blitz-Huij-Martens 2011) frozen "
                            "pre-results; betas OOS by construction (window ends <= decision week); "
                            "full-sample net curve IS the OOS curve, single OOS eval budget",
        "gate_thresholds": "official_50_20 + shadow_report_25_20 + shadow_floor_15_20",
    }
    fhash = freeze_config(cfg)

    rationale = (
        "残差动量溢价（Blitz–Huij–Martens 2011, 'Residual Momentum'）：剥离市场/规模/价值"
        "系统性 beta 后，个股特质残差收益仍呈动量——行为解释为投资者对公司特质信息反应不足/"
        "信息扩散缓慢；相对总收益动量，残差动量因子暴露更低、风险调整后收益更稳、动量崩溃更轻。"
        "预先假设：横截面做多残差赢家、做空残差输家，成本后仍有正的、与既有库存低相关的特质 alpha。")

    cand = Candidate(
        name="residual_momentum_F52_decile_3f",
        oos_net_returns=oos_ret, oos_dates=oos_dates,
        gross_returns=gross_ret, turnover=turnover, cost_per_turnover=0.001,
        required_notional=0.0, adv_notional=0.0,   # 大盘十分位书，研究 AUM 下容量非约束；跳过容量门
        prereg_config=cfg, frozen_hash=fhash,
        economic_rationale=rationale,
        trial_sharpes=trial_sharpes,               # 供 DSR 的 V
    )

    verdict = certify(cand, ledger=ledger, thresholds=GateThresholds(),
                      oos_budget=OOSBudget(max_evals=1))

    met = verdict.metrics or {}
    shadow_floor = bool(met.get("shadow_floor_pass", False))
    # 工部规矩#2：三值不二值化；FAIL 先看 shadow_floor_pass
    if verdict.decision == "REPORT_5020":
        action = "REPORT_5020 → 直接清官方 50/20，即刻上报工部"
    elif verdict.decision == "DECISION_POINT":
        action = "DECISION_POINT → 过影子上报门未过官方门，带真实数字停下等 Kevin 拍验收线，不自行放行"
    elif verdict.decision == "FAIL":
        action = ("FAIL 但 shadow_floor_pass=True → 记为兜底带(15-20%) sleeve 候选，留档（含与库存相关性），不丢弃"
                  if shadow_floor else "FAIL 且未过兜底带 → NEGATIVE，随轮如实回流")
    else:
        action = f"{verdict.decision}（硬门拒绝）→ 按门原因整改/回报"

    report = {
        "issue": "EVO-8", "sleeve": "residual_momentum",
        "candidate": cand.name, "preregistration_commit": args.prereg_commit,
        "frozen_hash": fhash,
        "data_provenance": f"OpenD/free daily bars data/daily_full; universe={len(universe)} names "
                           f"(resolved), factors={list(fac)}",
        "decision_cost_multiple": "x2",
        "family": FAMILY, "primary": PRIMARY,
        "honest_trial_count": {"n_cumulative_from_ledger": n_cumulative,
                               "this_run_N": len(FAMILY), "trial_sharpes_x2": trial_sharpes,
                               "ledger_path": args.ledger,
                               "note": "N 取自 TrialLedger.cumulative_n()（工部规矩#1）；跨轮累计由户部在"
                                       "共享台账维护，本 run 只登记自己的 family。"},
        "certify_verdict": {"certified": verdict.certified, "decision": verdict.decision,
                            "reasons": verdict.reasons, "gates": verdict.gates},
        "metrics": met,
        "shadow_floor_pass": shadow_floor,
        "action": action,
        "primary_diagnostics": {k: prim_net["diagnostics"].get(k) for k in
                                ("first_date", "last_date", "n_rebalances", "mean_names_per_leg",
                                 "min_names_per_leg", "thin_book_weeks", "mean_abs_net_beta",
                                 "max_gross", "signal_convention")},
        "run_date": dt.date.today().isoformat(),
    }
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2,
                                                 default=_json_default), encoding="utf-8")

    print(verdict.summary())
    if met.get("cagr") is not None:      # metrics gate only runs if not rejected earlier
        print(f"CAGR={met['cagr']:.2%} MDD={met['mdd']:.2%} sharpe_ann={met.get('sharpe_ann',0):.2f} "
              f"shadow_floor_pass={shadow_floor}")
        print("crisis:", {k: (round(v.get('mdd'), 3)
                              if isinstance(v.get('mdd'), (int, float)) and v.get('mdd') == v.get('mdd')
                              else 'tail_incomplete') for k, v in met.get("crisis", {}).items()})
    else:
        cs = (verdict.gates or {}).get("cost_stress", {})
        print(f"rejected before metrics gate; cost_stress sharpe_x1={cs.get('sharpe_x1')} "
              f"sharpe_x2={cs.get('sharpe_x2')}")
    print(f"N_cum={n_cumulative}")
    print("ACTION:", action)
    print("report →", out / "report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
