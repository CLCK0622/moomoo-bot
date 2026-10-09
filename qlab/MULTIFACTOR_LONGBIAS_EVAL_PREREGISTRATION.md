# EVO-8 方向(b) — MULTI-FACTOR LONG-BIAS: FROZEN 预注册

**冻结于任何回测结果被读取之前**（仅 smoke 验证 qlib 管线可跑，未读本候选 verdict）。基线
**rebase 到 `agent/evo-162-residual-reversal` @ `27cecc4`**（gate+生成器合树、N/V fail-open 已修）。
结果 commit 之前提交，git 时序供户部/都察院核。

## 0. 不自建门 / Qlib 只当因子源

- 新代码：`swing/multifactor_signals.py`（合成+组合+趋势闸）+ `run_multifactor.py`（接线）。
- 因子经 `tools.qlib_gen.factor_export` 出 tidy parquet + manifest；**`kernels=1`**；Qlib 永不作判据。
- 判定 100% 交 `research/gate.certify()`（合树后的 27cecc4 版，带 N/V/成本/容量修复）。

## 1. 候选：多因子长偏 + 200d 趋势闸

- **宇宙冻结** = `RESIDUAL_UNIVERSE_RESOLVED.txt`（大盘，跑中不换）。
- **因子集（8，Qlib 表达式，预注册冻结，方向锁定）**：
  `mom12_1(+) mom6_1(+)` 12-1/6-1 动量；`prox52w(+)` 距 52 周高；`trend200(+)` 200d MA 之上；
  `rev21(−)` 短期反转；`vol60(−) vol120(−)` 低波异象；`ltrev(−)` 长期反转/价值代理。
- **合成**：每日横截面对每因子 winsor(1/99)+z-score，乘方向，再对 8 因子取等权均值 = 复合分。
- **组合（long-bias，无做空无杠杆）**：月度再平衡，做多复合分 **top decile** 等权；杠杆上限 1.0×。
- **趋势闸**：SPY > 200d MA → 满仓 1.0×；否则敞口 → 0（absolute-momentum 撤现金），控回撤。
- **执行**：权重 close(T) 决定、open(T+1) 执行、open-to-open；成本 10bps/side × cost_mult（决策 ×2）。

## 2. 诚实 N + 共享账本（工部四条硬前提）

1. **全候选共用 `research/gate/state/trial_ledger.json`**；开跑前补登历史：GEM(2)+残差反转 EVO-162
   (family)+残差动量(4)+人肉筛除死因(~7)，再由 `factor_export` 登记本轮 8 个因子表达式。
   门 N 取 `cumulative_n()`（真累计，非单轮）。
2. 账本 gitignore → **最终 N 与各轮登记明细写进 report.json**（供都察院复核 N 来源）。
3. **`adv_notional`/`required_notional` 如实填**：单名部署额 vs 持仓名 20 分位 ADV，绝不留默认 0 跳过容量门。
4. `cost_per_turnover=0.001` 与冻结 10bps/side 一致（x1/x2 双跑）；`ledger=` 传入 + `n_trials_cumulative=None`；`kernels=1`。

## 3. 门槛 / 判定（全在 certify()）

- 官方 50/20（REPORT_5020）；影子上报**开区间 `≥25%` 且 MDD≤20%**（DECISION_POINT）；兜底 15/20（`shadow_floor_pass`）。
- FAIL 先看 `shadow_floor_pass`；危机窗 gate 自带 2008/2020/2022（样本没盖住→tail_incomplete 不背书）。
- DSR：N=`cumulative_n()`；成本早筛 x1x2；容量/ADV 如实。
- NO-FIT 豁免：因子定义+等权合成为文献惯例、冻结在前 ⇒ 全样本净收益即 OOS，单发 OOS 预算。

## 4. verdict 处置（工部口径）

出正向（REPORT_5020/DECISION_POINT）**先回工部、不自行上报 Kevin**（户部收口成本/容量门前的自律）；
负向随轮如实回流。全部回报 → 工部尚书；正向再走户部 CERTIFY → 都察院终审 → 首辅。
