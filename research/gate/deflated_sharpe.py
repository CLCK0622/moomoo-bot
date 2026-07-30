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
    scale_warning: bool = False   # 疑似单位不一致（V 尺度 vs sr_per_period），见下
    scale_note: str = ""          # 打旗原因（哪一侧、往严还是往松），供都察院/产出侧定位


def deflated_sharpe_ratio(sr_per_period: float, n_obs: int, skew: float, kurt: float,
                          n_trials: int,
                          trial_sharpes: Optional[Sequence[float]] = None,
                          trials_variance: Optional[float] = None,
                          trials_periods_per_year: int = 1,
                          threshold: float = 0.95) -> DSRResult:
    """
    DSR 门。**单位契约**：sr_per_period 与试验 Sharpe（trial_sharpes / trials_variance）
    必须同为**每期**（非年化）口径——`expected_max = √V · term` 里的 V 是每期 Sharpe 的方差。
    若产出侧把试验 Sharpe 算成**年化**（×√ppy），拿年化 V 去比每期 sr，会把基准抬高 √ppy≈15.9 倍，
    **系统性误杀真 alpha**（假阴性）。这是与「缺失≠放松」相反的方向，同样不能静默（工部 2026-07-29）。

    - `trials_periods_per_year`：声明试验 Sharpe 的年化尺度；>1 时这里**归一到每期**
      （每期 Var = 年化 Var / ppy；每期 Sharpe = 年化 Sharpe / √ppy）。默认 1 = 每期（契约）。
    - `scale_warning`：即便未声明，也做一道量级体检——每期 Sharpe 估计的抽样标准差 ~ 1/√n_obs，
      若 √V 远超此（>8×，疑似仍是年化），在结果上打旗（不阻断，交都察院/工部核 + 产出侧修）。
    n_trials 用跨轮累计真实试验数。返回 passed = DSR >= threshold。
    """
    ppy = max(int(trials_periods_per_year), 1)
    ts = None
    if trial_sharpes is not None:
        ts = [float(s) / math.sqrt(ppy) for s in trial_sharpes]
    tvar = (trials_variance / ppy) if trials_variance is not None else None
    v = _variance_of_trials(ts, tvar)

    # 单位体检（**双侧**，工部 2026-07-30）：每期 Sharpe 抽样标准差量级 ~ 1/√n_obs。
    #   上界：√V 远超 → 疑似年化未归一（V 偏大 → 门过严 → 误杀真 alpha / 假阴性）。
    #   下界：√V 远低于抽样噪声 → 试验 Sharpe 离散度比噪声还小一个量级，不可能，
    #         典型成因是**已是每期口径却又声明了 ppy**，V 被再除一次 → 门过松 → 假阳性。
    #         只有下界这一侧会放松门，必须打旗，不能静默。
    scale_warning = False
    scale_note = ""
    if v > 0 and n_obs > 1:
        sd, noise = math.sqrt(v), 1.0 / math.sqrt(n_obs)
        if sd > 8.0 * noise:
            scale_warning = True
            scale_note = ("√V 远超每期抽样噪声（%.3g vs %.3g）→ 疑似试验 Sharpe 仍是年化、"
                          "未声明 ppy 归一；门会过严（假阴性）。" % (sd, noise))
        elif sd < noise / 8.0:
            scale_warning = True
            scale_note = ("√V 远低于每期抽样噪声（%.3g vs %.3g）→ 疑似试验 Sharpe 已是每期口径"
                          "却又声明 trials_periods_per_year=%d，V 被重复归一；门会过松（假阳性）。"
                          % (sd, noise, ppy))

    sr0 = expected_max_sharpe(n_trials, v)
    psr0 = probabilistic_sharpe_ratio(sr_per_period, n_obs, skew, kurt, sr_benchmark=0.0)
    dsr = probabilistic_sharpe_ratio(sr_per_period, n_obs, skew, kurt, sr_benchmark=sr0)
    return DSRResult(
        sr_per_period=sr_per_period, n_obs=n_obs, n_trials=n_trials,
        expected_max_sr=sr0, psr_vs_zero=psr0, dsr=dsr,
        passed=(not np.isnan(dsr)) and dsr >= threshold,
        scale_warning=scale_warning, scale_note=scale_note,
    )


def bonferroni_haircut_alpha(base_alpha: float, n_trials: int) -> float:
    """DSR 拿不到 V 时的保守兜底：Bonferroni 单因子显著性门槛 α/N。"""
    return base_alpha / max(n_trials, 1)
