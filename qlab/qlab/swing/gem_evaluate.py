"""EVO-8 方向(b) — GEM 首轮回测 verdict builder。

镜像 `swing.momentum_evaluate.build_momentum_report`：预注册主格 + 声明的 lookback
family（多重检验 haircut）+ ×1/×2 双成本 + 危机子窗（进 verdict 非附录）+ 官方 50/20
与影子分层双口径记录。所有 gate/significance/haircut 数字来自复用的 EVO-149/EVO-130
模块，此处不重实现。

影子分层（裁定口径，仅记录、绝不自行放行）：
  官方门         : CAGR ≥ 50% 且 MDD ≤ 20%   —— 唯一 PASS 判据
  影子·组合级目标: CAGR ∈ [25%,35%) 且 MDD < 20%
  影子·兜底      : CAGR ∈ [15%,20%) 且 MDD < 20%
  过影子未过 50/20 → 停、带真实数字回报，不自行放行；直接清 50/20 → 立即上报。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..events.gates import CAGR_HURDLE, MDD_CAP, gate1_full_sample
from ..events.metrics import TRADING_DAYS_PER_YEAR, _cagr, _max_drawdown
from ..events.multiple_testing import PrimarySpec, haircut_family
from .evaluate import evaluate_curve
from .gem_signals import GemParams, gem_curve

# 危机子窗（进 verdict —— 预注册 §7）
STRESS_WINDOWS = {
    "2008_gfc": ("2008-06-01", "2009-06-30"),
    "2020_covid": ("2020-02-15", "2020-04-30"),
    "2022_ratehike_bear": ("2022-01-01", "2022-12-31"),
    "2025-2026_recent": ("2025-01-01", "2026-07-28"),
}

# 声明的 lookback family（haircut/稳健性）；主格预先固定为 12 个月
GEM_FAMILY_MONTHS = (6, 12)
GEM_PRIMARY_LB = 12

# 影子分层阈值
SHADOW_TARGET = (0.25, 0.35)   # 组合级目标带
SHADOW_FLOOR = (0.15, 0.20)    # 兜底带


def _window_stats(equity_df: pd.DataFrame, lo: str, hi: str, P: int) -> dict:
    w = equity_df[(equity_df["date"] >= pd.Timestamp(lo)) & (equity_df["date"] <= pd.Timestamp(hi))]
    if len(w) < 2:
        return {"n_days": int(len(w)), "insufficient": True}
    ret = w["ret"].to_numpy(float)
    eq = np.cumprod(1.0 + ret)
    mdd = _max_drawdown(eq)
    return {
        "n_days": int(len(w)),
        "window_return": float(eq[-1] - 1.0),
        "annualized_cagr": float(_cagr(eq, P)),
        "mdd": float(mdd),
        "worst_single_day": float(ret.min()),
        "mdd_breach_20pct": bool(mdd > MDD_CAP),
        "passed": bool(mdd <= MDD_CAP),
    }


def _shadow_tier(cagr: float, mdd: float) -> str:
    """影子分层归类（仅记录）。"""
    if mdd >= MDD_CAP:
        return "none(MDD≥20%)"
    if cagr >= CAGR_HURDLE:
        return "official_50_20"
    if SHADOW_TARGET[0] <= cagr < SHADOW_TARGET[1]:
        return "shadow_target_25_35"
    if SHADOW_FLOOR[0] <= cagr < SHADOW_FLOOR[1]:
        return "shadow_floor_15_20"
    if cagr >= SHADOW_TARGET[1]:
        return "between_35_and_50"
    if cagr >= SHADOW_FLOOR[1]:
        return "between_20_and_25"
    return "below_floor(<15%)"


def _common_start(frames, symbols) -> str | None:
    """四资产共同可得起点（预注册 §9）：各符号首日的最大值。日历从此起，12m warm-up
    自然把首次交易推到共同可得起点 + ~1 年，排除任一资产未上市的退化期。"""
    firsts = []
    for s in symbols:
        df = frames.get(s)
        if df is not None and len(df):
            firsts.append(pd.to_datetime(df["date"]).min())
    return str(max(firsts).date()) if firsts else None


def _cell(frames, params: GemParams, *, P, alpha, n_boot, seed, start=None) -> dict:
    out = {"mode": "gem", "hold": params.lookback_months,
           "lookback_months": params.lookback_months, "cost_variants": {},
           "data_window_start": start}
    for cm, tag in ((1.0, "x1"), (2.0, "x2")):
        res = gem_curve(frames, params, cost_mult=cm, start=start)
        eq, tl = res["equity_df"], res["trade_log"]
        ev = evaluate_curve(eq, tl, P=P, hurdle=CAGR_HURDLE, alpha=alpha, n_boot=n_boot, seed=seed)
        ev["diagnostics"] = res["diagnostics"]
        ev["stress"] = {name: _window_stats(eq, lo, hi, P) for name, (lo, hi) in STRESS_WINDOWS.items()}
        g1 = ev["gate1"]
        ev["shadow_tier"] = _shadow_tier(g1["cagr"], g1["mdd"])
        out["cost_variants"][tag] = ev
    return out


def _mt_cell(c):
    x2 = c["cost_variants"]["x2"]
    sig = x2["significance"]
    return {"mode": c["mode"], "hold": c["hold"],
            "p_value": sig.get("p_cagr_below_hurdle", 1.0),
            "oos_sharpe": sig.get("sharpe_point", 0.0), "oos_n": sig.get("n", 0),
            "oos_skew": sig.get("skew", 0.0), "oos_kurtosis": sig.get("kurtosis", 3.0),
            "gates_passed": bool(x2["gates_1_3_passed"])}


def _benchmarks(frames, params: GemParams, *, P, start=None) -> dict:
    """SPY buy&hold / 60-40(SPY+AGG) / 等权持有资产 —— 仅上下文，永不作 verdict。
    与 GEM 同一数据窗（start）对比才公平。"""
    from .momentum_signals import buy_and_hold_curve
    out = {}
    if frames.get(params.us) is not None and len(frames[params.us]):
        g = gate1_full_sample(buy_and_hold_curve(frames, [params.us], cost_mult=2.0, start=start)["equity_df"], P)
        out["SPY_buy_and_hold"] = {"cagr": g["cagr"], "mdd": g["mdd"]}
    present_ha = [s for s in params.held_assets if frames.get(s) is not None and len(frames.get(s))]
    if present_ha:
        g = gate1_full_sample(buy_and_hold_curve(frames, params.held_assets, cost_mult=2.0, start=start)["equity_df"], P)
        out["equal_weight_held_assets"] = {"cagr": g["cagr"], "mdd": g["mdd"], "present": present_ha}
    if (frames.get(params.us) is not None and frames.get(params.bond) is not None):
        # 60/40 近似：等权 SPY+AGG（buy&hold 引擎不支持非等权，标注为 50/50 代理）
        g = gate1_full_sample(buy_and_hold_curve(frames, [params.us, params.bond], cost_mult=2.0, start=start)["equity_df"], P)
        out["50_50_SPY_AGG_proxy_for_60_40"] = {"cagr": g["cagr"], "mdd": g["mdd"]}
    return out


def build_gem_report(frames_by_symbol, *, P=TRADING_DAYS_PER_YEAR, alpha=0.05,
                     n_boot=2000, seed=12345, prereg_commit="PENDING",
                     data_provenance="") -> dict:
    """GEM 首轮回测完整 verdict。主格=12m lookback；family=(6m,12m) 仅 haircut/稳健。"""
    base = GemParams()
    present = [s for s in base.all_symbols if frames_by_symbol.get(s) is not None
               and len(frames_by_symbol.get(s))]
    missing = [s for s in base.all_symbols if s not in present]
    # 至少要有 US + 一个避险/门槛资产才能跑
    if base.us not in present or base.bond not in present:
        return {
            "issue": "EVO-8", "candidate": "GEM dual momentum (SPY/VEU/AGG, T-bill hurdle)",
            "sleeve": "gem", "preregistration_commit": prereg_commit,
            "overall_verdict": "数据不足-无法评估",
            "verdict_reason": f"缺少核心资产（present={present}, missing={missing}）。",
            "universe_present": present, "universe_missing": missing,
        }

    # 预注册 §9：数据窗 = 四资产共同可得起点（受 VEU/BIL 上市约束），排除退化期
    common_start = _common_start(frames_by_symbol, base.all_symbols)

    runs = []
    for lb in GEM_FAMILY_MONTHS:
        runs.append(_cell(frames_by_symbol, GemParams(lookback_months=lb),
                          P=P, alpha=alpha, n_boot=n_boot, seed=seed, start=common_start))

    primary = PrimarySpec(mode="gem", hold=GEM_PRIMARY_LB, quantile=0.0, max_concurrent=1)
    mt = haircut_family([_mt_cell(c) for c in runs], primary, alpha=alpha, P=P)

    prun = next((c for c in runs if c["hold"] == GEM_PRIMARY_LB), None)
    prim_x2 = prun["cost_variants"]["x2"] if prun else None
    prim_x1 = prun["cost_variants"]["x1"] if prun else None

    stress = prim_x2["stress"] if prim_x2 else {}
    tail_fail = [k for k, v in stress.items() if isinstance(v, dict) and v.get("mdd_breach_20pct")]
    g1 = prim_x2["gate1"] if prim_x2 else {}
    gates_ok = bool(prim_x2 and prim_x2["gates_1_3_passed"])
    sig_ok = bool(prim_x2 and prim_x2["significance"].get("significant_beats_hurdle", False))
    haircut_ok = bool(mt["primary_survives_haircut"])
    official_pass = bool(gates_ok and sig_ok and haircut_ok and not tail_fail)

    shadow_tier = prim_x2["shadow_tier"] if prim_x2 else "n/a"
    cagr_x2 = g1.get("cagr", 0.0)
    mdd_x2 = g1.get("mdd", 0.0)

    if prim_x2 is None:
        verdict, reason = "需整改", "预注册主格 lookback 不在评估 family 中。"
    elif official_pass:
        verdict = "PASS(需CERTIFY+终审)"
        reason = "主格 ×2 清关 1-3、显著、过 haircut，且无危机窗破 MDD≤20%。直接清 50/20。"
    else:
        bits = []
        if not g1.get("passed", False):
            bits.append(f"官方门：CAGR={cagr_x2:.2%} vs 50%，MDD={mdd_x2:.2%} vs 20%")
        if tail_fail:
            bits.append("危机窗破 MDD>20%：" + ", ".join(tail_fail))
        if not sig_ok:
            bits.append("OOS 未显著高于 hurdle")
        # 影子分层判读（仅记录）
        if shadow_tier in ("shadow_target_25_35", "shadow_floor_15_20"):
            verdict = "过影子未过50/20-停报"
            reason = (f"未过官方 50/20（{'; '.join(bits)}）；命中影子层 {shadow_tier}"
                      f"（CAGR={cagr_x2:.2%}, MDD={mdd_x2:.2%}）。按裁定停下带真实数字回报，不自行放行。")
        else:
            verdict = "基线未达标"
            reason = (f"未过官方 50/20，且未达影子兜底（{'; '.join(bits)}）；"
                      f"影子分层={shadow_tier}（CAGR={cagr_x2:.2%}, MDD={mdd_x2:.2%}）。NEGATIVE。")

    report = {
        "issue": "EVO-8", "sleeve": "gem",
        "candidate": "GEM Global Equity Momentum (Antonacci 2014): dual momentum SPY/VEU rotate, "
                     "AGG risk-off, T-bill(BIL) absolute-momentum hurdle",
        "preregistration_commit": prereg_commit,
        "data_provenance": data_provenance,
        "decision_cost_multiple": "x2",
        "universe_present": present, "universe_missing": missing,
        "data_complete": bool(not missing),
        "data_window_start_common_availability": common_start,
        "actual_backtest_first_date": (prun["cost_variants"]["x2"]["diagnostics"]["first_date"]
                                       if prun else None),
        "lookback_family_months": list(GEM_FAMILY_MONTHS),
        "primary_lookback_months": GEM_PRIMARY_LB,
        "overall_verdict": verdict, "verdict_reason": reason,
        "official_gate_5020": {"cagr_x2": cagr_x2, "mdd_x2": mdd_x2,
                               "passed": bool(g1.get("passed", False))},
        "shadow_layers": {
            "primary_x2_tier": shadow_tier,
            "official_50_20": "CAGR>=50% & MDD<=20%",
            "shadow_target_25_35": "CAGR in [25%,35%) & MDD<20%",
            "shadow_floor_15_20": "CAGR in [15%,20%) & MDD<20%",
            "note": "影子层仅记录；PASS 只认官方 50/20。过影子未过 50/20 = 停报，不自行放行。",
        },
        "primary_gate1_x1": prim_x1["gate1"] if prim_x1 else {},
        "primary_gate1_x2": g1,
        "primary_significance_x2": prim_x2["significance"] if prim_x2 else {},
        "primary_shadow_tier_x2": shadow_tier,
        "crisis_windows_x2": stress,
        "crisis_windows_failing_mdd": tail_fail,
        "multiple_testing": mt,
        "honest_trial_count": {
            "within_candidate_N": len(GEM_FAMILY_MONTHS),
            "family_months": list(GEM_FAMILY_MONTHS),
            "note": "GEM 是单一文献配置（Antonacci 2014），无因子挖掘；within-candidate N=2 "
                    "(6m,12m)。跨轮累计真 N（DSR）由户部组合级判据在拼装所有候选时累加，"
                    "本候选只如实吐自己的 N，不预先折算。",
        },
        "runs": runs,
        "benchmarks": _benchmarks(frames_by_symbol, base, P=P, start=common_start),
        "notes": [
            "NO-FIT（hard gate #2 clause #4）：lookback=12m/月度再平衡/单资产 100% 均为文献惯例"
            "（Antonacci 2014 Dual Momentum）冻结于结果之前 ⇒ 全样本曲线即 OOS 曲线，gate3 滚动"
            "为稳定性代理，不欠 walk-forward 重拟合。若任一参数是样本内选出的，豁免作废、须补真实分折 WF。",
            "Long-only，无做空，无杠杆；避险靠 risk-off 切 AGG，无 vol target/breaker/stop。",
            "反前视：权重 close(T) 决定、open(T+1) 执行、收益 open-to-open —— 与动量 sleeve 同一引擎、已单测。",
            "MDD≤20% 是全样本+每个危机窗的硬门，任一破位即直接负向，不被平均掉。",
            "数据源为免费日线 Yahoo 复权（split+dividend adj），非 OpenD —— 本轮按工部/首辅"
            "「免费日线(Stooq/Yahoo/FRED)」数据政策；与动量 sleeve 的 OpenD-only 政策不同，已在"
            "预注册 provenance 标注，后续可用 OpenD SPY 交叉校验。",
            "N_universe 冻结；未取到的符号是永久现金槽（数据缺口），绝不静默重新配权。",
        ],
    }
    return report
