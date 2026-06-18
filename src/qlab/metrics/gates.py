"""门禁四关 (户部 EVO-12 v1.0 §3) — 稳定性判定的核心.

硬指标是「年化收益稳定 ≥50%、最大回撤 ≤20%」，关键词是**稳定**：单期达标不算过。
四关全过 → `候选通过`；关1 过但 2/3/4 任一不过 → `稳定性不足，未过线`；关1 不过 →
`基线未达标`。每一关都返回导致结论的具体数字。

所有函数纯计算，输入对齐的 (timestamps, equity) 序列与阈值，便于单测。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from ..config import GateConfig
from .core import geometric_cagr, max_drawdown


@dataclass
class GateResult:
    key: str
    title: str
    passed: bool
    conclusive: bool = True  # False = 数据不足，无法判定 (不等于通过)
    metrics: dict = field(default_factory=dict)
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GateVerdict:
    verdict: str  # 候选通过 | 稳定性不足，未过线 | 基线未达标
    gates: list[GateResult] = field(default_factory=list)
    blocking: list[str] = field(default_factory=list)  # 卡在哪几关

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "blocking": self.blocking,
            "gates": [g.to_dict() for g in self.gates],
        }


def _percentiles(values: list[float]) -> dict:
    if not values:
        return {"min": None, "p25": None, "median": None, "p75": None, "max": None}
    s = sorted(values)

    def q(p: float) -> float:
        if len(s) == 1:
            return s[0]
        idx = p * (len(s) - 1)
        lo = int(idx)
        hi = min(lo + 1, len(s) - 1)
        frac = idx - lo
        return s[lo] + (s[hi] - s[lo]) * frac

    return {
        "min": s[0],
        "p25": q(0.25),
        "median": q(0.50),
        "p75": q(0.75),
        "max": s[-1],
    }


def gate1_baseline(equity: list[float], periods_per_year: int, cfg: GateConfig) -> GateResult:
    """关1 全样本基线: 成本后 CAGR ≥ 目标 且 MDD ≤ 上限."""
    cagr = geometric_cagr(equity, periods_per_year)
    mdd = max_drawdown(equity)
    passed = cagr >= cfg.target_cagr and mdd <= cfg.max_mdd
    return GateResult(
        key="gate1",
        title="全样本基线",
        passed=passed,
        metrics={"cagr": cagr, "mdd": mdd, "target_cagr": cfg.target_cagr, "max_mdd": cfg.max_mdd},
        notes="入场券，非合格证" if passed else "基线未达标",
    )


def _by_year(timestamps: list[str], equity: list[float]) -> list[tuple[str, list[float]]]:
    """Group the equity curve into calendar-year sub-curves.

    Each year's sub-curve is prefixed with the prior bar's equity so the year's
    return/MDD is continuous (no artificial reset at the year boundary).
    """
    groups: list[tuple[str, list[float]]] = []
    for i, ts in enumerate(timestamps):
        year = ts[:4]
        if not groups or groups[-1][0] != year:
            seed = [equity[i - 1]] if i > 0 else []
            groups.append((year, seed + [equity[i]]))
        else:
            groups[-1][1].append(equity[i])
    return groups


def gate2_yearly(
    timestamps: list[str], equity: list[float], periods_per_year: int, cfg: GateConfig
) -> GateResult:
    """关2 分年度一致性: 每个完整年度 CAGR ≥ 35%、无负年度、年内 MDD ≤ 20%."""
    groups = _by_year(timestamps, equity)
    full_threshold = 0.75 * periods_per_year  # 完整年度的最小 bar 数
    per_year = []
    failures = []
    for year, curve in groups:
        n_bars = len(curve) - 1  # 该年实现收益期数
        year_return = (curve[-1] / curve[0] - 1.0) if curve[0] else 0.0
        year_cagr = geometric_cagr(curve, periods_per_year)
        year_mdd = max_drawdown(curve)
        complete = n_bars >= full_threshold
        row = {
            "year": year,
            "complete": complete,
            "n_bars": n_bars,
            "return": year_return,
            "cagr": year_cagr,
            "mdd": year_mdd,
        }
        per_year.append(row)
        if complete:
            if year_cagr < cfg.yearly_min_cagr:
                failures.append(f"{year} CAGR {year_cagr:.1%}<{cfg.yearly_min_cagr:.0%}")
            if year_return < 0:
                failures.append(f"{year} 年度为负 {year_return:.1%}")
            if year_mdd > cfg.max_mdd:
                failures.append(f"{year} MDD {year_mdd:.1%}>{cfg.max_mdd:.0%}")

    full_cagr = geometric_cagr(equity, periods_per_year)
    if full_cagr < cfg.target_cagr:
        failures.append(f"合并几何年化 {full_cagr:.1%}<{cfg.target_cagr:.0%}")
    n_complete = sum(1 for r in per_year if r["complete"])
    conclusive = n_complete >= 1
    passed = conclusive and not failures
    return GateResult(
        key="gate2",
        title="分年度一致性",
        passed=passed,
        conclusive=conclusive,
        metrics={
            "per_year": per_year,
            "combined_cagr": full_cagr,
            "n_complete_years": n_complete,
        },
        notes=(
            "; ".join(failures)
            if failures
            else ("通过" if conclusive else "无完整年度，数据不足")
        ),
    )


def gate3_rolling(
    equity: list[float], periods_per_year: int, cfg: GateConfig
) -> GateResult:
    """关3 滚动窗口稳定性: 滚动 12 月年化中位数/达标占比/负占比/滚动 MDD 上限."""
    w = cfg.rolling_window_bars
    step = cfg.rolling_step_bars
    if len(equity) <= w:
        return GateResult(
            key="gate3",
            title="滚动窗口稳定性",
            passed=False,
            conclusive=False,
            metrics={"n_windows": 0, "window_bars": w},
            notes=f"样本不足一个滚动窗口 ({len(equity)}<={w})，数据不足",
        )
    annuals: list[float] = []
    mdds: list[float] = []
    starts = list(range(0, len(equity) - w, step))
    # Anchor a final window ending at the last bar so a non-step-aligned tail
    # (the trailing <step bars) is not silently dropped from the distribution.
    last_start = len(equity) - 1 - w
    if not starts or starts[-1] != last_start:
        starts.append(last_start)
    for start in starts:
        window = equity[start : start + w + 1]
        annuals.append(geometric_cagr(window, periods_per_year))
        mdds.append(max_drawdown(window))
    n = len(annuals)
    hit_ratio = sum(1 for a in annuals if a >= cfg.target_cagr) / n
    neg_ratio = sum(1 for a in annuals if a < 0) / n
    median = _percentiles(annuals)["median"]
    max_mdd = max(mdds)
    failures = []
    if median < cfg.rolling_median_min:
        failures.append(f"滚动年化中位数 {median:.1%}<{cfg.rolling_median_min:.0%}")
    if hit_ratio < cfg.rolling_hit_ratio_min:
        failures.append(f"达标窗口占比 {hit_ratio:.0%}<{cfg.rolling_hit_ratio_min:.0%}")
    if neg_ratio > cfg.rolling_negative_max:
        failures.append(f"负年化窗口占比 {neg_ratio:.0%}>{cfg.rolling_negative_max:.0%}")
    if max_mdd > cfg.max_mdd:
        failures.append(f"滚动 MDD 上限 {max_mdd:.1%}>{cfg.max_mdd:.0%}")
    passed = not failures
    return GateResult(
        key="gate3",
        title="滚动窗口稳定性",
        passed=passed,
        metrics={
            "n_windows": n,
            "window_bars": w,
            "step_bars": step,
            "annual_distribution": _percentiles(annuals),
            "hit_ratio": hit_ratio,
            "negative_ratio": neg_ratio,
            "rolling_mdd_max": max_mdd,
        },
        notes="; ".join(failures) if failures else "通过",
    )


def gate4_holdout(
    timestamps: list[str],
    equity: list[float],
    oos_start_ts: str | None,
    periods_per_year: int,
    cfg: GateConfig,
) -> GateResult:
    """关4 简单留出: 样本外段满足关1，且相对样本内衰减 ≤ 30% (过拟合信号)."""
    if not oos_start_ts:
        return GateResult(
            key="gate4",
            title="样本外/Walk-Forward",
            passed=False,
            conclusive=False,
            metrics={},
            notes="未设置样本外切分，数据不足",
        )
    split = next((i for i, ts in enumerate(timestamps) if ts >= oos_start_ts), None)
    if split is None or not (0 < split < len(equity) - 1):
        return GateResult(
            key="gate4",
            title="样本外/Walk-Forward",
            passed=False,
            conclusive=False,
            metrics={},
            notes="样本外切分点无效，数据不足",
        )
    is_curve = equity[: split + 1]
    oos_curve = equity[split:]
    is_cagr = geometric_cagr(is_curve, periods_per_year)
    oos_cagr = geometric_cagr(oos_curve, periods_per_year)
    oos_mdd = max_drawdown(oos_curve)
    degradation = ((is_cagr - oos_cagr) / is_cagr) if is_cagr > 0 else None
    failures = []
    if oos_cagr < cfg.target_cagr:
        failures.append(f"样本外 CAGR {oos_cagr:.1%}<{cfg.target_cagr:.0%}")
    if oos_mdd > cfg.max_mdd:
        failures.append(f"样本外 MDD {oos_mdd:.1%}>{cfg.max_mdd:.0%}")
    if degradation is not None and degradation > cfg.oos_degradation_max:
        failures.append(f"相对衰减 {degradation:.0%}>{cfg.oos_degradation_max:.0%} (过拟合信号)")
    passed = not failures
    return GateResult(
        key="gate4",
        title="样本外/Walk-Forward (Hold-out)",
        passed=passed,
        metrics={
            "method": "hold-out",
            "is_cagr": is_cagr,
            "oos_cagr": oos_cagr,
            "oos_mdd": oos_mdd,
            "degradation": degradation,
            "split_ts": timestamps[split],
        },
        notes="; ".join(failures) if failures else "通过",
    )


def decide_verdict(gates: list[GateResult]) -> GateVerdict:
    """门禁判定汇总规则 (v1.0 §3)."""
    by_key = {g.key: g for g in gates}
    gate1 = by_key.get("gate1")
    blocking = [g.key for g in gates if not g.passed]
    if gate1 is not None and not gate1.passed:
        verdict = "基线未达标"
    elif blocking:
        verdict = "稳定性不足，未过线"
    else:
        verdict = "候选通过"
    return GateVerdict(verdict=verdict, gates=gates, blocking=blocking)


def evaluate_gates(
    timestamps: list[str],
    equity: list[float],
    periods_per_year: int,
    cfg: GateConfig,
    oos_start_ts: str | None = None,
    include_holdout: bool = True,
) -> GateVerdict:
    """Run the gates on a single equity curve and return the combined verdict.

    - Raw full-sample curve: ``include_holdout=True`` (default) runs all four gates,
      with gate 4 as the 70/30 hold-out using ``oos_start_ts``.
    - Stitched Walk-Forward OOS curve: pass ``include_holdout=False`` — the WF curve
      *is* the out-of-sample, so only gates 1-3 apply to it (gate 4 主口径).
    """
    gates = [
        gate1_baseline(equity, periods_per_year, cfg),
        gate2_yearly(timestamps, equity, periods_per_year, cfg),
        gate3_rolling(equity, periods_per_year, cfg),
    ]
    if include_holdout:
        gates.append(gate4_holdout(timestamps, equity, oos_start_ts, periods_per_year, cfg))
    return decide_verdict(gates)
