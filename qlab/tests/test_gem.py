"""GEM 信号/曲线单测：双动量选择规则 + 曲线口径 + 判据接线。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from qlab.swing.gem_signals import GemParams, gem_curve
from qlab.swing.gem_evaluate import build_gem_report


def _frame(dates, closes):
    closes = np.asarray(closes, float)
    return pd.DataFrame({"date": dates, "open": closes, "high": closes,
                         "low": closes, "close": closes, "volume": 1.0})


def _series(n, daily):
    """从日收益率复利出收盘价路径（起点 100）。"""
    return 100.0 * np.cumprod(1.0 + np.full(n, daily))


def _make(dates, spy, veu, agg, bil):
    return {"SPY": _frame(dates, spy), "VEU": _frame(dates, veu),
            "AGG": _frame(dates, agg), "BIL": _frame(dates, bil)}


# 序列要长于回看 (252 交易日) + 足够部署期；前 ~252 期是无信号的现金 warm-up，
# 故断言用「已部署期内的选择」而非含 warm-up 的绝对占比。
N = 700
DATES = pd.bdate_range("2013-01-01", periods=N)


def test_riskon_us_wins_holds_spy():
    # SPY 强上行 > BIL 且 > VEU ⇒ 部署期应几乎全持 SPY（VEU/AGG≈0）
    frames = _make(DATES, _series(N, 0.0005), _series(N, 0.0), _series(N, 0.0), _series(N, 0.00005))
    af = gem_curve(frames, GemParams(), cost_mult=1.0)["diagnostics"]["alloc_frac"]
    assert af["SPY"] > 0.3 and af["SPY"] == max(af.values()), af
    assert af["VEU"] < 0.02 and af["AGG"] < 0.02, af


def test_riskoff_holds_agg():
    # 所有风险资产下行（US 动量 < T-bill）⇒ 避险切 AGG，SPY/VEU≈0
    frames = _make(DATES, _series(N, -0.0005), _series(N, -0.0004), _series(N, 0.00005), _series(N, 0.00005))
    af = gem_curve(frames, GemParams(), cost_mult=1.0)["diagnostics"]["alloc_frac"]
    assert af["AGG"] > 0.3 and af["AGG"] == max(af.values()), af
    assert af["SPY"] < 0.02 and af["VEU"] < 0.02, af


def test_relative_momentum_picks_intl():
    # US、ex-US 都正且 > T-bill，但 ex-US 动量更高 ⇒ 相对动量选 VEU，SPY≈0
    frames = _make(DATES, _series(N, 0.0002), _series(N, 0.0006), _series(N, 0.0), _series(N, 0.00005))
    af = gem_curve(frames, GemParams(), cost_mult=1.0)["diagnostics"]["alloc_frac"]
    assert af["VEU"] > af["SPY"] and af["VEU"] > 0.3, af
    assert af["SPY"] < 0.02, af


def test_curve_columns_and_gate_wiring():
    frames = _make(DATES, _series(N, 0.0004), _series(N, 0.0001), _series(N, 0.00005), _series(N, 0.00005))
    res = gem_curve(frames, GemParams(), cost_mult=2.0)
    eq = res["equity_df"]
    assert list(eq.columns) == ["date", "ret", "equity", "traded_notional"]
    assert len(eq) > 100 and eq["equity"].iloc[-1] > 0
    # verdict 接线跑通、含官方门与影子层字段
    rep = build_gem_report(frames, n_boot=200)
    assert "official_gate_5020" in rep and "shadow_layers" in rep
    assert rep["primary_lookback_months"] == 12
    assert rep["honest_trial_count"]["within_candidate_N"] == 2


def test_cost_reduces_return():
    # ×2 成本下的净值应 ≤ ×1（换手带来的成本更高）
    frames = _make(DATES, _series(N, 0.0004), _series(N, 0.0003), _series(N, 0.0001), _series(N, 0.00005))
    e1 = gem_curve(frames, GemParams(), cost_mult=1.0)["equity_df"]["equity"].iloc[-1]
    e2 = gem_curve(frames, GemParams(), cost_mult=2.0)["equity_df"]["equity"].iloc[-1]
    assert e2 <= e1 + 1e-9


TESTS = [test_riskon_us_wins_holds_spy, test_riskoff_holds_agg,
         test_relative_momentum_picks_intl, test_curve_columns_and_gate_wiring,
         test_cost_reduces_return]


if __name__ == "__main__":
    passed = 0
    for t in TESTS:
        t(); passed += 1; print("PASS", t.__name__)
    print(f"{passed}/{len(TESTS)} passed")
