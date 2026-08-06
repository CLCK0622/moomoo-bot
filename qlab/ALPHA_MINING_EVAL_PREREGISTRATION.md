# EVO-8 岔路 (i) — Qlib 有界因子挖掘（偏收益引擎）: FROZEN 预注册

**冻结于任何回测结果被读取之前。** 基线 `agent/evo-162-residual-reversal @ 7259aba`（C 数据 + 资金效率口径 +
store provenance/verifier 均在树上、117 单测绿、ledger N=35）。本文件在结果 commit 之前提交，git 时序供户部/都察院核。

**store 复现前置已满足**：本轮重建 store 后跑 `python -m tools.qlib_gen.verify_store_fingerprint` →
`input_parquets 541cb575…` + `store ae8fbdc6…` **双指纹全匹配**，与都水 provenance 锚点一致。

## 0. 判据零重实现 / 不自建门

- Qlib 只作**因子表达式求值器**，其自带回测**永不作判据**；判定 100% 交 `research/gate.certify()`（`7259aba` 版）。
- 新代码仅接线（复用 `tools.qlib_gen.factor_export` + `swing/multifactor_signals` 的合成/组合引擎）。

## 1. N 预算纪律（宁少而准 —— 硬约束）

试验数 N 是**永久不可退的公共成本**（现 `cumulative_n=35`；全量倒 Alpha158 会推到 ~193+，**永久抬高之后每一条
候选的 DSR 门槛**）。故本轮**只冻结 12 条**有界表达式（下 §2），**向公共 N 池支取 12**（35→47），不全量倒库。

## 2. 冻结的表达式子集（12 条，每条附 ex-ante 经济理由；跑后不得增删）

| # | name | Qlib 表达式 | 经济理由（ex-ante） |
|--|--|--|--|
| 1 | `illiq_amihud` | `Mean(Abs($close/Ref($close,1)-1)/($volume*$close+1),21)` | Amihud 非流动性溢价：买卖冲击大者需更高预期收益（Amihud 2002）。**新族**：此前八因子未含流动性维度。 |
| 2 | `turnover_low` | `-Mean($volume,21)/Mean($volume,252)` | 换手率异象：高换手＝高投机/分歧，低换手长期跑赢（Datar-Naik 1998）。 |
| 3 | `vol_of_vol` | `-Std(Std($close/Ref($close,1)-1,21),63)` | 波动的波动＝不确定性定价，低 vol-of-vol 溢价（Baltussen 2018）。低波族的**二阶**维度，非既有 vol60/120 重复。 |
| 4 | `downside_beta` | `-Std(Less($close/Ref($close,1)-1,0),126)` | 下行风险定价：下行半方差比总方差更贴投资者厌恶（Ang-Chen-Xing 2006）。 |
| 5 | `max_lottery` | `-Max($close/Ref($close,1)-1,21)` | 彩票偏好：极端单日涨幅吸引投机、随后跑输（Bali-Cakici-Whitelaw 2011 MAX）。 |
| 6 | `skew_neg` | `-Mean(Power($close/Ref($close,1)-1,3),63)` | 特质偏度定价：正偏（彩票型）跑输（Boyer-Mitton-Vorkink 2010）。 |
| 7 | `intraday_close_str` | `Mean(($close-$open)/($high-$low+0.0001),21)` | 日内收盘强度＝知情交易者尾盘定价（Bogousslavsky 2021 intraday momentum）。 |
| 8 | `overnight_drift` | `Mean($open/Ref($close,1)-1,63)` | 隔夜 vs 日内收益分解：隔夜段承载散户情绪/风险溢价（Lou-Polk-Skouras 2019）。 |
| 9 | `volume_shock_rev` | `-Mean(($volume/Mean($volume,21)-1)*($close/Ref($close,1)-1),21)` | 量价冲击后反转：无信息量冲击引发的价格压力会回补（Campbell-Grossman-Wang 1993）。 |
| 10 | `range_compress` | `-Mean(($high-$low)/$close,21)/(Mean(($high-$low)/$close,252)+0.0001)` | 波动压缩＝低风险状态定价（区间收窄相对自身历史）。 |
| 11 | `price_accel` | `($close/Ref($close,21)-1)-($close/Ref($close,63)-1)` | 动量**加速度**（二阶），非动量水平本身——既有 8 因子只含一阶动量。 |
| 12 | `close_to_high52` | `$close/Max($high,252)` | 52 周高邻近度作**锚定效应**代理（George-Hwang 2004）；与既有 prox52w 的口径差异：用 `$high` 而非 `$close`。 |

**排除的已证伪族**（生成阶段即剔除，不花试验预算复验已知负向）：日历/事件异象（B FOMC 已证伪）、
特质动量/残差反转（残差动量 EVO-162 已证伪）、经典中性套利、短波 carry（EVO-25 VIX carry 已证伪）、
静态风险平价、GEM 双动量、多因子那 8 条（mom12_1/mom6_1/prox52w/trend200/rev21/vol60/vol120/ltrev）、
A 利率 carry、C 信用 regime。**本 12 条与上述均不重叠**（流动性/换手/二阶波动/下行/彩票/偏度/日内/隔夜/量价冲击/压缩/加速度/锚定）。

## 3. 组合与执行（no-fit，沿用已过门引擎）

- 复用 `multifactor_signals`：每日横截面对每因子 winsor(1/99)+z-score×方向 → 等权合成 → **做多 top decile**、
  月度再平衡、**200d SMA 趋势闸**（SPY>200dMA 满仓、否则退现金）。long-only、无杠杆、无裸空。
- 执行 close(T) 决定 → open(T+1)、open-to-open；成本 10bps/side×cost_mult，**决策口径 ×2**。
- **family（决定 DSR 的 V，冻结、跑后不得增删）= 上述 12 条各自单因子的 x2 每期 Sharpe**。

## 4. 成功判据（如实标注，工部 2026-07-30 算术）

同宇宙（291 大盘 + 免费日线 + long-only + ≤2x）内最好水平 8.03%/22.6%，距官方 50/20（无杠杆等价 25%/10%）
**收益差 3.1 倍、回撤超 2.3 倍**。故本轮**如实瞄影子带**（组合级 25%/<20%，无杠杆等价 12.5%/10%），
官方门清关视为超预期。**非事件类候选，照旧全额 CAGR + `certify()` 判**（资金效率口径不适用）。
若结果仍落 8–12%，即为「同宇宙内 50/20 不可达、需换结构或换数据轴」再添一条实证。

## 5. 契约

`project_ledger()`（N=35→47）+ `project_oos_budget()` canonical 落盘、`candidate_id="alpha_mining_i"`、
family 预冻、每发记**全量 `n_trials_total` + 每期 `trial_sharpes`**（不声明 ppy）、`cost_per_turnover=0.001`、
`cost_model="moomoo_retail_x1"`、ADV 如实、`kernels=1`、判定 100% 走 `certify()`。
红线：SIMULATE-only、仅免费数据、本地算力、无裸空、≤2x、零真金。RD-Agent 本轮**不上**（不需 LLM 生成即可覆盖 12 条假设）。
