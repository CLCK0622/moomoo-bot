"""
deflated_sharpe.py —— 多重检验 haircut：PSR / DSR（Bailey & López de Prado 2014）

这是「机器批量挖因子」最关键的门：naive 最优因子的样本内 Sharpe 在 N 很大时几乎必然是噪声。
DSR 把基准从 0 换成「N 次独立试验下期望的最大 Sharpe」，N 用**跨轮累计真实试验数**。

口径：
- 所有 Sharpe 均为**每期**（非年化）口径，且与试验方差 V 同频率。
- n  = 观测数（如日频交易日数）
- N  = 跨轮累计独立试验数（来自 trial_ledger）
- V  = 各试验 Sharpe 的方差（有全量试验 SR 列表就直接算；没有则须显式传入）
- skew/kurt = 收益序列的偏度/非超额峰度（正态=3）

参考公式：
  PSR(SR*) = Φ[ ((SR - SR*)·√(n-1)) / √(1 - skew·SR + ((kurt-1)/4)·SR²) ]
  期望最大 SR0 = √V · [ (1-γ)·Z⁻¹(1 - 1/N) + γ·Z⁻¹(1 - 1/(N·e)) ]
  DSR = PSR(SR0)
其中 γ = Euler–Mascheroni ≈ 0.5772156649, Z⁻¹ = 标准正态分位, e = exp(1)。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np
from scipy.stats import norm

EULER_MASCHERONI = 0.5772156649015329


def probabilistic_sharpe_ratio(sr: float, n: int, skew: float, kurt: float,
                               sr_benchmark: float = 0.0) -> float:
    """PSR：真实 Sharpe 超过基准 sr_benchmark 的概率。sr / sr_benchmark 均为每期口径。"""
    if n < 2 or np.isnan(sr):
        return float("nan")
    denom = 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr * sr
    if denom <= 0:  # 分母非正 → 分布假设崩，保守返回 0
        return 0.0
    z = (sr - sr_benchmark) * math.sqrt(n - 1) / math.sqrt(denom)
    return float(norm.cdf(z))


def expected_max_sharpe(n_trials: int, trials_variance: float) -> float:
    """N 次独立试验（真实 SR=0）下期望的最大 Sharpe（每期口径）。"""
    if n_trials < 1:
        return 0.0
    if n_trials == 1:
        return 0.0  # 单次试验无选择偏差
    v = max(trials_variance, 0.0)
    if v == 0:
        return 0.0
    g = EULER_MASCHERONI
    term = (1.0 - g) * norm.ppf(1.0 - 1.0 / n_trials) + \
        g * norm.ppf(1.0 - 1.0 / (n_trials * math.e))
    return math.sqrt(v) * term


def _variance_of_trials(trial_sharpes: Optional[Sequence[float]],
                        trials_variance: Optional[float]) -> float:
    if trials_variance is not None:
        return float(trials_variance)
    if trial_sharpes is not None and len(trial_sharpes) >= 2:
        return float(np.var(np.asarray(trial_sharpes, dtype=float), ddof=1))
    raise ValueError(
        "DSR 需要试验 Sharpe 的方差 V：请传 trials_variance 或至少 2 个 trial_sharpes。"
        "（机器批量挖因子必须吐全量试验 SR，否则无法做多重检验校正——不予评估。）"
    )


@dataclass
class DSRResult:
    sr_per_period: float
    n_obs: int
    n_trials: int
    expected_max_sr: float   # 选择偏差基准 SR0
    psr_vs_zero: float       # 不做多重检验时的 PSR（对照用）
    dsr: float               # 真正判据
    passed: bool


def deflated_sharpe_ratio(sr_per_period: float, n_obs: int, skew: float, kurt: float,
                          n_trials: int,
                          trial_sharpes: Optional[Sequence[float]] = None,
                          trials_variance: Optional[float] = None,
                          threshold: float = 0.95) -> DSRResult:
    """
    DSR 门。sr_per_period 为**每期**（非年化）Sharpe。
    n_trials 用跨轮累计真实试验数。返回 passed = DSR >= threshold。
    """
    v = _variance_of_trials(trial_sharpes, trials_variance)
    sr0 = expected_max_sharpe(n_trials, v)
    psr0 = probabilistic_sharpe_ratio(sr_per_period, n_obs, skew, kurt, sr_benchmark=0.0)
    dsr = probabilistic_sharpe_ratio(sr_per_period, n_obs, skew, kurt, sr_benchmark=sr0)
    return DSRResult(
        sr_per_period=sr_per_period, n_obs=n_obs, n_trials=n_trials,
        expected_max_sr=sr0, psr_vs_zero=psr0, dsr=dsr,
        passed=(not np.isnan(dsr)) and dsr >= threshold,
    )


def bonferroni_haircut_alpha(base_alpha: float, n_trials: int) -> float:
    """DSR 拿不到 V 时的保守兜底：Bonferroni 单因子显著性门槛 α/N。"""
    return base_alpha / max(n_trials, 1)
