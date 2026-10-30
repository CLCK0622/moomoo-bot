# 独立 15k 离线影子账（EVO-885）

本模块只处理显式合成意图、累计收据和盯市输入；不生成策略信号，不连接 OpenD、SIMULATE 交易上下文或 REAL。`execution_verified` 与 `certifiable` 始终为 `false`。固定本金是 USD 15,000，与旧 `llm_paper` 的目录、数据库、库存和调度分离。

基于 PR #10 的 `4e076c87af50e3388229b5edc9a44a888addabb5`，只新增本目录和 `qlab/tests/shadow15k/`。只 import PR #10 的契约/夹具；没有修改其接口、费用工具或正在进行的 v0.2 接线。

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

Harness 禁用 socket、DNS 和连接入口，记录网络尝试数；无当前时间、随机值或外部 Python 包。`fixtures/cases.json` 是完整固定输入，9 个用例包括报告第 7 页的五项：`paper.partial_is_incomplete`、`paper.failed_hedge_retains_risk`、`nav.missing_mark_is_unknown`、`intent.retry_requires_reconcile`、`cost.cash_vs_reference_no_double`，另含部分成交累计费、TAF 日期切换、策略拒绝和命名空间初始状态。正例只证明账务机制，不能解释为策略盈利或成交验证。

报告携带原字节夹具 SHA、逐 case 输入 SHA、包含本模块和所 import 工具源码的 SHA 清单及汇总、依赖版本、assumptions。工程自检输出保存在 `evidence/harness.json`。重跑时不要把已存在的证据文件当新的输入。

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
- `pending/partial/unknown` 或数量/费用未知会阻塞新意图；同 ID 同内容跨进程/重启重试不重复记账。不同内容拒绝。新收据 ID 下的累计快照可补齐先前未知项；不能删掉已知库存和费用。普通单明确 `cancelled` 可保留已知残量后解除对账阻塞，但不会声称完整执行。保护单失败/不足额持续冻结，不提供自动覆盖或修复权限。
- `readout(marks)`：输入同一 UTC `as_of` 的完整 `prices` 与明确 `price_basis`。缺价/非正价/未知价不使用旧值；当前持仓缺一价则 `valuation_complete=false`、NAV/P&L=`null`。数量未知时保留 `last_known_qty`/库存但不报完整估值；费用未知时 `cash/fees/nav/net_pnl=null`，已知部分另列。`last_known_cash`/`known_fees` 不是完整净值。

金额通过固定 50 位上下文的 Decimal 运算并以字符串输出，不受调用方修改 Decimal 精度影响；不做未经冻结的发票分项分币舍入。禁止最终空头库存或计费后现金透支。逐单费用在累计数量和金额上重算，仅记累计差额；`postings` 留每次已知数量/金额/费用增量，`fee_ledger` 留逐单累计费用和组成。一个订单固定在一个交易日，跨日必须另给订单 ID，不能用收据到达日改费率。跨日收费的最终业务政策仍待冻结。

## 报告字段

`metrics` 覆盖报告第 7 页全部字段：`candidate_id/version/decision_ts/input_hash/price_basis/reading_kind/gross_pnl/fees/net_pnl/cash/inventory_value/missing_marks/execution_verified/sharpe_available/metric_unavailable_reason/cumulative_n/n_ledger_hash/intent_id/fills/residual_qty/reconciliation_required`，并附 `valuation_complete/execution_complete/quantity_complete/fees_complete`、库存、NAV、逐单费用和事件链 SHA。多意图字段显式按意图列出，残量按意图/订单索引。

`execution_complete` 只表示合成计划数量已知且完全满足；不等于 `execution_verified`。保护单数量完成也不能证明保护有效，`hedge_verified=false`。没有权威 N 输入和收益序列，因此 `cumulative_n/n_ledger_hash/sharpe=null`，`sharpe_available=false` 并给原因。数值零与未知严格区分。

## 策略停止门与前提假设

`policy.py` 的选池、倾斜权重、首日建仓、换手、`voluntary_trade_gate`、再平衡和退役接口始终拒绝，原因均为 `prereg_pending_v0.2`，参数均为 `null`。即使请求自称 frozen/verified 也不放行。本单不会随着 PR #10 接 draft v0.2 而自动解锁；须 EVO-883 最终冻结、翰林核验及后续授权后另行实现。

费用仅是带前提的机械算术，保留以下未闭合项并在产物逐项列出：

1. 使用 EVO-882 eligible-client/SG 税务场景，真实零佣资格、GST 计税基、SEC/TAF 每单 min/max 映射与发票舍入未核实。
2. TAF 按显式 `trade_date` 生效日切换：2026-10-01 至 2026-12-31 暂停、2027-01-01 起恢复；日期不在费表内直接拒绝。这里不采用 research_restored 的历史预算口径。未来 Section 31 和新费率到件空档均未获得实时验证，开放末期只作冻结费表假设，不作生产有效性证明。
3. ×2 同步放大所有显式费项、GST、摩擦与诊断地板。`reference` 扣全份摩擦；`cash_bid_ask` 已含 ×1 摩擦，×1 不重扣、×2 只扣增量。10bp 单边地板仅作诊断，不在现金账再扣一遍，也不构成策略准入。
4. 全部价格和收据由合成输入提供；没有真实 bid/ask、深度、成交、总回报、分红和公司行动证明，也不处理复权价换算。
5. 费用政策仍待 EVO-883 后续版本；未接冻结元策略、权威 N/V、基准/IR 或历史 walk-forward。没有运行新策略回测、前向采样、生产调度、旧纸面轨或任何账户/凭据操作。

这次交付范围是隔离账本、拒绝桩和离线合成验证；策略集成与前向采样继续停止。D10 独立复核及首辅另行授权是后续阶段。
