"""EVO-8 方向(b) 候选 C — 宏观-信用 regime runner，接 research/gate.certify()。

复用已过门的 carry ETF-配置引擎 `carry_rates_curve`（信号源不变，只把「陡度→久期」换成
「BAA10Y 利差水平→ 风险/中/避险腿」）：s<1.8→SPY(calm)、1.8≤s<2.6→IEF、s≥2.6→BIL(stress)。
发布滞后（工部 2026-07-30，对 C 绑定前视）：BAA10YM 月频、月 M 值约 M+1 发布 ⇒ 利差日期整体后移
~1 月+数日，再经 carry 引擎 close(T)→open(T+1) 执行 ⇒ 信号相对成交至少滞后一个月+一日，绝不同日成交。
修订偷看已证据化排除（§3a 实测修订≤1bp）。判定 100% 交 certify()。
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
from qlab.swing.carry_rates_signals import CarryRatesParams, carry_rates_curve          # noqa: E402

UNIVERSE = ["BIL", "IEF", "SPY"]                 # defensive / mid / risk（carry 引擎 long/mid/short 对应）
FAMILY = [(1.8, 2.6), (1.5, 2.5), (2.0, 3.0)]    # 冻结阈值对 (lo, hi)；主 (1.8,2.6)
PRIMARY = (1.8, 2.6)
PUB_LAG_DAYS = 35                                # 月频发布滞后：值日期后移 ~1 月+，保证 run 时已发布


def _sr_pp(r):
    r = np.asarray(r, float); r = r[np.isfinite(r)]
    return float(r.mean() / r.std(ddof=1)) if len(r) > 1 and r.std(ddof=1) > 0 else 0.0


def _jd(o):
    if isinstance(o, np.bool_): return bool(o)
    if isinstance(o, np.integer): return int(o)
    if isinstance(o, np.floating): return float(o)
    if isinstance(o, np.ndarray): return o.tolist()
    return str(o)


def _params(lo, hi):
    # carry 引擎：signal≥hi→long_asset, ≥lo→mid, else short。C: 利差≥hi→BIL(避险), ≥lo→IEF, else SPY(风险)
    return CarryRatesParams(hi_thresh=hi, lo_thresh=lo, long_asset="BIL", mid_asset="IEF", short_asset="SPY")


def _load_spread(path: Path) -> pd.DataFrame:
    """latest BAA10YM (date,value月频) → 发布滞后后移的 (date, slope) 供 carry 引擎 ffill。"""
    d = pd.read_parquet(path)
    d["date"] = pd.to_datetime(d["date"]) + pd.Timedelta(days=PUB_LAG_DAYS)   # 发布滞后
    return d.rename(columns={"value": "slope"})[["date", "slope"]].dropna().sort_values("date")


def _inv_corr(a_ret: pd.DataFrame, inv_dir: Path) -> dict:
    a = a_ret[["date", "ret"]].copy(); a["date"] = pd.to_datetime(a["date"])
    out = {}
    for f in sorted(inv_dir.glob("*_equity.csv")):
        name = f.stem.replace("_equity", "")
        inv = pd.read_csv(f); inv["date"] = pd.to_datetime(inv["date"])
        m = pd.merge(a, inv[["date", "ret"]].rename(columns={"ret": "i"}), on="date", how="inner")
        if len(m) > 30:
            out[name] = round(float(np.corrcoef(m["ret"], m["i"])[0, 1]), 4)
    return out


def _find(sym, dirs=("data/daily_full", "data/gem", "data/rate_carry")):
    for d in dirs:
        p = Path(d) / f"{sym}_1d.parquet"
        if p.exists():
            return load_daily(p)
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="EVO-8(b) 候选 C 宏观-信用 regime")
    ap.add_argument("--spread", default="data/credit_baa10ym_latest.parquet")
    ap.add_argument("--inventory-dir", default="qlab/reports/inventory_curves")
    ap.add_argument("--out", default="qlab/reports/credit_regime")
    ap.add_argument("--prereg-commit", default="PENDING")
    ap.add_argument("--supersedes", default=None)
    ap.add_argument("--certify", action="store_true")
    args = ap.parse_args(argv)

    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    frames = {s: _find(s) for s in UNIVERSE}
    missing = [s for s in UNIVERSE if frames[s] is None]
    if missing or not Path(args.spread).exists():
        (out / "report.json").write_text(json.dumps({"status": "DATA_PENDING", "missing": missing,
            "spread_present": Path(args.spread).exists()}, ensure_ascii=False, indent=2), encoding="utf-8")
        print("DATA_PENDING", missing); return 0
    spread = _load_spread(Path(args.spread))

    # family 各阈值对 → x2 每期 Sharpe（DSR 的 V）
    trial_sharpes = []
    for lo, hi in FAMILY:
        c = carry_rates_curve(spread, frames, UNIVERSE, _params(lo, hi), cost_mult=2.0)
        trial_sharpes.append(_sr_pp(c["equity_df"]["ret"].to_numpy()))

    plo, phi = PRIMARY
    net = carry_rates_curve(spread, frames, UNIVERSE, _params(plo, phi), cost_mult=2.0)
    gross = carry_rates_curve(spread, frames, UNIVERSE, _params(plo, phi), cost_mult=0.0)
    edf = net["equity_df"]; diag = net["diagnostics"]
    corr = _inv_corr(edf, Path(args.inventory_dir))

    report = {"issue": "EVO-8", "candidate": "credit_regime", "preregistration_commit": args.prereg_commit,
              "primary_thresholds": {"lo": plo, "hi": phi}, "family": FAMILY,
              "publication_lag": {"spread_shift_days": PUB_LAG_DAYS,
                                  "note": "利差日期后移~1月+，再 close(T)→open(T+1)；信号相对成交≥1月+1日，无同日成交",
                                  "signal_first_date": diag["first_date"]},
              "revision_evidence_bps": {"max_abs_rev": 0.0100, "median": 0.0, "std": 0.0007,
                                        "note": "§3a 实测：latest−PIT ≤1bp，市场价序列基本不修订，latest 用之有据"},
              "family_trial_sharpes_pp_x2": dict(zip([f"{lo},{hi}" for lo, hi in FAMILY], trial_sharpes)),
              "diagnostics": {k: diag.get(k) for k in ("first_date", "last_date", "alloc_frac", "n_switches")},
              "sleeve_correlation": corr, "run_date": dt.date.today().isoformat()}

    if args.certify:
        ledger = project_ledger(str(_REPO_ROOT / DEFAULT_LEDGER_PATH))
        cfg = {"candidate": "credit_regime", "universe": UNIVERSE, "leverage_cap": 1.0,
               "signal_params": {"signal": "BAA10Y credit-spread level regime", "lo": plo, "hi": phi,
                                 "map": "s>=hi->BIL, s>=lo->IEF, else SPY", "pub_lag_days": PUB_LAG_DAYS,
                                 "killer_test": "C=FRED_vintage_防前视 (rev<=1bp evidenced) + T->T+1 lag"},
               "rebalance": "monthly", "cost_model": "moomoo_retail_x1",
               "train_test_split": "no-fit round thresholds frozen pre-results; full-sample OOS (rev-evidenced latest)",
               "gate_thresholds": "official_50_20 + shadow_report_25_20 + shadow_floor_15_20",
               "family": {"threshold_pairs": FAMILY, "primary": list(PRIMARY)}}
        rec = ledger.register_run(run_id=f"credit_regime-{args.prereg_commit}", source="manual",
                                  n_trials_total=len(FAMILY), n_evaluated=len(FAMILY), trial_sharpes=trial_sharpes,
                                  candidate_id="macro_credit_regime", supersedes=args.supersedes,
                                  note="信用 regime C：阈值 family 3；每期 trial Sharpe；修订≤1bp、发布滞后 T→T+1")
        report["ledger_run_id"] = rec.run_id; report["cumulative_n_after_C"] = ledger.cumulative_n()
        cand = Candidate(name="credit_regime_baa10y",
                         oos_net_returns=edf["ret"].to_numpy(float).tolist(),
                         oos_dates=[str(d.date()) for d in pd.DatetimeIndex(edf["date"])],
                         gross_returns=gross["equity_df"]["ret"].to_numpy(float).tolist(),
                         turnover=gross["equity_df"]["traded_notional"].to_numpy(float).tolist(),
                         cost_per_turnover=0.001, required_notional=454545.0, adv_notional=5e9,
                         prereg_config=cfg, frozen_hash=freeze_config(cfg),
                         economic_rationale="信用利差是权益压力的领先/同步指标：利差低=calm→持股(SPY)，走阔=stress→"
                                            "退中久期/现金(IEF/BIL)。long/flat 无裸空，作 regime 择时/回撤控制 sleeve。",
                         n_trials_cumulative=None, trial_sharpes=trial_sharpes)
        assert cand.n_trials_cumulative is None and cand.adv_notional > 0
        v = certify(cand, ledger=ledger, thresholds=GateThresholds(),
                    oos_budget=project_oos_budget(max_evals=1, path=str(_REPO_ROOT / DEFAULT_OOS_BUDGET_PATH)))
        m = v.metrics or {}
        report["certify_verdict"] = {"certified": v.certified, "decision": v.decision, "reasons": v.reasons}
        report["metrics"] = m
        floor = bool(m.get("shadow_floor_pass"))
        report["verdict"] = ("REPORT_5020→先回工部" if v.decision == "REPORT_5020" else
                             "DECISION_POINT→带数字先回工部" if v.decision == "DECISION_POINT" else
                             ("FAIL 但 shadow_floor_pass→兜底带 sleeve 候选" if floor else
                              "standalone 负；按 sleeve 组件级看相关性"))
        print(v.summary())
        if m.get("cagr") is not None:
            print(f"CAGR={m['cagr']:.2%} MDD={m['mdd']:.2%} decision={m.get('decision')} floor={floor}")
            print("crisis:", {k: (round(x['mdd'], 3) if isinstance(x.get('mdd'), (int, float)) and x['mdd'] == x['mdd']
                                  else 'tail_incomplete') for k, x in m.get("crisis", {}).items()})

    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=_jd), encoding="utf-8")
    print(f"[C credit_regime] alloc={ {k: round(x,2) for k,x in diag['alloc_frac'].items()} } "
          f"switches={diag['n_switches']} window {diag['first_date']}→{diag['last_date']}")
    print("sleeve corr:", corr)
    print("report →", out / "report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
