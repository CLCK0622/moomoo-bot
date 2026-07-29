"""EVO-8 方向(b) — GEM 过一遍 research/gate.certify()（工部 2026-07-29 要求：统一存档口径 +
把 GEM 试验数登进**共享**账本）。结论不会变（CAGR 7.98%/MDD 32.05% 两轴大幅未达）。
GEM 的 N(=2) 已由 run_multifactor 的 seed 补登进共享账本；本 runner 只读 cumulative_n()、不重登。"""
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
                           freeze_config, GateThresholds)
from qlab.swing.momentum_signals import load_daily                        # noqa: E402
from qlab.swing.gem_signals import GemParams, gem_curve                    # noqa: E402

SHARED_LEDGER = "research/gate/state/trial_ledger.json"


def _jd(o):
    if isinstance(o, np.bool_): return bool(o)
    if isinstance(o, (np.integer,)): return int(o)
    if isinstance(o, (np.floating,)): return float(o)
    if isinstance(o, np.ndarray): return o.tolist()
    return str(o)


def _sr(ret):
    r = np.asarray(ret, float); r = r[np.isfinite(r)]
    return float(r.mean() / r.std(ddof=1) * np.sqrt(252)) if len(r) > 1 and r.std(ddof=1) > 0 else 0.0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data/gem")
    ap.add_argument("--out", default="qlab/reports/gem_certify")
    ap.add_argument("--prereg-commit", default="GEM-frozen-67b9ce7")
    args = ap.parse_args(argv)

    dd = Path(args.data_dir)
    p = GemParams()
    frames = {s: load_daily(dd / f"{s}_1d.parquet") for s in p.all_symbols
              if (dd / f"{s}_1d.parquet").exists()}
    # 四资产共同可得窗（预注册 §9）
    start = str(max(pd.to_datetime(frames[s]["date"]).min() for s in frames).date())

    net = gem_curve(frames, p, cost_mult=2.0, start=start)
    gross = gem_curve(frames, p, cost_mult=0.0, start=start)
    edf = net["equity_df"]
    # family {6m,12m} 的 Sharpe → DSR 的 V
    trial_sharpes = [_sr(gem_curve(frames, GemParams(lookback_months=L), cost_mult=2.0, start=start)
                         ["equity_df"]["ret"].to_numpy()) for L in (6, 12)]

    ledger = TrialLedger(SHARED_LEDGER)              # GEM 的 N 已由 multifactor seed 登记，读即可
    n_cum = ledger.cumulative_n()

    cfg = {"candidate": "gem_dual_momentum", "universe": p.all_symbols, "leverage_cap": 1.0,
           "signal_params": {"lookback_months": 12, "family": [6, 12], "assets": p.held_assets,
                             "hurdle": p.tbill, "rule": "abs+rel dual momentum, AGG risk-off"},
           "rebalance": "monthly", "cost_model": "moomoo_retail_10bps_side_x2",
           "train_test_split": "NO-FIT waiver (Antonacci 2014 literature params frozen pre-results); "
                               "common-availability window from " + start,
           "gate_thresholds": "official_50_20 + shadow_report_25_20 + shadow_floor_15_20"}
    fhash = freeze_config(cfg)
    cand = Candidate(
        name="gem_dual_momentum_12m",
        oos_net_returns=edf["ret"].to_numpy(float).tolist(),
        oos_dates=[str(d.date()) for d in pd.DatetimeIndex(edf["date"])],
        gross_returns=gross["equity_df"]["ret"].to_numpy(float).tolist(),
        turnover=gross["equity_df"]["traded_notional"].to_numpy(float).tolist(),
        cost_per_turnover=0.001,
        required_notional=1_000_000.0, adv_notional=5_000_000_000.0,  # SPY/VEU/AGG ETF，ADV~数十亿，如实
        prereg_config=cfg, frozen_hash=fhash,
        economic_rationale="双动量（Antonacci 2014）：绝对动量(US vs T-bill)择时 + 相对动量(US vs ex-US)"
                           "择强，risk-off 切综合债券。行为(处置效应/羊群)+风险(增长期权)双解释的动量溢价。",
        n_trials_cumulative=None, trial_sharpes=trial_sharpes)
    assert cand.n_trials_cumulative is None and cand.adv_notional > 0
    v = certify(cand, ledger=ledger, thresholds=GateThresholds(), oos_budget=OOSBudget(max_evals=1))
    met = v.metrics or {}
    report = {"issue": "EVO-8", "sleeve": "gem_certify_archival", "candidate": cand.name,
              "note": "GEM 归档统一走 certify() 口径；结论与 EVO-149 原判一致（负向）。",
              "shared_ledger": SHARED_LEDGER, "cumulative_n": n_cum, "trial_sharpes": trial_sharpes,
              "certify_verdict": {"certified": v.certified, "decision": v.decision,
                                  "reasons": v.reasons, "gates": v.gates},
              "metrics": met, "window_start": start, "run_date": dt.date.today().isoformat()}
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=_jd),
                                     encoding="utf-8")
    print(v.summary())
    if met.get("cagr") is not None:
        print(f"CAGR={met['cagr']:.2%} MDD={met['mdd']:.2%} decision={met.get('decision')} "
              f"shadow_floor={met.get('shadow_floor_pass')}")
    print(f"cumulative_N={n_cum}  → report {out/'report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
