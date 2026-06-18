"""Report generation.

Renders :class:`PerformanceMetrics` into a markdown report and a JSON sidecar,
both keyed to 户部口径 field names. Every report carries an explicit fixture
disclaimer so engineering validation is never mistaken for a performance claim.
"""

from __future__ import annotations

import json
import os

from ..backtest.engine import BacktestResult
from .metrics import PerformanceMetrics, compute_metrics

_DISCLAIMER = (
    "> ⚠️ 本报告仅用于验证工程流程（fixture 数据）。所有指标均来自合成/样例行情，"
    "**不代表任何真实策略表现，也不构成收益承诺或投资建议**。"
)


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _money(value: float) -> str:
    return f"{value:,.2f}"


class ReportGenerator:
    def __init__(self, trading_days: int = 252) -> None:
        self.trading_days = trading_days

    def build(self, result: BacktestResult) -> PerformanceMetrics:
        return compute_metrics(result, self.trading_days)

    def to_markdown(self, result: BacktestResult, metrics: PerformanceMetrics | None = None) -> str:
        m = metrics or self.build(result)
        lines = [
            f"# 回测报告 — {result.symbol} / {result.strategy}",
            "",
            _DISCLAIMER,
            "",
            f"- 区间: `{m.period_start}` → `{m.period_end}` （{m.n_bars} bars）",
            f"- 初始资金: {_money(result.initial_cash)}",
            f"- 期末权益: {_money(result.final_equity)}",
            "",
            "## 核心指标（户部口径）",
            "",
            "| 指标 | 值 |",
            "| --- | --- |",
            f"| 累计收益 | {_pct(m.total_return)} |",
            f"| 年化收益 | {_pct(m.annualized_return)} |",
            f"| 年化波动 | {_pct(m.annualized_volatility)} |",
            f"| 夏普 | {m.sharpe:.2f} |",
            f"| 最大回撤 | {_pct(m.max_drawdown)} |",
            f"| 交易成本(佣金) | {_money(m.total_commission)} |",
            f"| 滑点成本 | {_money(m.total_slippage)} |",
            f"| 成交笔数 | {m.n_trades} |",
            f"| 换手率 | {m.turnover:.2f}x |",
            "",
            "## 分年度表现",
            "",
            "| 年度 | 收益 |",
            "| --- | --- |",
        ]
        for year, ret in m.yearly_returns.items():
            lines.append(f"| {year} | {_pct(ret)} |")

        lines += ["", "## 样本内 / 样本外", ""]
        if m.oos_period and m.in_sample and m.out_of_sample:
            lines += [
                f"- 样本内区间: `{m.oos_period['in_sample']}`",
                f"- 样本外区间: `{m.oos_period['out_of_sample']}`",
                "",
                "| 区间 | 累计收益 | 年化收益 | 最大回撤 |",
                "| --- | --- | --- | --- |",
                "| 样本内 | "
                f"{_pct(m.in_sample['total_return'])} | "
                f"{_pct(m.in_sample['annualized_return'])} | "
                f"{_pct(m.in_sample['max_drawdown'])} |",
                "| 样本外 | "
                f"{_pct(m.out_of_sample['total_return'])} | "
                f"{_pct(m.out_of_sample['annualized_return'])} | "
                f"{_pct(m.out_of_sample['max_drawdown'])} |",
            ]
        else:
            lines.append("_样本外切分未启用（oos_fraction 不在 (0,1) 区间或数据过短）。_")

        lines.append("")
        return "\n".join(lines)

    def write(
        self,
        result: BacktestResult,
        out_dir: str,
        *,
        basename: str | None = None,
    ) -> dict:
        os.makedirs(out_dir, exist_ok=True)
        metrics = self.build(result)
        base = basename or f"{result.symbol}_{result.strategy}"
        md_path = os.path.join(out_dir, f"{base}.md")
        json_path = os.path.join(out_dir, f"{base}.json")
        with open(md_path, "w", encoding="utf-8") as fh:
            fh.write(self.to_markdown(result, metrics))
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(metrics.to_dict(), fh, ensure_ascii=False, indent=2, sort_keys=True)
        return {"markdown": md_path, "json": json_path}
