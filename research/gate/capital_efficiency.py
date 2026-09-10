"""
capital_efficiency.py —— 事件/稀疏腿的「资金效率 / 收益轴」口径（户部，吏部 07-30 EVO-8(i)）

**问题（B FOMC 暴露的假阴性形态）**：门的收益轴默认全额资金。事件类腿只在事件窗口在险、其余时间
是现金，全额资金 CAGR 被现金天稀释 → 明明有 edge 也被误杀（连 Sharpe 都被拖 ~√f：现金天把
mean 拉向 0）。这是与「缺失≠放松 / 单位不一致」相反方向的 fail-open——**结构性假阴性**。

**口径**：事件类候选按**在险资金（deployed / active）判 edge**，不按全额资金 CAGR 判。
- **预注册冻结暴露定义**（哪些期在险 / 平均暴露比例 f / 杠杆上限），进 prereg 冻结哈希；
- 跑后由**实际持仓序列**核验 `f_realized ≈ f_prereg`（不符即拒）——防事后挑小 f 抬高 deployed
  收益，与 ppy-频率、family-规模、成本地板 同一类反 fail-open（自报旋钮须对权威来源可核）；
- **edge 判据**：active 期 edge 显著为正 + 扛过成本 x1x2 + 过 DSR 多重检验 haircut（用 active 期
  Sharpe、非现金稀释序列）——三关全过才算「edge 可捕获」。
- **MDD 双报**：全额资金 MDD（稀疏腿本就小）+ active 期 MDD（防 active 期大回撤被现金掩盖）。

口径与冻结门一致：Sharpe/MDD 走 research.gate.metrics；DSR 走 deflated_sharpe。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence

import numpy as np
import pandas as pd

from .deflated_sharpe import deflated_sharpe_ratio
from .metrics import PERIODS_PER_YEAR, max_drawdown, sharpe


@dataclass
class EventExposureSpec:
    """**可预注册冻结**的暴露定义（放进 prereg_config['event_exposure']，由冻结哈希守住）。"""
    active_rule: str            # 人读的在险规则，如 "FOMC 会议前 3 个交易日"（冻结、可审计）
    expected_fraction: float    # 预注册的平均暴露比例 f（0<f<=leverage_cap），跑后须与实测相符
    leverage_cap: float = 2.0   # 在险时的杠杆上限（≤2x 预注册，不可事后加）
    tol: float = 0.25           # f 实测 vs 预注册的相对容差（|实测-预注册|/预注册）


def realized_exposure_fraction(exposure: Sequence[float]) -> float:
    """实测平均暴露比例 = 平均绝对暴露（1.0=平均满仓 1x；稀疏腿 <<1）。"""
    e = np.abs(np.asarray(exposure, dtype=float))
    return float(e.mean()) if len(e) else 0.0


@dataclass
class ExposureCheck:
    ok: bool
    realized_fraction: float
    max_abs_exposure: float
    reason: str = ""


def verify_exposure(exposure: Sequence[float], spec: EventExposureSpec) -> ExposureCheck:
    """核验实测暴露与预注册一致：f 在容差内、杠杆不超上限。不符 → ok=False（调用方据此拒）。"""
    e = np.abs(np.asarray(exposure, dtype=float))
    f = realized_exposure_fraction(e)
    mx = float(e.max()) if len(e) else 0.0
    if spec.expected_fraction <= 0:
        return ExposureCheck(False, f, mx, "预注册 expected_fraction 须 >0")
    if mx > spec.leverage_cap + 1e-9:
        return ExposureCheck(False, f, mx,
                             f"在险杠杆 {mx:.2f} 超预注册上限 {spec.leverage_cap:.2f}")
    rel = abs(f - spec.expected_fraction) / spec.expected_fraction
    if rel > spec.tol:
        return ExposureCheck(False, f, mx,
                             f"实测暴露 f={f:.4f} 与预注册 {spec.expected_fraction:.4f} 相对差 "
                             f"{rel:.0%}>容差{spec.tol:.0%}（防事后挑小 f 抬高 deployed 收益）")
    return ExposureCheck(True, f, mx, "暴露与预注册一致")


@dataclass
class CapEffReport:
    n_obs: int
    n_active: int
    realized_fraction: float
    # 全额资金（被现金稀释，仅作对照，勿据此判 edge）
    full_mdd: float
    full_ann_return: float
    full_sharpe_ann: float          # 全额资金 Sharpe（被现金拖 ~√f，故 < active edge Sharpe）
    # 在险 / deployed（edge 轴，判据看这个）
    edge_per_active: float          # active 期均值收益（每次事件的 edge）
    active_sharpe_ann: float        # active 期 Sharpe（去现金拖累，annualize 用 active 频率）
    active_mdd: float               # active 期序列的 MDD（防大回撤被现金掩盖）
    deployed_ann_return: float      # 指示性：把 edge 按 active 频率年化（非现金稀释）
    exposure: ExposureCheck
    dsr: Optional[Dict[str, Any]] = None
    edge_confirmed: bool = False    # edge 正 + 扛 x2 成本 + 过 DSR + 暴露核验通过

    def as_dict(self) -> dict:
        d = self.__dict__.copy()
        d["exposure"] = self.exposure.__dict__
        return d


def capital_efficiency_report(
        returns: Sequence[float], exposure: Sequence[float], spec: EventExposureSpec,
        dates: Optional[Sequence] = None, n_trials: int = 1,
        trials_variance: Optional[float] = None,
        trial_sharpes: Optional[Sequence[float]] = None,
        cost_per_active_x1: float = 0.0, periods_per_year: int = PERIODS_PER_YEAR,
        dsr_threshold: float = 0.95) -> CapEffReport:
    """
    事件类候选的资金效率报告 + edge 判据。
    - returns：全额资金每期净收益（cash 天≈0）。exposure：同长度的每期（有符号）暴露。
    - cost_per_active_x1：每个 active 期的单边成本（比例）；judged 用 x2（保守）扣在 active edge 上。
    - DSR 用 **active 期 Sharpe** + 跨轮累计 N（多重检验校在 edge 上，非现金稀释序列）。
    """
    r = np.asarray(returns, dtype=float)
    e = np.abs(np.asarray(exposure, dtype=float))
    n = len(r)
    active = e > 1e-12
    ra = r[active]
    n_active = int(active.sum())
    xchk = verify_exposure(exposure, spec)

    rs = pd.Series(r)
    full_mdd = max_drawdown(rs)
    full_ann = (np.prod(1.0 + r) ** (periods_per_year / n) - 1.0) if n > 0 else float("nan")
    full_sharpe = sharpe(rs, periods_per_year=periods_per_year, annualized=True)

    if n_active >= 2:
        edge = float(ra.mean())
        sd = float(ra.std(ddof=1))
        # active 频率年化：一年里有多少个 active 期
        years = ((pd.to_datetime(pd.Index(dates))[-1] - pd.to_datetime(pd.Index(dates))[0]).days
                 / 365.25) if dates is not None else (n / periods_per_year)
        active_ppy = (n_active / years) if years and years > 0 else n_active
        active_sharpe = (edge / sd * np.sqrt(active_ppy)) if sd > 0 else float("nan")
        active_mdd = max_drawdown(pd.Series(ra))
        # 扣 x2 成本后的 active edge（保守），DSR 用其 per-period Sharpe
        edge_net_x2 = edge - 2.0 * cost_per_active_x1
        sr_pp_net = (edge_net_x2 / sd) if sd > 0 else float("nan")
        deployed_ann = edge_net_x2 * active_ppy   # 指示性年化（算术、非复利）
    else:
        edge = sd = active_sharpe = active_mdd = edge_net_x2 = sr_pp_net = deployed_ann = float("nan")
        active_ppy = 0.0

    dsr_d = None
    edge_confirmed = False
    if xchk.ok and n_active >= 2 and not np.isnan(sr_pp_net) and edge_net_x2 > 0:
        try:
            dres = deflated_sharpe_ratio(
                sr_pp_net, n_active, float(pd.Series(ra).skew()),
                float(pd.Series(ra).kurt()) + 3.0, n_trials=n_trials,
                trial_sharpes=trial_sharpes, trials_variance=trials_variance,
                threshold=dsr_threshold)
            dsr_d = dres.__dict__
            edge_confirmed = bool(dres.passed)
        except ValueError as ex:
            dsr_d = {"error": str(ex)}

    return CapEffReport(
        n_obs=n, n_active=n_active, realized_fraction=xchk.realized_fraction,
        full_mdd=full_mdd, full_ann_return=full_ann, full_sharpe_ann=full_sharpe,
        edge_per_active=edge, active_sharpe_ann=active_sharpe, active_mdd=active_mdd,
        deployed_ann_return=deployed_ann, exposure=xchk, dsr=dsr_d,
        edge_confirmed=edge_confirmed)
