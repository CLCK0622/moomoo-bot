# research/gate —— EVO-149 冻结验收门（户部门禁护栏）

给 **Qlib / RD-Agent 试跑管线** 接线用的候选验收门。落地首辅 2026-07-29 裁定与 EVO-8 纪律。

## 架构铁律（任何人不得绕）

1. Qlib / RD-Agent / AlphaAgent 一律只当 **假设生成器**。
2. 验收权 **100% 留在本门**。
3. 工具自带回测 **永不** 作接受判据。

生成器产候选 → 本门验收 → 户部 `CERTIFY` → 都察院终审 → 回报首辅。负向静默。

## 七道门（cheap → expensive，尽早杀）

| 顺序 | 门 | 模块 | 失败即 |
|---|---|---|---|
| 1 | 预注册完整性 + 冻结核对 | `prereg.py` | `REJECTED_prereg` |
| 2 | 诚实试验计数（不吐全量 N 即不评估） | `trial_ledger.py` | `REJECTED_honesty` / `HonestyError` |
| 3 | 成本 x1x2 早筛 | `cost_capacity.py` | `REJECTED_cost` |
| 4 | 容量 / ADV | `cost_capacity.py` | `REJECTED_capacity` |
| 5 | ex-ante 经济理由（无理由→隔离） | `prereg.py` | `REJECTED_rationale` |
| 6 | 样本外净值 + 危机子窗 + OOS 单发预算 | `metrics.py` / `walk_forward.py` | `REJECTED_oos_budget` / `FAIL` |
| 7 | DSR 多重检验 haircut（N=跨轮累计真实数） | `deflated_sharpe.py` | `REJECTED_dsr` |

通过全部硬门后出 **双口径** 判定：
- `REPORT_5020`：直接清 Kevin 官方 50/20 → 即刻上报。
- `DECISION_POINT`：过影子上报门（组合级 CAGR≥25% / MDD≤20%）未过官方门 → 带真实数字上验收线，请 Kevin 拍板。
- `FAIL`：连影子上报门都没过。

## 接线示例（工部管线里）

```python
from research.gate import certify, Candidate, TrialLedger, OOSBudget, freeze_config

# 1) 每轮挖矿先登记全量 N（含被丢弃的因子），否则候选不予评估
ledger = TrialLedger("research/gate/state/trial_ledger.json")
ledger.register_run("qlib-alpha158-run1", source="qlib",
                    n_trials_total=158, n_evaluated=3, trial_sharpes=all_trial_srs)

# 2) 跑前冻结预注册配置
cfg = {"universe": frozen_tickers, "leverage_cap": 2.0, "signal_params": {...},
       "rebalance": "monthly", "cost_model": "moomoo_retail_x1",
       "train_test_split": "2017-12-31", "gate_thresholds": "official_50_20+shadow"}
fhash = freeze_config(cfg)

# 3) 用 walk_forward / cpcv 切样本外，只在 train 上挖矿，OOS 留最后一发
#    生成器（Qlib/RD-Agent）产出 OOS 净收益后 → 送门

cand = Candidate(name="dual_momentum",
                 oos_net_returns=oos_net_r, oos_dates=oos_dates,
                 gross_returns=gross_r, turnover=turnover, cost_per_turnover=0.0005,
                 required_notional=req_notional, adv_notional=adv,
                 prereg_config=cfg, frozen_hash=fhash,
                 economic_rationale="动量溢价：行为(处置效应/羊群)+风险(增长期权)双解释……",
                 trial_sharpes=all_trial_srs)

verdict = certify(cand, ledger=ledger, oos_budget=OOSBudget(max_evals=1))
print(verdict.summary())
# 仅当 verdict.certified and verdict.decision in {REPORT_5020, DECISION_POINT}
# 才由户部盖 CERTIFY、转都察院终审、回报首辅。
```

## 台账是地板（fail-closed）

有 `ledger` 时它是 N 与试验方差 V 的**地板**：自报 `n_trials_cumulative` / `trials_variance`
只能把门开得**更严**（更大），不能压低。自报 N 低于 `cumulative_n()` → `certify()` 抛
`HonestyError`（与 `register_run` 同惯例，逼修接线而非静默驳回）。**正确管线用法：传
`ledger=`，`n_trials_cumulative` / `trials_variance` 留 `None`，让门自台账取数。** 无台账的
手跑文献候选（如 GEM, N=2）才纯采信自报，合法用途不受影响。

## 红线

SIMULATE-only、仅免费数据、无裸空、杠杆预注册 ≤2x、不动真金。本门不碰真实资金，纯离线验收。

## 测试

```
python3 -m research.gate.tests.test_gate     # repo 根执行；39 项覆盖每道门的失败模式
```

依赖：`numpy`、`scipy`、`pandas`（已在环境内）。
