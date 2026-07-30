"""EVO-8 方向(b) 候选 B — FOMC 季节性（pre-announcement drift）runner，接 research/gate.certify()。

复用 EVO-130 S5 原语（s5_fomc_trades / event_edge / load_fomc_calendar / simulate_book），不重写信号。
杀手验证 = 2019+ OOS 衰减复核（DECAY_SPLIT=2019-01-01）。四条新门契约（工部 2026-07-30）全落实：
project_oos_budget() 共享落盘单发 / register_run 带 candidate_id(+supersedes) / 预注册冻 family /
每条台账带每期 trial_sharpes。sparse 事件腿：full-capital certify 必 FAIL(现金为主)，B 判据在 2019+ 事件 edge。
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

from research.gate import (certify, Candidate, GateThresholds, freeze_config,           # noqa: E402
                           project_ledger, DEFAULT_LEDGER_PATH, project_oos_budget,
                           DEFAULT_OOS_BUDGET_PATH)
from qlab.swing.momentum_signals import load_daily                                       # noqa: E402
from qlab.swing.strategies import s5_fomc_trades, load_fomc_calendar                     # noqa: E402
from qlab.swing.book import simulate_book                                                # noqa: E402
from qlab.swing.evaluate import event_edge, _base_side_frac                              # noqa: E402

FAMILY_OFFSETS = (1, 2, 3)          # 冻结 family（决定 DSR 的 V）；主 offset=1
PRIMARY_OFFSET = 1
DECAY_SPLIT = pd.Timestamp("2019-01-01")   # B 杀手验证：2019+ OOS 衰减复核
P = 252


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
    ap = argparse.ArgumentParser(description="EVO-8(b) 候选 B FOMC 季节性")
    ap.add_argument("--spy", default="data/daily_full/SPY_1d.parquet")
    ap.add_argument("--fomc", default="data/fomc_meetings.csv")
    ap.add_argument("--out", default="qlab/reports/fomc_seasonality")
    ap.add_argument("--prereg-commit", default="PENDING")
    ap.add_argument("--supersedes", default=None, help="重冻覆盖旧 run_id（换 prereg commit 时）")
    ap.add_argument("--certify", action="store_true")
    args = ap.parse_args(argv)

    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    spy = load_daily(Path(args.spy))
    fomc = load_fomc_calendar(args.fomc)      # scheduled-only 由该原语处理
    calendar = sorted(pd.Timestamp(d) for d in pd.to_datetime(spy["date"]))
    base = _base_side_frac()

    # ---- family 各 offset：event edge(full/pre/post-2019) + 每期 Sharpe(x2) ----
    cells, trial_sharpes = {}, []
    for off in FAMILY_OFFSETS:
        trades, event_rows = s5_fomc_trades(spy, fomc, side_frac=base * 2.0, entry_offset=off)
        eq, diag, tl = simulate_book(trades, calendar, max_concurrent=1, P=P)
        rets = [r["net_return"] for r in event_rows]
        dates = [pd.Timestamp(r["date"]) for r in event_rows]
        full = event_edge(rets, seed=12345)
        post = event_edge([x for x, d in zip(rets, dates) if d >= DECAY_SPLIT], seed=12345)
        pre = event_edge([x for x, d in zip(rets, dates) if d < DECAY_SPLIT], seed=12345)
        srpp = _sr_pp(eq["ret"].to_numpy())
        trial_sharpes.append(srpp)
        cells[off] = {"n_events": len(event_rows), "edge_full": full, "edge_pre2019": pre,
                      "edge_post2019": post, "sr_per_period_x2": srpp, "equity_df": eq}

    prim = cells[PRIMARY_OFFSET]
    post = prim["edge_post2019"]; pre = prim["edge_pre2019"]
    decayed = bool(pre.get("mean", 0.0) > post.get("mean", 0.0))
    edge_survives_2019 = bool(post.get("significant_positive", False))

    report = {
        "issue": "EVO-8", "candidate": "fomc_seasonality", "preregistration_commit": args.prereg_commit,
        "primary_offset": PRIMARY_OFFSET, "family_offsets": list(FAMILY_OFFSETS),
        "decay_split": str(DECAY_SPLIT.date()), "decay_observed_pre>post": decayed,
        "killer_test_2019plus": {"edge_significant_positive": edge_survives_2019,
                                 "post2019_mean": post.get("mean"), "post2019_p_mean_le_0": post.get("p_mean_le_0"),
                                 "post2019_n": post.get("n"),
                                 "pre2019_mean": pre.get("mean"), "full_mean": prim["edge_full"].get("mean")},
        "family_trial_sharpes_per_period_x2": dict(zip([str(o) for o in FAMILY_OFFSETS], trial_sharpes)),
        "per_offset_edges": {str(o): {"n_events": c["n_events"], "edge_full_mean": c["edge_full"].get("mean"),
                                      "edge_post2019_mean": c["edge_post2019"].get("mean"),
                                      "edge_post2019_sig": c["edge_post2019"].get("significant_positive")}
                             for o, c in cells.items()},
        "run_date": dt.date.today().isoformat(),
    }

    if args.certify:
        edf = prim["equity_df"]
        ledger = project_ledger(str(_REPO_ROOT / DEFAULT_LEDGER_PATH))
        cfg = {"candidate": "fomc_seasonality", "universe": ["SPY"], "leverage_cap": 1.0,
               "signal_params": {"mechanism": "FOMC pre-announcement drift (Lucca-Moench 2015)",
                                 "entry": "close(T-offset)->close(T)", "primary_offset": PRIMARY_OFFSET,
                                 "killer_test": "B=2019+_OOS_decay"},
               "rebalance": "event_driven", "cost_model": "moomoo_retail_x1",
               "train_test_split": "no-fit event sleeve; decision = 2019+ subsample edge significance",
               "gate_thresholds": "official_50_20 + shadow_report_25_20 + shadow_floor_15_20",
               "family": {"offsets": list(FAMILY_OFFSETS), "primary_offset": PRIMARY_OFFSET}}  # 冻结 family
        rec = ledger.register_run(run_id=f"fomc_seasonality-{args.prereg_commit}", source="manual",
                                  n_trials_total=len(FAMILY_OFFSETS), n_evaluated=len(FAMILY_OFFSETS),
                                  trial_sharpes=trial_sharpes, candidate_id="fomc_seasonality",
                                  supersedes=args.supersedes,
                                  note="FOMC 季节性 B：offset family {1,2,3}(主1)；每期 trial Sharpe；2019+ 衰减复核")
        report["ledger_run_id"] = rec.run_id
        report["cumulative_n_after_B"] = ledger.cumulative_n()
        cand = Candidate(name="fomc_seasonality_off1",
                         oos_net_returns=edf["ret"].to_numpy(float).tolist(),
                         oos_dates=[str(d.date()) for d in pd.DatetimeIndex(edf["date"])],
                         gross_returns=None, turnover=None, cost_per_turnover=0.001,
                         required_notional=454545.0, adv_notional=5e9,   # SPY 流动性极充裕，如实
                         prereg_config=cfg, frozen_hash=freeze_config(cfg),
                         economic_rationale="FOMC 决议前 pre-announcement drift（Lucca-Moench 2015）：会议前"
                                            "风险溢价累积/不确定性消解带来的系统性上行。稀疏事件腿、long/flat 无裸空。",
                         n_trials_cumulative=None, trial_sharpes=trial_sharpes)   # 每期口径，不声明 ppy
        assert cand.n_trials_cumulative is None and cand.adv_notional > 0
        v = certify(cand, ledger=ledger, thresholds=GateThresholds(),
                    oos_budget=project_oos_budget(max_evals=1,     # 共享落盘单发（canonical repo-root 路径）
                                                  path=str(_REPO_ROOT / DEFAULT_OOS_BUDGET_PATH)))
        report["certify_verdict"] = {"certified": v.certified, "decision": v.decision, "reasons": v.reasons}
        report["metrics_full_capital"] = v.metrics
        report["verdict"] = ("已衰减/不可用(负向)" if not edge_survives_2019 else
                             "2019+ 仍显著-带真实数字回工部")

    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=_jd), encoding="utf-8")
    print(f"[B FOMC] primary offset={PRIMARY_OFFSET} | 2019+ edge sig_positive={edge_survives_2019} "
          f"(post2019 mean={post.get('mean',0):+.4%}, p={post.get('p_mean_le_0',1):.3f}, n={post.get('n',0)})")
    print(f"  full mean={prim['edge_full'].get('mean',0):+.4%} | pre2019 mean={pre.get('mean',0):+.4%} | decayed(pre>post)={decayed}")
    if args.certify:
        print(f"  certify(full-capital)={report['certify_verdict']['decision']} | B verdict={report['verdict']} "
              f"| cumN={report.get('cumulative_n_after_B')}")
    print("report →", out / "report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
