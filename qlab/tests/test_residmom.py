"""残差动量信号单测：做多残差赢家（与残差反转符号相反）+ 权重口径。"""
from __future__ import annotations
import numpy as np

from qlab.swing.residmom_signals import ResidMomParams, _rebalance_weights_mom
from qlab.swing import residual_signals as rr


def _synth(n_weeks=230, n_stocks=6, drift_weeks=56, seed=0):
    """3 因子非退化 + 特质噪声 + **近期特质漂移**（残差动量的信号必须在残差里，
    不能是被截距吸收的常数 alpha）。近 drift_weeks 周内 stock 0 正漂移、stock 5 负漂移。"""
    rng = np.random.RandomState(seed)
    t = np.arange(n_weeks)
    MKT = 0.010 * np.sin(t / 5.0)
    SMB = 0.008 * np.cos(t / 7.0)
    HML = 0.006 * np.sin(t / 11.0)
    F = np.column_stack([MKT, SMB, HML])
    betas = np.array([1.0, 0.8, 1.2, 0.9, 1.1, 1.0])
    eps = rng.normal(0.0, 0.004, (n_weeks, n_stocks))       # 特质噪声
    rec = slice(n_weeks - drift_weeks, n_weeks)
    eps[rec, 0] += 0.012                                    # 近期残差赢家
    eps[rec, 5] -= 0.012                                    # 近期残差输家
    wret = np.full((n_weeks, n_stocks), np.nan)
    for j in range(n_stocks):
        wret[:, j] = betas[j] * MKT + 0.5 * SMB + 0.3 * HML + eps[:, j]
    return wret, F


def test_momentum_longs_residual_winners():
    wret, F = _synth()
    reb_w, _ = _rebalance_weights_mom(wret, F, ResidMomParams(), None)
    assert reb_w, "no rebalance produced"
    k = max(reb_w)
    w = reb_w[k]
    # stock 0 (highest residual alpha) 应被做多；stock 5 (最低) 应被做空
    assert w[0] > 0, w
    assert w[5] < 0, w


def test_momentum_is_opposite_of_reversal():
    """同数据、同形成窗下，残差动量的持仓方向与残差反转相反。"""
    wret, F = _synth()
    p_mom = ResidMomParams(formation_weeks=8, skip_weeks=0, estimation_weeks=156, cut=0.10)
    reb_mom, _ = _rebalance_weights_mom(wret, F, p_mom, None)
    # 反转引擎（户部冻结）用 formation_weeks=8 同窗
    p_rev = rr.ResidualParams(formation_weeks=8, estimation_weeks=156, cut=0.10)
    reb_rev, _ = rr._rebalance_weights(wret, F, p_rev, None)
    k = max(set(reb_mom) & set(reb_rev))
    wm, wv = reb_mom[k], reb_rev[k]
    # 动量做多的那只（stock 0），反转应做空（符号相反）
    assert wm[0] > 0 and wv[0] < 0, (wm, wv)


def test_weights_dollar_and_gross_normalized():
    wret, F = _synth()
    reb_w, _ = _rebalance_weights_mom(wret, F, ResidMomParams(), None)
    w = reb_w[max(reb_w)]
    assert abs(np.abs(w).sum() - 2.0) < 1e-6      # gross ≡ gross_base 2.0
    assert w[w > 0].sum() > 0 and w[w < 0].sum() < 0


TESTS = [test_momentum_longs_residual_winners, test_momentum_is_opposite_of_reversal,
         test_weights_dollar_and_gross_normalized]

if __name__ == "__main__":
    n = 0
    for t in TESTS:
        t(); n += 1; print("PASS", t.__name__)
    print(f"{n}/{len(TESTS)} passed")
