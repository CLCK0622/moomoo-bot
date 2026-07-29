"""EVO-8 方向(b) 候选 A — 利率 carry 起草 runner：曲线 → adapter → 相关性(sleeve判据) → certify 接线。

⚠️ **正式 verdict 前置未满足**（工部 2026-07-29）：户部门侧 DSR 单位契约修正未落地前，本候选不出正式
verdict。且 canonical 曲线信号需都水的 FRED DGS2/DGS10（本 agent 运行时 FRED 超时不可达）。故本 runner：
  - 无 --certify 时：只出曲线 + 与库存相关性（sleeve 判据机制），**不判定**；
  - 有 --certify（数据+门就位后）时：走 certify()，四条接线照 CARRY_RATES 预注册。

slope 源：FRED CSV（都水落库，格式 date,DGS2,DGS10 或 date,slope）。ETF：SHY/IEF/TLT 复权日线 parquet。
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

from qlab.swing.momentum_signals import load_daily                        # noqa: E402
from qlab.swing.carry_rates_signals import CarryRatesParams, carry_rates_curve  # noqa: E402

UNIVERSE = ["SHY", "IEF", "TLT"]


def load_slope(path: Path) -> pd.DataFrame:
    """FRED CSV → DataFrame[date, slope]。支持 (date,slope) 或 (date,DGS2,DGS10)。"""
    df = pd.read_csv(path)
    cols = {c.lower(): c for c in df.columns}
    dcol = cols.get("date") or list(df.columns)[0]
    df["date"] = pd.to_datetime(df[dcol])
    if "slope" in cols:
        df["slope"] = pd.to_numeric(df[cols["slope"]], errors="coerce")
    elif "dgs2" in cols and "dgs10" in cols:
        df["slope"] = pd.to_numeric(df[cols["dgs10"]], errors="coerce") - pd.to_numeric(df[cols["dgs2"]], errors="coerce")
    else:
        raise ValueError("slope CSV 需含 slope 或 (DGS2,DGS10)")
    return df[["date", "slope"]].dropna()


def inventory_correlations(a_curve: pd.DataFrame, inv_dir: Path) -> dict:
    """A 与现有库存（GEM/残差动量/多因子）日频收益相关性——sleeve 判据核心（工部强调）。
    inv_dir 下每条库存曲线存为 <name>_equity.csv（date,ret）。缺失则记 data_pending。"""
    a = a_curve[["date", "ret"]].copy()
    a["date"] = pd.to_datetime(a["date"])
    out = {}
    if not inv_dir.exists():
        return {"status": "inventory_curves_pending",
                "note": "GEM/残差动量/多因子 曲线未落地此目录；正式相关性等三条曲线 CSV 就位"}
    for f in sorted(inv_dir.glob("*_equity.csv")):
        name = f.stem.replace("_equity", "")
        inv = pd.read_csv(f); inv["date"] = pd.to_datetime(inv["date"])
        m = pd.merge(a, inv[["date", "ret"]].rename(columns={"ret": "iret"}), on="date", how="inner")
        if len(m) > 20:
            out[name] = round(float(np.corrcoef(m["ret"], m["iret"])[0, 1]), 4)
    return {"status": "ok" if out else "inventory_curves_pending", "corr_with_inventory": out,
            "note": "低/负相关（债 vs 股）= 分散价值；standalone 判负≠sleeve 判负"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="EVO-8(b) 候选 A 利率 carry 起草")
    ap.add_argument("--data-dir", default="data/rates", help="SHY/IEF/TLT parquet 目录（都水落库）")
    ap.add_argument("--slope-csv", default="data/rates/fred_curve.csv", help="FRED 曲线 CSV（都水落库）")
    ap.add_argument("--inventory-dir", default="qlab/reports/inventory_curves")
    ap.add_argument("--out", default="qlab/reports/carry_rates")
    ap.add_argument("--certify", action="store_true", help="数据+门就位后才置；否则只出曲线+相关性、不判定")
    ap.add_argument("--prereg-commit", default="PENDING")
    args = ap.parse_args(argv)

    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    ddir = Path(args.data_dir); slope_path = Path(args.slope_csv)
    missing = [s for s in UNIVERSE if not (ddir / f"{s}_1d.parquet").exists()]
    if missing or not slope_path.exists():
        rep = {"issue": "EVO-8", "candidate": "carry_rates", "status": "DATA_PENDING",
               "missing_etf": missing, "slope_csv_present": slope_path.exists(),
               "note": "等都水落地 FRED DGS2/DGS10 + SHY/IEF/TLT parquet（本 agent FRED 不可达）。"
                       "adapter/预注册/相关性机制已就位，数据到即可复跑。"}
        (out / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        print("DATA_PENDING:", rep["note"]); return 0

    frames = {s: load_daily(ddir / f"{s}_1d.parquet") for s in UNIVERSE}
    slope = load_slope(slope_path)
    params = CarryRatesParams()
    net = carry_rates_curve(slope, frames, UNIVERSE, params, cost_mult=2.0)
    corr = inventory_correlations(net["equity_df"], Path(args.inventory_dir))

    report = {"issue": "EVO-8", "candidate": "carry_rates", "preregistration_commit": args.prereg_commit,
              "status": "DRAFT_NO_VERDICT" if not args.certify else "CERTIFIED_RUN",
              "diagnostics": net["diagnostics"], "sleeve_correlation": corr,
              "run_date": dt.date.today().isoformat()}

    if args.certify:
        # 前置：DSR 门修正合入后才允许（trial Sharpe 每期口径已修 ac687cc）
        from research.gate import (certify, Candidate, OOSBudget, freeze_config, GateThresholds,
                                   project_ledger, DEFAULT_LEDGER_PATH)
        gross = carry_rates_curve(slope, frames, UNIVERSE, params, cost_mult=0.0)
        edf = net["equity_df"]
        ledger = project_ledger(str(_REPO_ROOT / DEFAULT_LEDGER_PATH))
        cfg = {"candidate": "carry_rates", "universe": UNIVERSE, "leverage_cap": 2.0,
               "signal_params": {"mechanism": "curve steepness DGS10-DGS2 → duration ladder",
                                 "hi": params.hi_thresh, "lo": params.lo_thresh, "assets": params.assets,
                                 "killer_test": "A=2022_rate_shock"},
               "rebalance": "monthly", "cost_model": "moomoo_retail_x1",
               "train_test_split": "NO-FIT waiver: curve-regime thresholds frozen pre-results; full-sample OOS",
               "gate_thresholds": "official_50_20 + shadow_report_25_20 + shadow_floor_15_20"}
        # 每因子/单腿试验 Sharpe 每期口径（DSR 单位契约，ac687cc）
        def _sr_pp(r):
            r = np.asarray(r, float); r = r[np.isfinite(r)]
            return float(r.mean() / r.std(ddof=1)) if len(r) > 1 and r.std(ddof=1) > 0 else 0.0
        cand = Candidate(name="carry_rates_curve_duration",
                         oos_net_returns=edf["ret"].to_numpy(float).tolist(),
                         oos_dates=[str(d.date()) for d in pd.DatetimeIndex(edf["date"])],
                         gross_returns=gross["equity_df"]["ret"].to_numpy(float).tolist(),
                         turnover=gross["equity_df"]["traded_notional"].to_numpy(float).tolist(),
                         cost_per_turnover=0.001, required_notional=454545.0, adv_notional=5e8,
                         prereg_config=cfg, frozen_hash=freeze_config(cfg),
                         economic_rationale="利率 carry：曲线陡度承载期限溢价+roll-down；陡则上久期收 carry，"
                                            "平/倒挂退短久期避久期风险。long/flat 不做空债，作分散/回撤控制 sleeve。",
                         n_trials_cumulative=None, trial_sharpes=[_sr_pp(edf["ret"].to_numpy())])
        assert cand.n_trials_cumulative is None and cand.adv_notional > 0
        v = certify(cand, ledger=ledger, thresholds=GateThresholds(), oos_budget=OOSBudget(max_evals=1))
        report["certify_verdict"] = {"certified": v.certified, "decision": v.decision, "reasons": v.reasons}
        report["metrics"] = v.metrics
        print(v.summary())

    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    d = net["diagnostics"]
    print(f"[carry_rates DRAFT] {d['first_date']}→{d['last_date']} alloc={ {k:round(x,2) for k,x in d['alloc_frac'].items()} } "
          f"switches={d['n_switches']}")
    print("sleeve correlation:", corr.get("status"), corr.get("corr_with_inventory", ""))
    print("status:", report["status"], "→", out / "report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
