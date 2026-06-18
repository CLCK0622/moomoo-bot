# moomoo-bot · qlab — 理财方向探索 策略验证工程骨架（EVO-13）

> **本仓库已在 `agent/evo-13-qlab-reset` 分支重置为 `qlab` 工程骨架。** 旧的
> `backend/`（futu 实盘 bot）、`frontend/`（Next.js 面板）、`ng-backend/` 等全部内容已清除，
> `main` 历史与旧分支保留不动。旧仓真实跑过的 moomoo OpenD 接线思路被**提取复用**到
> `qlab.brokers.moomoo`（见下「OpenD 适配层」），旧策略收益**一律不采信**。

一个**分层、可替换、核心零运行时依赖**的量化工程骨架。候选策略进入一条统一流水线：

```
数据接入(data) → 策略(strategy) → 回测(backtest) → 模型训练/持久化(model) → 报告/门禁(metrics+report)
```

> ⚠️ 只用 fixture（合成/样例行情）验证「整条链路能跑通」与指标计算口径。**不代表、也不声称任何真实策略表现。**

## 从旧 moomoo-bot 清理 / 复用了什么

- **清除**：`backend/`（含写死的 `TRADING_PASSWORD='762185'`、`pwd_unlock='123456'`）、提交进库的 `.env`、`frontend/`、`ng-backend/`、`DEPLOYMENT_CHECK.md`、`tunnel.sh`、IDE/缓存文件等全部旧内容。
- **复用（仅接线思路，不带凭据/策略）**：OpenD 连接初始化（`OpenQuoteContext` / `OpenSecTradeContext` + `security_firm`）、`unlock_trade` 解锁、`accinfo_query` 资产查询、`place_order(trd_env, trd_side, order_type)` 下单、`US.<symbol>` 代码规范、`ret == RET_OK` 返回约定、行情订阅与熔断/止损思路。这些被重写进 `src/qlab/brokers/moomoo.py`，并套上全部安全栏杆。
- **安全整改**：旧仓凭据写死且 `.env` 入库——新实现凭据**只走环境变量**（`qlab.config`），日志全程脱敏，自动交易默认关闭。

## 设计要点

- **核心引擎只用 Python 标准库**：`无真实行情也能跑通整条链路`，build/test/lint 零安装即可通过。
- **每层都是抽象 + fixture 实现各一份**，可直接替换为真实实现：
  | 层 | 抽象 | fixture / 示例实现 |
  | --- | --- | --- |
  | 数据接入 | `data.base.DataSource` | `data.fixture.FixtureDataSource`（CSV 或确定性合成） |
  | 策略 | `strategy.base.Strategy` | `strategy.sma_cross.SmaCrossStrategy` |
  | 回测 | `backtest.engine.BacktestRunner` | 事件驱动，含成本/滑点/样本外切分 |
  | 模型 | `model.base.Model`（fit/predict/save/load） | `model.momentum.MomentumModel`（JSON 持久化） |
  | 报告 | `report.report.ReportGenerator` | Markdown + JSON，对齐户部口径 |
- **moomoo US OpenD 只做接口/适配层设计**（`data.moomoo`）：密钥与账户全部走环境变量（`qlab.config`），源码不写死任何敏感信息，未显式启用前绝不发起任何实盘调用。
- **指标对齐户部口径**：年化收益、最大回撤、分年度表现、交易成本、滑点、样本外区间。
- **承接户部 EVO-12「回测口径、数据方案与指标门禁 v1.0」**：`qlab.metrics` 是独立可单测的指标计算模块，实现 v1.0 §2 全部指标（几何 CAGR、逐 bar MDD、回撤持续期、Sharpe/Sortino、胜率/盈亏比/盈利因子/期望、换手、容量）与 §3 四关门禁；报告层只做组装与门禁判定，产出覆盖 **B 成本登记 / C 成本后核心指标 / D 四关门禁 / E 偏差自查** 的结构化评估卡。

## v1.0 评估卡（B/C/D/E 门禁）

承接户部 [EVO-12] 的 v1.0 评估卡口径，指标与门禁分两层：

- **计算层 `src/qlab/metrics/`**（纯函数，逐项单测）：
  - `core.py` — §2 指标：`geometric_cagr` / `max_drawdown` / `drawdown_durations` / `sharpe` / `sortino` / 换手 / 容量 + `compute_core_metrics`
  - `trades.py` — §2.6-2.7 平仓 round-trip 重建 → 胜率/盈亏比/盈利因子/期望
  - `gates.py` — §3 四关：关1 全样本基线 / 关2 分年度一致性 / 关3 滚动窗口 / 关4 样本外(hold-out)，及综合判定（`候选通过` / `稳定性不足，未过线` / `基线未达标`）
- **编排 `pipeline.evaluate_candidate`**：跑主回测 + 四关 + **成本×2 压力测试** + （模型方向可选）**Walk-Forward 主口径**（`backtest/walk_forward.py`，逐折重训、拼接样本外曲线，对其跑关1-3）。
- **报告层 `report/evaluation_card.py`**：只组装与渲染，产出 Markdown + JSON 评估卡。

```bash
# 静态策略评估卡（打印 Markdown）
PYTHONPATH=src python3 -m qlab.cli card --symbol DEMO

# 模型方向 + Walk-Forward 主口径，写出 md+json 到 artifacts/
PYTHONPATH=src python3 -m qlab.cli card --symbol DEMO --model --walk-forward --out-dir artifacts
```

口径常量（P、门禁阈值如年化 50%/回撤 20%/分年度 35%/滚动达标 70% 等）固定在 `config.MetricConfig` 与 `config.GateConfig`，与 v1.0 一致。**fixture 数据下门禁结论仅证明「计算与判定逻辑可运行」，不代表任何策略达标。**

## 目录结构

```
quant-skeleton/
├── pyproject.toml          # 打包；core 无依赖，[analysis]/[moomoo]/[dev] 为可选 extras
├── requirements.txt        # 说明：core 零依赖
├── .env.example            # 所有可配项 + moomoo 密钥占位（拷为 .env 填写）
├── Makefile                # make build / test / lint / check / demo / report
├── conftest.py             # 让 pytest 免安装找到 src/
├── fixtures/DEMO.csv       # 样例行情（CSV，3 年日线）
├── src/qlab/
│   ├── config.py           # 配置加载（env > overrides > 默认；密钥仅来自 env）
│   ├── data/{base,fixture}.py
│   ├── strategy/{base,sma_cross}.py
│   ├── strategy/plugin.py            # 候选策略插件接入点 (quant-strategies)
│   ├── backtest/{engine,walk_forward}.py   # 回测引擎 + Walk-Forward 主口径
│   ├── model/{base,momentum}.py
│   ├── brokers/guardrails.py         # 安全栏杆: 急停/限频/脱敏/重连
│   ├── brokers/moomoo.py             # moomoo OpenD 真实适配 (quote/account/持仓/下单/撤单/查单)
│   ├── execution/{signals,broker,risk,engine,session,moomoo_broker}.py  # 执行层 + 风控
│   ├── metrics/{core,trades,gates}.py   # v1.0 §2 指标 + §3 四关 (纯函数, 逐项单测)
│   ├── report/{metrics,report}.py        # 旧版简报
│   ├── report/evaluation_card.py         # v1.0 评估卡组装/渲染 (B/C/D/E)
│   ├── pipeline.py         # run_backtest / train_and_backtest / evaluate_candidate
│   └── cli.py              # python -m qlab.cli {backtest,train,report,card,execute}
└── tests/                  # 131 用例: 链路 + 指标门禁 + 安全栏杆 + 执行层风控 + 插件
```

## 安装依赖

核心引擎**无需安装任何第三方包**。只在需要时装可选层：

```bash
# 开发自检工具（pytest + ruff）
pip install -e ".[dev]"
# 真实数据分析便捷层（可选）
pip install -e ".[analysis]"     # pandas / numpy
# moomoo US OpenD 实盘对接（可选）
pip install -e ".[moomoo]"       # futu-api
```

不安装包也能直接用：设 `PYTHONPATH=src` 即可（见下）。

## 跑回测 / 出报告（fixture，离线）

```bash
# 1) 跑一条 SMA 交叉回测，打印指标
PYTHONPATH=src python3 -m qlab.cli backtest --symbol DEMO

# 2) 训练 fixture 模型 → 持久化 → 回测（演示 train/save/load 闭环）
PYTHONPATH=src python3 -m qlab.cli train --symbol DEMO --model-out artifacts/DEMO_momentum.json

# 3) 出报告（Markdown + JSON 写到 artifacts/）
PYTHONPATH=src python3 -m qlab.cli report --symbol DEMO --out-dir artifacts
```

或用 Makefile：`make demo` / `make report`。

数据来源优先级：`fixtures/<symbol>.csv` 若存在则读 CSV，否则回退到确定性合成序列（带种子，可复现）。

### 在代码里用

```python
from qlab.pipeline import run_backtest
out = run_backtest("DEMO")          # 默认 FixtureDataSource + SmaCrossStrategy
print(out.metrics.annualized_return, out.metrics.max_drawdown)
```

## moomoo US OpenD 适配层（`qlab.brokers.moomoo`，真实实现 + 安全栏杆）

`qlab/brokers/` 把 OpenD 接线从骨架推进到真实实现：`MoomooQuoteSource`（历史 K 线 → `Bar`，
喂进回测链路）和 `MoomooTradeGateway`（连接/解锁/查资产/下单）。`futu` 懒加载，导入 qlab 不需要它。

**安全栏杆是硬要求（`qlab/brokers/guardrails.py`），任一缺失视为未完成：**

| 栏杆 | 实现 |
| --- | --- |
| 凭据只走环境变量 | `MoomooConfig`（`MOOMOO_*`）；源码零写死，旧仓写死密码已移除 |
| 自动交易默认关闭 | `MOOMOO_ALLOW_ORDERS=false` 默认；下单前 `_preflight_order` 校验 |
| 全局急停 | `KillSwitch`（进程标志 + 哨兵文件 + 环境变量，fail-safe）；`gateway.emergency_stop()` 触发并撤单 |
| 模式隔离 SIMULATE/REAL | `trade_env` + REAL 二次闸门 `MOOMOO_ALLOW_REAL` + 必须有 `MOOMOO_UNLOCK_PWD` 并解锁成功 |
| 日志脱敏 | `mask_secret()`；账户/密码/订单号一律掩码 |
| 限频 | `RateLimiter`（滚动窗口，默认 30 笔/30s） |
| 连接异常重连/降级 | `call_with_retry`（退避重试），最终失败 fail-safe 不下单 |

接实盘：`pip install -e ".[moomoo]"` → 启动本地 OpenD → `cp .env.example .env` 按其中 `MOOMOO_*`
填好（含 `MOOMOO_ENABLED=true` 及需显式打开的 `MOOMOO_ALLOW_ORDERS`/`MOOMOO_ALLOW_REAL`）→ 即可联通。
单测用注入的 fake context 覆盖了全部栏杆与下单/撤单/解锁路径，无需 SDK 或真实网关即可跑。

> 接入任何其它行情源：实现 `DataSource._fetch` 即可，回测/报告链路无需改动。

## 候选策略插件接入点（`qlab.strategy.plugin`，预留给 quant-strategies）

骨架可把外部候选（如 `quant-strategies`）作为**插件**接入并复跑，只需符合现有 `Strategy` 接口：

- `load_strategy("package.module:Attr", **params)` —— 解析外部包里的 Strategy 类/实例/工厂。
- `FunctionStrategy(name, fn)` —— 包装一个 `bars -> list[float]` 的权重函数。

> 注：当 quant-strategies 作为**用户已有研究成果走实盘落地**时（EVO-13 现口径），走下面的执行层
> 接入（signal handoff），**不重跑历史回测**；只做轻量核对。上面这条 `evaluate_candidate` 复核仅在把
> 外部代码当「新候选方向」时才用。

## 执行层（`qlab.execution`）— signals → 风控 → 券商（paper / live）

把研究侧的策略信号落到**可观测/可控/可审查**的执行层。接入边界是一个轻量的 **signal handoff**
（`fixtures/signals.json` 的目标权重列表），**不在执行层重跑回测**；只做轻量 sanity 核对
（`sanity_check`：权重范围、是否超 `max_positions`、gross、是否在 universe 内）。

- `execution/signals.py` —— `TargetSignal` / `SignalSet` / `load_signals` / `sanity_check`
- `execution/broker.py` —— `Broker` 抽象 + `PaperBroker`（确定性模拟成交，paper/dry-run 默认venue）
- `execution/risk.py` —— `RiskManager` 风控硬栏杆
- `execution/engine.py` —— `ExecutionEngine`：对账目标权重 → 逐单过风控 → 路由券商 → `RunRecord`
- `execution/moomoo_broker.py` —— 把 `MoomooTradeGateway` 适配成 `Broker`（live 模式，默认不走）

**执行默认安全**：模式 `dry_run`（只算不下单）/ `paper`（模拟成交，默认）/ `live`（真实 OpenD，需显式）。

**风控硬栏杆（EVO-13 §4，缺一视为未完成）** —— 全部在 `RiskManager` + broker 层：

| 栏杆 | 落点 |
| --- | --- |
| 凭据只走环境变量，仓库零 key | `MoomooConfig`（`MOOMOO_*`）；`.env` 已 gitignore |
| 全局 kill switch | `brokers.guardrails.KillSwitch`（进程+文件+env），风控/券商双重检查 |
| 仓位上限 | 单标的权重上限 + gross 上限 + `max_positions` |
| 日内损失阈值 | 触发即停新开仓（仍允许减仓/平仓） |
| 20% 回撤熔断 | 峰值-谷值回撤 ≥20% 锁定停机 |
| 异常行情停机 | 单 bar 异常波动 / 行情过期 → 停机 |
| 日志脱敏 | `mask_secret()` |
| 限频 / 连接重连降级 | `RateLimiter` / `call_with_retry` |

注：halt 只挡**加仓**，始终放行**减仓/平仓**以便去风险。

```bash
# paper 跑通（离线，marks 取自 fixture 行情）
PYTHONPATH=src python3 -m qlab.cli execute --signals fixtures/signals.json --mode paper
# 只算不下单
PYTHONPATH=src python3 -m qlab.cli execute --mode dry_run
```

> ⚠️ live 模式真实下单默认关闭，且依赖外部资源（真实/模拟盘 key、OpenD 权限、账户授权）——这些是
> **blocker**，已在 issue 列清，未自行 mock 充数。本轮验证只到 paper / dry-run。

## 自检（build / test / lint）

```bash
make check          # = build + test + lint
# 或分开：
make build          # py_compile 全部源码
make test           # python -m unittest discover -s tests -t .   （29 用例，零依赖）
make lint           # ruff check（需 pip install ruff）
# pytest 亦可（已配置 pythonpath）：python -m pytest
```

## 待补资源 / 后续

- 项目当前**未绑定 GitHub repo / 本地目录**：本骨架落在 workspace 的 `quant-skeleton/`。若要纳入版本管理或长期持久化，请提供目标 repo / 目录。
- 真实美股日线 / 分钟线行情源（moomoo OpenD 账户或其它数据供应商）。
- 候选策略与户部对收益口径的精确定义（无风险利率、交易日历、费率档位等），便于把 fixture 替换为正式实现。
