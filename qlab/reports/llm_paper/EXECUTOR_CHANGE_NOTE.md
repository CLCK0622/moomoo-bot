# EVO-8 前向纸面轨 · 执行器变更与等价性口径备注（(a) 单 book → (b) 多 book）

**本文件是口径备注，不动冻结文本、不动决策逻辑、不动冻结参数。** 记录三件必须留痕的事：
(b) 多 book 执行器做了什么、等价性验证到哪一步、以及**哪一轮起换的执行器**。

裁定链：工部尚书 2026-08-10 提出分叉 → 吏部同日裁定走 (b)（带前置条件与兜底）→ 工部尚书 2026-08-10
修完前置 1 的两处 bug（`4da9493`）→ 轮次因宿主离线窗断了 17 天 → 工部尚书 2026-08-27 派单恢复实现。

---

## 1. 当前状态：**(b) 尚未接管，承载路径仍是 (a)**

| | 状态 |
|--|--|
| 承载路径（写入 §4 判据的那条） | **(a) `run_round.run_round()`** |
| (b) `multi_book.run_round_multi()` | 已在树上、有单测、可跑；**未接管** |
| 等价性第 ① 段（决策集 vs 第 1 轮） | ✅ **通过**（下方 §3） |
| 等价性第 ② 段（book 等价性） | ⏳ 待与 (a) 并行的那一轮对照 |
| 换执行器的轮次 | **尚未发生**；换轮次确定后回填本表 |

**08-31 那轮的默认路径仍是 (a)，(b) 不阻塞、不推迟轮次。** 证据连续性高于本次重构。
并行对照时 **(b) 必须传 `register_trials=False`**——对照不是承载路径，二次登记只会拿到幂等旧记录、
把 `n_evaluated` 记歪（`ledger_bridge` 会把这种情形标成 `ledger_reused_existing_record`，不静默）。

## 2. (b) 做了什么

`qlab/qlab/llm_paper/multi_book.py` —— **一次取符号并集、内部按格分账**，每格自带 book 与净值点：

* 配额形态实测（足额 10 格一轮，第 1 轮的 7 标的 + SPY）：**8 次/轮**；
  朴素「10 次 `run_round()` 各取一遍行情」需 **80 次/轮** ≫ 25/天硬预算。这正是吏部指出的正确形态。
* **组合约束按格逐一判**：每格是一个独立组合，不跨格加总（10 个 49% 是 10 个合规组合，不是 490% 超限）；
  任一格不过 ⇒ **整轮 fail-closed、零落盘**，与 (a) 同一条纪律（不产出半截证据）。
* 决策 / 约束 / 建仓 / 盯市 / 探针全部**复用既有实现**（`build_decision` / `check_portfolio` /
  `build_book` / `mark_to_market` / `determinism`），本模块只做编排，不复制其中任何一段逻辑——
  这是「两条路径不会静默分叉」的结构性保证，比对齐两份代码更可靠。
* 探针**按轮不按格**（它测的是模型有没有被换权重，与格子无关），仍无跳过开关。
* 缺格如实记进 `cells_missing`，不静默。

`qlab/qlab/llm_paper/nav_series.py` —— **每格净值序列**，从各轮**不可改的 round JSON** 机械拼出，
不维护第二份可变的累计文件。(a)/(b) 两种落盘格式都认，`coverage()` 直接给出
`executor_switch_rounds`（哪一轮起换的执行器，一眼可见）。未建仓的轮次没有净值点，序列里就不该有那一天——
**不补「持平」点**。`cumulative_returns()` 是监控读数，**不出 verdict**；判定一律走 `certify()` + `llm_paradigm`。

## 3. 等价性验证第 ① 段：决策集与第 1 轮 `f2f7729` 逐位相同 ✅

第 1 轮 `status=pending_entry_bar`、**没有 book 可比**（工部尚书 2026-08-10 §3 已更正吏部的前置 2），
故第 ① 段比的是**决策集**。可复跑：`python3 qlab/tools/verify_multi_book.py`（不打网络、不花配额、不改台账），
同一比对另有单测 `tests/test_multi_book.py::test_decision_set_matches_round1_bit_for_bit`。

```
① 决策集 vs 第 1 轮 f2f7729（round_20260810.json）
   比对字段    symbol, target_weight, seed, prompt_variant, evidence_available_utc, decision_ts, intended_start
   条数        7 vs 7
   逐位相同    True   差异 []
   gross       0.49 (第 1 轮 0.49)
   book 状态   pending_entry_bar（第 1 轮 pending_entry_bar，如期无 book）

② 冻结足额 10 格一轮
   取行情调用  1 次，符号 ['CAT', 'COP', 'EMR', 'GD', 'GILD', 'MET', 'MRK', 'SPY']
   本轮配额    8 次（朴素按格各取一遍需 80 次）
   格子        评估 10/10，缺格 []
   每格 gross  pv1=0.49 / pv2=0.37（按格判，不跨格加总）
   verdict     None
```

**这一比对不是抄答案**：喂给 (b) 的是 `evidence_acceptance_utc`（信息源自身受理时刻），
`evidence_available_utc` 由 `derive_available_utc` **重新派生**后才比对，故真的过了一遍派生逻辑。
（单条重建与原多条等价：`derive_available_utc` 对信息源时间单调不减 ⇒ max(可得) = 可得(max(受理))。）

比对器本身也上了单测（改一个字段必须报出来），不做橡皮图章。

## 4. 等价性验证第 ② 段：book 等价性（待办）

与 (a) 并行的那一轮，同一批 bar 各算一次 book，逐位比 `shares` / `entries` / `gross_notional` /
`cash` / `nav_point`。机械版本已先行落测：`tests/test_multi_book.py::test_single_cell_book_identical_to_path_a`
在打桩行情下证明单格 (b) 与 (a) 逐位相同（含真 book 与净值点）；**并行对照是它的实盘版本，比完才切**。

## 5. 顺带修掉的一个会让**第 2 轮直接归零**的坑（(a)/(b) 同受影响）

实现时用真台账副本模拟第 2 轮，发现原先内联在 `run_round()` 里的台账登记**第 2 轮起必崩**：

```
RefreezeError: 候选 candidate_id='llm_paper' 已以 run_id=['llm_paper-2026-08-10'] 登记，
现又以新 run_id=llm_paper-2026-08-31 重登…须显式 supersedes=<旧 run_id> 覆盖计一次
```

抛错点最坏：**配额已花、决策已产生、round JSON 尚未落盘** ⇒ 该轮证据当场归零，
后果等同于「空一轮永久少一轮」。这与本次改点要抢救的第三轮是同一件事，故一并修掉。

`TrialLedger` 的重冻护栏（工部 2026-07-30）本身是对的——同 `candidate_id` 换 `run_id` 静默追加会把
同一批试验计两遍、N 虚高 ⇒ DSR haircut 变松。错的是调用方：本轨是**一个候选、一张冻结的 10 格网格、
按周前向推进**，每周不是新增 10 个试验，是同样那 10 格多走了一周。故正确形态是
**一个候选恒定一条台账记录**，`supersedes` 覆盖计一次：

* `n_trials_total` **恒为冻结的 10**，一格不少登（DSR 的 V 不变、不放松）；
* `n_evaluated` 取**跨轮已评估格子的并集**，从各轮 round JSON 机械读出——(a) 长期是 1 格，
  (b) 接管后是 10 格，「哪一轮起变成 10」在台账与 round JSON 两侧都对得上；
* `cumulative_n()` 里本候选恒定贡献 10，不会每周 +10。

实现在 `qlab/qlab/llm_paper/ledger_bridge.py`，**(a)/(b) 共用同一份**（这也顺手消掉了两条路径各写一份
登记逻辑的分叉风险）。回归单测把「原内联写法在第 2 轮必崩」这个失败形态本身钉死，防止有人改回去。

## 6. 红线与边界（本次改动全程未动）

冻结文本 / 决策逻辑 / 冻结参数一律未动；`temperature` 未动、未重冻；`n_trials_total` 按冻结 10 格足额登记；
第 1 轮已落盘记录未回改。SIMULATE-only、零真金、仅免费数据、禁做空、单标的 ≤10%、总仓 ≤100%、≤1x。
**未 rebase、未 force-push**（集成分支 `agent/evo-162-residual-reversal` 快进推送）。
