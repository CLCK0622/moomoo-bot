# EVO-8 方向(b) candidate — GEM (Global Equity Momentum): FROZEN 预注册

**冻结于任何回测结果被读取之前。** 本文件在结果 commit *之前* 提交到分支；git
时间戳/hash 顺序供户部/都察院核验「预注册先于结果」（工部尚书 2026-07-24 (b)#2，
hard gate #1）。冻结后下列任何数字不得更改；任何偏离即停并回报，绝不静默重调。

一个候选、一个主格（primary cell）、一个显式声明的 family（多重检验 haircut）。
复用判据栈为 EVO-149/EVO-130 模块，逐字节复用；唯一新建模代码是 GEM 信号适配
（`swing/gem_signals.py`）及其 verdict 接线（`swing/gem_evaluate.py`）。

---

## 0. 复用清单（hard gate #2 — 不重实现）

| 逐字复用（零改动） | 作用 |
|--|--|
| `qlab/events/gates.py` | EVO-12 门 1–3 + `three_gate_verdict`（CAGR≥50%、MDD≤20%） |
| `qlab/events/significance.py` | moving-block bootstrap OOS 显著性 |
| `qlab/events/multiple_testing.py` | 预注册 + Bonferroni/BH/Deflated-Sharpe haircut |
| `qlab/events/metrics.py` | EVO-12 §2 指标块（`evo12_metrics`） |
| `qlab/swing/evaluate.py::evaluate_curve` | 曲线 → 门 + 显著性接线 |
| `qlab/swing/momentum_signals.py` | 复用 `load_daily`/`_rebalance_mask`/open-to-open 约定 |

新代码（仅本候选）：`swing/gem_signals.py`、`swing/gem_evaluate.py`、`swing/run_gem.py`。
**无 best-of-N；不重实现任何判据指标。**

## 1. 数据来源（hard gate #3）

| 层 | 来源 | 角色 |
|--|--|--|
| 价格/信号/执行 | **Yahoo v8 chart 复权日线**（split+dividend adjusted） | 唯一数据源 |

- 本轮按工部/首辅「免费日线（Stooq/Yahoo/FRED）」数据政策取数（(a)#2）。这与动量
  sleeve 的 OpenD-only 政策**不同**：GEM 是规则型择时、不走 OpenD 引擎，且 OpenD
  gateway 在本 workspace 不可达；免费日线是本轮唯一可行且获授权的源。**已标注，
  后续可用 OpenD SPY 交叉校验**（overnight/复权口径一致性）。
- 复权口径：用 `adjclose/close` 因子把 OHLC 整体重标定，使 overnight 与 intraday 腿
  在 split+dividend 上一致（否则除息/拆股日会注入假隔夜跳空）。
- 抓不到的符号如实记为缺口（`blocked`），绝不造数或静默换标的。
- `TrdEnv.SIMULATE` 语义：纯行情、零真金、零下单——GEM 代码无任何下单/入金路径。

## 2. 候选：GEM 双动量（Antonacci 2014, *Dual Momentum Investing*）

- **可持有资产（冻结，3）**：`SPY`（美股）、`VEU`（非美 FTSE All-World ex-US）、
  `AGG`（综合债券，risk-off 避险仓）。**绝对动量门槛资产**：`BIL`（1–3M T-bill，
  **仅作门槛、不持有**）。
- **信号（no-fit，hard gate #2 clause #4）**：`mom(T)=close(T)/close(T−L)−1`，
  L=lookback 交易日。规则：
    - 绝对动量闸：`mom_SPY(T) > mom_BIL(T)` → risk-on；否则 risk-off。
    - risk-on：在 `SPY` 与 `VEU` 间取 `mom` 更高者（相对动量），100% 持有。
    - risk-off：100% 持有 `AGG`。
  均为 Antonacci 2014 双动量惯例，**冻结于结果之前，非样本内拟合**。
- **仓位（冻结，无旋钮）**：单资产 **100% 权重**；long-only、**无做空、无杠杆**。
  避险靠 risk-off 切 AGG，无 vol target / breaker / stop（绝对动量闸即唯一风控）。
- **主 lookback = 12 个月（L=252d）**。family（仅 haircut/稳健，非 best-of-N）：
  **L ∈ {6mo=126d, 12mo=252d}**，**主格 = 12mo**（预先固定）。
- **再平衡 = 月度**（每月最后交易日 close 决定，次 open 执行）。

## 3. 执行与反前视（hard gate #2）

- 权重在再平衡 `close(T)` 决定，只能从 `open(T+1)` 起交易；持仓收益 **open-to-open**：
  `open(p+1)/open(p)−1`。任何 bar 都不用信号当时不可交易的信息定价。已单测。

## 4. 成本模型（冻结）

- `side_frac_base = 0.001`（10 bps/side：5 佣金 + 5 滑点，EVO-12 CostModel 基准）。
- **决策口径 = ×2**（成本翻倍下判 pass/fail）；×1 仅上下文。成本 = side×cost_mult×换手。

## 5. 门槛与影子分层（§6 阈值冻结）

- **官方门（唯一 PASS 判据）**：全样本 CAGR ≥ 50% 且 MDD ≤ 20%，且过门 2/3
  （分年度/滚动）、OOS 显著、过 haircut、且**每个危机窗** MDD ≤ 20%。
- **影子分层（仅记录，绝不自行放行）**：
    - 组合级目标带：CAGR ∈ [25%,35%) 且 MDD < 20%
    - 兜底带：CAGR ∈ [15%,20%) 且 MDD < 20%

## 6. 危机子窗（进 verdict，非附录 —— (b)#4）

`2008_gfc`(2008-06-01→2009-06-30)、`2020_covid`(2020-02-15→2020-04-30)、
`2022_ratehike_bear`(2022-01-01→2022-12-31)（另附 2025–2026 近窗）。任一窗 MDD>20%
即直接负向，不被平均掉。

## 7. 诚实试验计数 / DSR（(b)#5，地基）

- GEM 是**单一文献配置**，无因子挖掘。**within-candidate N = 2**（family {6m,12m}）。
- DSR 的 `n_trials` 取 family size；**跨轮累计真 N** 由户部组合级判据在拼装所有候选
  （GEM/多因子/残差动量…）时累加——本候选只如实吐自己的 N，**不预先折算、不做幸存者上交**。

## 8. Walk-forward / NO-FIT 豁免（hard gate #2 clause #4）

- lookback=12m / 月度 / 单资产 100% 全为文献惯例，冻结于结果之前 ⇒ **全样本曲线即
  OOS 曲线**，gate3 滚动为稳定性代理，不欠 per-fold 重拟合。若任一参数事后被证明是
  样本内选出的，豁免作废、须补真实分折 WF（embargo/CPCV）。

## 9. 冻结切分

- **数据窗 = 四资产共同可得起点**（受 VEU 2007-03 / BIL 2007-05 约束）+ 12m 回看
  warm-up ⇒ 首次决策约 2008 中，覆盖 2008 GFC / 2020 COVID / 2022 加息熊三窗。
- 宇宙冻结，跑中不换标的；未取到的符号=永久现金槽（数据缺口），不静默重配权。

## 10. verdict 规则（(b)#3）

- **直接清官方 50/20** → verdict=PASS(需CERTIFY+终审)，**立即上报工部尚书**。
- **过影子未过 50/20** → verdict=过影子未过50/20-停报，**停下带真实数字回报，不自行放行**。
- 二者皆不满足 → verdict=基线未达标（NEGATIVE），随轮回报。
- 全部回报路径：→ 工部尚书（不直接外呼首辅/都察院）。
