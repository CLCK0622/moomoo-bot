# 独立 15k 离线影子账（EVO-885）

本模块只处理显式合成意图、累计收据和盯市输入；不生成策略信号，不连接 OpenD、SIMULATE 交易上下文或 REAL。`execution_verified` 与 `certifiable` 始终为 `false`。固定本金是 USD 15,000，与旧 `llm_paper` 的目录、数据库、库存和调度分离。

基于 PR #10 已复核的 `6c63505f72135063162c1f55ecfaa03514f1fa32`，只新增本目录和 `qlab/tests/shadow15k/`。原提交 `2a0aad4` 重放为 `1fab8c4`，无文本冲突；后续独立提交处理费用与现金的语义衔接。只 import PR #10 的现有接口，未修改其源码或封存回执。

## 运行和复现

在仓库根目录、Python >=3.9（仅标准库）运行，两个 workdir 必须为空或不存在：

```sh
PYTHONPATH=qlab:. python3 -m qlab.shadow15k.harness --workdir ./repro-a > harness-a.json
PYTHONPATH=qlab:. python3 -m qlab.shadow15k.harness --workdir ./repro-b > harness-b.json
cmp harness-a.json harness-b.json
PYTHONPATH=qlab:. python3 -m pytest qlab/tests/shadow15k qlab/tests/dynamic_factor qlab/tests/test_qlib_gen.py -q
python3 -m ruff check qlab/qlab/shadow15k qlab/tests/shadow15k
python3 -m ruff format --check qlab/qlab/shadow15k qlab/tests/shadow15k
```

Harness 禁用 socket、DNS 和连接入口，记录网络尝试数；无当前时间、随机值或外部 Python 包。`fixtures/cases.json` 的9个固定用例保留报告第7页的五项：`paper.partial_is_incomplete`、`paper.failed_hedge_retains_risk`、`nav.missing_mark_is_unknown`、`intent.retry_requires_reconcile`、`cost.cash_vs_reference_no_double`；TAF补充用例现验证所有日期restored。另有8项QQQ现金衔接探针，覆盖金额冲突、缺映射、未证到账、除息日新买、应收不可花和付款重试/回滚。正例只证明账务机制，不能解释为策略盈利或成交验证。

报告携带原字节夹具SHA、QQQ映射SHA、v1身份、逐case输入SHA、源码清单及依赖版本。当前工程回执见`evidence/rebase-6c63505/`；根目录的旧`harness.json`/`verification.json`只保留原交件历史，不能作当前输出。重跑不读取任何旧证据文件。

## API 和状态

构造 `FeeBook(params_path, schedule_path, params_sha256=..., schedule_sha256=...)`：调用方必须明确传入文件与 SHA，无隐含费率。合成 harness 的 `fixture_fees("x1"/"x2")` 读取 PR #10 已收存的 EVO-882 原件，两个参数文件已经与 EVO-882 附件逐字节核对：

| 文件 | SHA-256 |
| --- | --- |
| `fee_params_x1.json` | `7e24f9e9b25802a7d4b50bd4b089a60d288b8f8f448ea92aac9482816b7ffdb2` |
| `fee_params_x2.json` | `a81bb5790638e9730dec666a695bbb797ab1ec7fe817e666f744193cfa6f9044` |
| `fee_schedule.json`（PR #10） | `c400412f361a659290289517adf640e1fc2610560e203dc79bf76975e87c7fd9` |

`ShadowLedger(root, genesis, fee_book)` 要求 `root` 名为 `shadow15k`，独占该目录与 `ledger.sqlite3`。拒绝旧轨/受控目录、符号链接、硬链接及外来文件/数据库。`genesis` 必须显式提供以下全部字段：

```json
{
  "namespace": "evo881.shadow15k.offline",
  "mode": "offline_synthetic",
  "initial_cash": "15000",
  "candidate_id": "SYNTHETIC_NOT_A_STRATEGY",
  "version": "fixture-v1",
  "price_basis": "cash_bid_ask"
}
```

×1/×2 和不同 price basis 使用不同父目录下的 `shadow15k/`；原目录重开时身份、价基和费参 SHA 必须完全匹配。数据库仅有不可覆盖事件；事务使用 `BEGIN IMMEDIATE` 和 `synchronous=FULL`，每次重放校验连续序号与哈希链。哈希用于可追溯和损坏检查，不是防篡改签名。拒绝的无效事件不入账。

- `register_intent(request)`：要求 `intent_id`、UTC `decision_ts`、`input_hash`、非空 `orders`。每单明确 `order_id/symbol/side/planned_qty/trade_date/protective`，股数只允许正整数。意图不产生库存；这是纯合成夹具入口，不接策略的下单链。
- `record_receipt(intent_id, receipt)`：要求全量累计快照 `receipt_id/receipt_ts/orders`。每单明确 `order_id/confirmed_qty/gross_usd/fee_known/status`。收据时间不得早于决策/先前收据。股数与金额不得倒退、超计划或凭空增加。终态已知收据不能修改。`fills` 是这些合成累计快照，不代表券商逐笔成交。
- `record_dividend({receipt_id, as_of, event})`：把版本化QQQ现金输入写入同一本独立事件账。事件按除息日唯一汇总，资格由账中更早交易日的已知整股持仓计算，除息日新买不享分红；除息日卖出不抹掉先前资格。事件中的资格必须与账内一致。金额/来源/支付证据复用`dynamic_factor.integer_cash_valuation`校验，2022-12-19每股0.65541绑定`71953b09…`映射。错误金额/缺映射可作为未知记录保存，但读数为null并阻塞新意图；写入成功不代表现金可用。经验证的模拟付款不能被改写，未证付款可由后续追加补证。
- `pending/partial/unknown` 或数量/费用未知会阻塞新意图；同 ID 同内容跨进程/重启重试不重复记账。不同内容拒绝。新收据 ID 下的累计快照可补齐先前未知项；不能删掉已知库存和费用。普通单明确 `cancelled` 可保留已知残量后解除对账阻塞，但不会声称完整执行。保护单失败/不足额持续冻结，不提供自动覆盖或修复权限。
- `readout(marks)`：输入同一 UTC `as_of` 的完整 `prices` 与明确 `price_basis`。缺价/非正价/未知价不使用旧值；当前持仓缺一价则 `valuation_complete=false`、NAV/P&L=`null`。数量未知时保留 `last_known_qty`/库存但不报完整估值；费用未知时 `cash/fees/nav/net_pnl=null`，已知部分另列。`last_known_cash`/`known_fees` 不是完整净值。

`cash`是`available_cash`的兼容别名，`receivable_amount`单列。交易现金不含分红，事件按唯一除息日派生累计模拟入账，重复回执/重启不重复加现金。应收只进入可完整估值的NAV，不可用于买入；交易所支付日不等于模拟到账，需显式金额/日期/证据SHA。真实账户金额/到账时间始终null，不做分红再投或整数股变化。分析TR输入不能代替现金分红。收据/决策/读数不得回溯到已观察付款证据之前。

账内金额通过固定50位上下文Decimal运算并以字符串输出；导入工具提供冻结v1数值读数，不自拟额外舍入。禁止最终空头或可用现金透支。逐单费用在累计数量/金额上重算，仅记差额；`postings`留每次增量，`fee_ledger`留累计费用/组成。订单限定DAY及一个交易日，跨日另给ID。费用身份增加冻结合同/profile和政策版本；旧费率/旧政策SQLite库身份不匹配即拒绝，不自动重解释历史事件或迁移实盘数据。

## 报告字段

`metrics` 覆盖报告第 7 页全部字段：`candidate_id/version/decision_ts/input_hash/price_basis/reading_kind/gross_pnl/fees/net_pnl/cash/inventory_value/missing_marks/execution_verified/sharpe_available/metric_unavailable_reason/cumulative_n/n_ledger_hash/intent_id/fills/residual_qty/reconciliation_required`，并附 `valuation_complete/execution_complete/quantity_complete/fees_complete`、库存、NAV、逐单费用和事件链 SHA。多意图字段显式按意图列出，残量按意图/订单索引。

`execution_complete` 只表示合成计划数量已知且完全满足；不等于 `execution_verified`。保护单数量完成也不能证明保护有效，`hedge_verified=false`。没有权威 N 输入和收益序列，因此 `cumulative_n/n_ledger_hash/sharpe=null`，`sharpe_available=false` 并给原因。数值零与未知严格区分。

## 策略停止门与前提假设

本轮是rebase和账务接线。定义身份已绑定v1.0.1，运行N/V、参考证据和前向授权未到，`policy.py`的策略入口继续拒绝，原因改为`runtime_evidence_unavailable_v1`，参数null；不再谎报冻结草案缺失，也不把S2不可算变成空池/全持QQQ。实际策略及前向采样不由机械账务入口解锁。

费用仅是带前提的机械算术，保留以下未闭合项并在产物逐项列出：

1. 使用 EVO-882 eligible-client/SG 税务场景，真实零佣资格、GST 计税基、SEC/TAF 每单 min/max 映射与发票舍入未核实。
2. 所有日期采用restored TAF研究政策，含2026Q4；日期只作订单交易日键。原费参/日程字节不变，不将研究费用当真实发票或实时费率核验。
3. 费用直接复用PR #10 `fee_model.order_cost`：逐个净订单先取模型费与10bp地板较大值，再整体×2；cash_bid_ask扣除已经包含的×1摩擦，避免重复。单边地板已进研究费用，不再额外扣一次；原显式分项仍单列，不冒称已核发票。
4. 价格与执行收据只用合成输入；QQQ复用已交来源映射，未取市场数据或证明真实账户分红到账。不做复权价替代现金。
5. 费用政策待EVO-883后续版本，真实资格/发票与运行证据仍缺。没有运行策略回测、前向采样、生产调度、旧纸面轨或账户/凭据操作。

这次交付范围是隔离账本、拒绝桩和离线合成验证；策略集成与前向采样继续停止。D10 独立复核及首辅另行授权是后续阶段。
