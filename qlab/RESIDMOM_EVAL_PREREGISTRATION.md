# EVO-8 方向(b) — RESIDUAL MOMENTUM: FROZEN 预注册

**冻结于任何回测结果被读取之前**（工程 smoke 仅验证引擎可跑，未读 verdict 数字）。本文件在
结果 commit 之前提交，git 时序供户部/都察院核验预注册先于结果（工部 hard gate #1）。冻结后
下列任何数字不得更改；偏离即停并回报。

## 0. 判据零重实现 + 不自建门（工部 2026-07-29 接线口径）

- 唯一新建模代码：`swing/residmom_signals.py`（信号）+ `swing/run_residmom.py`（接线）。
- 信号引擎与 EVO-162 residual reversal **同一份**：`residmom_signals` 复用
  `residual_signals` 的 `_factor_returns/_ols_beta`，并把 sim/成本/杠杆/反前视循环逐行搬运，
  **唯一差异是横截面信号**（动量 `+mean(eps)` vs 反转 `−mean(eps)` + 形成窗+skip）。
- **判定 100% 交给 `research/gate.certify()`**（PR #1 `agent/agent/c33332b0`）：本 runner
  只产 OOS 净收益 + 预注册元数据 + 真实 N；官方/影子/DSR/成本/容量门全部在门里，不重实现。

## 1. 数据来源

- `data/daily_full` 复权日线（OpenD qfq / 免费日线口径，与 residual reversal 同源）。
- 冻结宇宙 = `RESIDUAL_UNIVERSE_RESOLVED.txt`（EVO-162 已冻结的大盘清单，跑中不换）。
- 3 因子回归 ETF：`SPY(MKT) / IWM,SPY(SMB) / IVE,IVW(HML)`，只作回归量、不交易。
- `TrdEnv.SIMULATE`：纯行情、零真金、代码无下单/入金路径。

## 2. 候选：残差动量（Blitz–Huij–Martens 2011, *Residual Momentum*）

- **信号（no-fit，文献惯例冻结在前）**：周频。每周 k：
    * 估计窗 **E=156 周**（3yr）OLS `r_i ~ 1+MKT+SMB+HML`，窗口以 **k−skip 结尾**（≤ 决策周，无未来）。
    * 形成窗 **F=52 周**（12M）残差、**skip=4 周**跳最近 1M；`signal_i = +mean(eps over F)`。
    * 横截面 winsorize 1/99。
- **组合（§4，与反转同）**：十分位做多残差赢家 / 做空残差输家，等权，美元中性 + β 中性
  （净 |β^MKT|≤0.05，破则机械 rescale 空腿）。市场中性 long-short。
- **杠杆 overlay（§5，与反转同）**：base/cap gross 2.0×、floor 0.5×，10% 年化波动目标
  （trailing 26w），熔断 trailing 5d 回撤≥8%→0.5×。预注册杠杆上限 ≤2x，不可事后加。
- **执行/反前视**：权重 close(T) 决定、open(T+1) 执行、收益 open-to-open（单测）。
- **成本 x1/x2**：佣金+价差 10bps/side×cost_mult；借券 0.5%/yr（空腿）；融资 6.8%/yr
  （max(0,gross−1)·NAV）。**决策口径 = ×2**。

## 3. 声明的 family（haircut/稳健；主格预先固定）+ 诚实 N（工部规矩#1）

- family = `(F,cut) ∈ {(52,decile),(26,decile),(52,quintile),(26,quintile)}`，**主格 = (F=52, decile)**。
- **N 只从 `TrialLedger.cumulative_n()` 取**，绝不用 manifest 每轮值、不接受默认 0。本轮登记
  `n_trials_total = 4`（全 family，无隐藏挖矿），trial Sharpes 全量吐给 DSR 的 V。跨轮累计真 N
  由户部在共享台账维护——本 run 只登记自己的 family，不预折算、不交幸存者。

## 4. NO-FIT 豁免 / OOS

- lookback/skip/estimation/组合/杠杆全为 Blitz 2011 文献惯例，冻结在前 ⇒ 无全局参数拟合；
  per-stock betas 由构造即 OOS（窗口≤决策周）。**全样本 cost-after 净收益即 OOS 曲线**，
  单发 OOS 预算（`OOSBudget(max_evals=1)`）。若任一参数事后被证明样本内选出，豁免作废、补真实分折 WF。

## 5. 门槛（全部在 certify() 里，本文件不重实现）

- 官方 50/20（唯一 REPORT_5020）；影子上报 25/20（DECISION_POINT）；兜底 15/20（shadow_floor_pass）。
- 危机子窗 gate 自带 2008/2020/2022；样本没盖住 → `tail_incomplete`，不背书。残差动量因 E+F+skip
  的 warmup（~3yr），首次决策约 2009，**2008 窗预期 tail_incomplete**（如实标注，不背书）。
- DSR：N=`cumulative_n()`；成本 x1x2 早筛；容量门（大盘十分位书、研究 AUM 下非约束）。

## 6. verdict 三值不二值化（工部规矩#2）

- `REPORT_5020` → 即刻上报工部；`DECISION_POINT` → 带真实数字停下等 Kevin 拍验收线，不自行放行；
- `FAIL` → **先看 `verdict.metrics.shadow_floor_pass`**：为 True 记兜底带(15-20%) sleeve 候选、
  留档（含与库存相关性），**不当垃圾扔**（standalone 判负 ≠ sleeve 判负）；为 False 才 NEGATIVE。
- 全部回报 → 工部尚书（不直接外呼首辅/都察院）。

## 7. 冻结切分

- 数据窗 = 宇宙+因子共同可得（~2006→2026）；warmup E+F+skip 后首次决策约 2009。
- 宇宙冻结不换；未取到的符号=永久缺席横截面槽（数据缺口），不静默重配权；thin-book 周（每腿<20）标注。
