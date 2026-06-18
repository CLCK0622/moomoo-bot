"""候选方向评估卡渲染 — 承接户部 EVO-12 v1.0 §7 模板, 覆盖 B/C/D/E 四块.

报告层只做**组装与门禁判定展示**: 所有指标与门禁结论已由 ``qlab.metrics`` /
``qlab.pipeline`` 算好, 这里把它们排成 v1.0 评估卡的结构化 Markdown + JSON。
"""

from __future__ import annotations

import json
import math
import os

from ..pipeline import EvaluationResult


def _json_safe(value):
    """Recursively coerce non-finite floats (inf/-inf/NaN) to ``None``.

    The card dict may carry ``float('inf')`` for ratios with zero denominator
    (e.g. profit_factor on a zero-loss candidate). Standard JSON has no token
    for these, and ``json.dump`` would emit non-standard ``Infinity``/``NaN``
    that strict downstream parsers reject. Markdown rendering keeps its ``∞``;
    only the JSON form is normalised here. ``null`` is the JSON-portable choice
    (an unbounded ratio is "undefined" to a strict consumer).
    """
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value

_DISCLAIMER = (
    "> ⚠️ 本评估卡仅用 fixture（合成/样例行情）验证**工程流程与指标计算口径**，"
    "对齐户部 [EVO-12] 回测口径与指标门禁 v1.0。所有数字均非真实行情，"
    "**不代表、也不声称任何策略达标**；门禁结论仅说明「这套计算与判定逻辑可运行」。"
)


def _pct(v: float | None) -> str:
    return "—" if v is None else f"{v * 100:.2f}%"


def _num(v: float | None, nd: int = 2) -> str:
    if v is None:
        return "—"
    if v == float("inf"):
        return "∞"
    return f"{v:,.{nd}f}"


def _ok(passed: bool, conclusive: bool = True) -> str:
    if not conclusive:
        return "⚠️ 数据不足"
    return "✅ 过" if passed else "❌ 不过"


def _gate_lines(verdict, ev: EvaluationResult) -> list[str]:
    lines: list[str] = []
    for g in verdict.gates:
        m = g.metrics
        if g.key == "gate1":
            detail = f"CAGR={_pct(m.get('cagr'))} MDD={_pct(m.get('mdd'))}"
        elif g.key == "gate2":
            worst = None
            for r in m.get("per_year", []):
                if r["complete"] and (worst is None or r["cagr"] < worst["cagr"]):
                    worst = r
            wt = f"最差完整年度={worst['year']}({_pct(worst['cagr'])})" if worst else "无完整年度"
            detail = f"合并年化={_pct(m.get('combined_cagr'))} 完整年度数={m.get('n_complete_years')} {wt}"
        elif g.key == "gate3":
            dist = m.get("annual_distribution", {})
            detail = (
                f"窗口数={m.get('n_windows')} 滚动年化中位={_pct(dist.get('median'))} "
                f"达标占比={_pct(m.get('hit_ratio'))} 负占比={_pct(m.get('negative_ratio'))} "
                f"滚动MDD max={_pct(m.get('rolling_mdd_max'))}"
            )
        elif g.key == "gate4":
            detail = (
                f"方式={m.get('method')} 样本外CAGR={_pct(m.get('oos_cagr'))} "
                f"MDD={_pct(m.get('oos_mdd'))} 相对衰减={_pct(m.get('degradation'))}"
            )
        else:
            detail = ""
        lines.append(f"- **{g.title}** {_ok(g.passed, g.conclusive)} — {detail}")
        if g.notes:
            lines.append(f"  - {g.notes}")
    return lines


def build_card_dict(ev: EvaluationResult) -> dict:
    """Structured JSON form of the card (B/C/D/E + meta)."""
    c = ev.core
    cfg = ev.config
    period = (
        [ev.result.equity_curve[0].ts, ev.result.equity_curve[-1].ts]
        if ev.result.equity_curve
        else [None, None]
    )
    years = (c.periods_per_year and len(ev.bars) / c.periods_per_year) or 0.0
    return {
        "meta": {
            "symbol": ev.symbol,
            "strategy": ev.strategy,
            "period": period,
            "n_bars": len(ev.bars),
            "approx_years": round(years, 2),
            "periods_per_year": c.periods_per_year,
            "initial_cash": ev.result.initial_cash,
            "rf_annual": c.rf_annual,
            "fixture_only": True,
        },
        "B_cost_registration": {
            "commission_rate": cfg.cost.commission_rate,
            "slippage_bps": cfg.cost.slippage_bps,
            "min_commission": cfg.cost.min_commission,
            "fill_rule": "信号在 bar 收盘产生, T+1 bar 开盘成交 (引擎结构强制, 无前视)",
            "untradeable_bar_rule": "零成交量/停牌 bar 由数据层过滤; 真实数据接入时补涨跌停顺延",
            "financing_cost": "占位 — 杠杆策略接真实数据时按 moomoo 融资利率逐日计提",
            "borrow_cost": "占位 — 做空策略接真实数据时按实际借券费率计提",
            "option_spread": "占位 — 期权方向按实际 bid-ask 50%-100% 计滑点",
            "cost_x2_pass": ev.cost_stress.stressed_pass,
            "cost_x2": {
                "base_cagr": ev.cost_stress.base_cagr,
                "stressed_cagr": ev.cost_stress.stressed_cagr,
                "base_mdd": ev.cost_stress.base_mdd,
                "stressed_mdd": ev.cost_stress.stressed_mdd,
            },
        },
        "C_core_metrics": c.to_dict(),
        "D_gates": {
            "holdout": ev.holdout.to_dict(),
            "walk_forward": ev.walk_forward.to_dict() if ev.walk_forward else None,
            "wf_meta": ev.wf_meta,
        },
        "E_bias_checklist": _bias_checklist(ev),
    }


def _bias_checklist(ev: EvaluationResult) -> list[dict]:
    years = (ev.core.periods_per_year and len(ev.bars) / ev.core.periods_per_year) or 0.0
    return [
        {"item": "幸存者偏差", "status": "占位", "note": "fixture 单标的; 真实标的池须含已退市/退榜标的"},
        {"item": "前视偏差", "status": "已控", "note": "引擎 T+1 开盘成交 + 模型 predict 逐 bar 因果"},
        {"item": "过拟合/数据窥探", "status": "占位", "note": "fixture 演示; 真实调参须登记次数与参数敏感性"},
        {"item": "多重检验", "status": "占位", "note": "横向筛选多个方向时须登记并做显著性校正"},
        {
            "item": "样本期",
            "status": "不足" if years < 5 else "满足",
            "note": f"fixture 约 {years:.1f} 年; v1.0 要求 ≥5 年且含一次完整牛熊",
        },
        {"item": "流动性", "status": "占位", "note": "fixture 合成成交量; 真实数据须设日均成交额门槛并配套容量"},
        {"item": "复权与数据质量", "status": "占位", "note": "真实数据须前复权且登记分红/拆股口径"},
    ]


def to_markdown(ev: EvaluationResult) -> str:
    c = ev.core
    d = c.drawdown
    cs = ev.cost_stress
    card = build_card_dict(ev)
    meta = card["meta"]
    lines = [
        f"# 候选方向评估卡 — {ev.symbol} / {ev.strategy}",
        "",
        _DISCLAIMER,
        "",
        "## A. 元信息与口径",
        f"- 区间 / bar 数: `{meta['period'][0]}` → `{meta['period'][1]}` / {meta['n_bars']} "
        f"(≈{meta['approx_years']} 年)",
        f"- 计价周期因子 P: {c.periods_per_year}（日频）；无风险利率 r_f: {_pct(c.rf_annual)}（取 0 已声明）",
        f"- 初始资金: {_num(ev.result.initial_cash)}；一笔交易 = 同方向持仓 0→0 的完整round trip",
        "",
        "## B. 成本登记（v1.0 §4，成本后口径）",
        f"- 手续费率: {_pct(ev.config.cost.commission_rate)} / 笔(notional)；"
        f"滑点: {ev.config.cost.slippage_bps:.1f} bps（单边，引擎已折进成交价）",
        "- 成交规则: 信号 bar 收盘产生，**T+1 bar 开盘成交**（引擎结构强制，无前视）",
        "- 不可成交 bar: 零成交量/停牌由数据层过滤；涨跌停顺延待真实数据接入补全",
        "- 融资/借券/期权价差: 占位（接真实数据按 moomoo 实际费率计提）",
        f"- **成本×2 压力测试**: {_ok(cs.stressed_pass)} — "
        f"基准 CAGR {_pct(cs.base_cagr)}→翻倍后 {_pct(cs.stressed_cagr)}，"
        f"MDD {_pct(cs.base_mdd)}→{_pct(cs.stressed_mdd)}",
        "",
        "## C. 成本后核心指标（v1.0 §2）",
        "| 指标 | 值 |",
        "| --- | --- |",
        f"| 几何 CAGR | {_pct(c.cagr)} |",
        f"| 逐 bar 最大回撤 | {_pct(c.max_drawdown)} |",
        f"| 最长水下时长 / 中位 | {d.longest_underwater_bars} / {_num(d.median_underwater_bars,0)} bar |",
        f"| 期末未恢复回撤 | {'是，已持续 ' + str(d.unrecovered_bars) + ' bar' if d.has_unrecovered else '否'} |",
        f"| 年化波动 | {_pct(c.annualized_volatility)} |",
        f"| Sharpe（未做自相关修正） | {_num(c.sharpe)} |",
        f"| Sortino（MAR={_pct(c.mar_annual)}） | {_num(c.sortino)} |",
        f"| 胜率 | {_pct(c.win_rate)}（{c.n_closed_trades} 笔平仓） |",
        f"| 盈亏比 / 盈利因子 | {_num(c.profit_loss_ratio)} / {_num(c.profit_factor)} |",
        f"| 单笔期望 | {_num(c.expectancy)} |",
        f"| 年化换手 | {_num(c.annualized_turnover)}x |",
        f"| 容量估算（参与度 {_pct(c.capacity_participation)}） | "
        f"{_num(c.capacity_estimate) if c.capacity_estimate is not None else '—'} |",
        f"| 成本: 佣金 / 滑点 | {_num(c.total_commission)} / {_num(c.total_slippage)} |",
        "",
        "## D. 门禁四关（v1.0 §3）",
        f"**综合判定（70/30 hold-out）: {ev.holdout.verdict}**"
        + (f"（卡点: {', '.join(ev.holdout.blocking)}）" if ev.holdout.blocking else ""),
        "",
    ]
    lines += _gate_lines(ev.holdout, ev)
    if ev.walk_forward is not None:
        lines += [
            "",
            f"**Walk-Forward 主口径（拼接样本外曲线，gate1-3）: {ev.walk_forward.verdict}**"
            + (f"（卡点: {', '.join(ev.walk_forward.blocking)}）" if ev.walk_forward.blocking else ""),
            f"- 折数={ev.wf_meta['n_folds']} 训练窗={ev.wf_meta['train_bars']} "
            f"测试窗={ev.wf_meta['test_bars']} 样本外 bar 数={ev.wf_meta['oos_bars']}",
        ]
        lines += _gate_lines(ev.walk_forward, ev)
    else:
        lines.append("\n_Walk-Forward 主口径未运行（仅静态策略；模型方向请用 `--walk-forward`）。_")

    lines += ["", "## E. 偏差自查（v1.0 §5）", ""]
    for row in card["E_bias_checklist"]:
        mark = {"已控": "✅", "满足": "✅", "不足": "⚠️", "占位": "⬜"}.get(row["status"], "⬜")
        lines.append(f"- {mark} **{row['item']}**（{row['status']}）— {row['note']}")

    lines += [
        "",
        "## F. 结论与风险",
        f"- 工程判定: 指标计算与四关门禁链路在 fixture 上完整运行；综合门禁结论 = **{ev.holdout.verdict}**。",
        "- 置信度: 不适用——这是工程/口径验证，非真实策略评估。",
        "- 待补: 真实行情、≥5 年含牛熊样本、融资/借券/期权成本实测、偏差清单逐项落实。",
        "",
    ]
    return "\n".join(lines)


def write_card(ev: EvaluationResult, out_dir: str, *, basename: str | None = None) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    base = basename or f"{ev.symbol}_{ev.strategy}_card"
    md_path = os.path.join(out_dir, f"{base}.md")
    json_path = os.path.join(out_dir, f"{base}.json")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(to_markdown(ev))
    with open(json_path, "w", encoding="utf-8") as fh:
        # Normalise inf/NaN to null in the dict, then force allow_nan=False so any
        # non-finite value that slipped through surfaces as an error instead of
        # silently writing invalid JSON.
        json.dump(
            _json_safe(build_card_dict(ev)),
            fh,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
    return {"markdown": md_path, "json": json_path}
