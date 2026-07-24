# prediction_markets —— 预测市场只读数据接入（Kalshi / Polymarket / Limitless）

EVO-8「理财方向探索」方向 X 的执行模块：三家预测市场的**只读**行情接入、跨 venue
价差监测、纸面套利回测。对齐 quant **SIMULATE-only** 基线——**全模块无任何下单 /
入金 / 提现 / 撤单路径**（`tests/test_readonly_guard.py` 静态强制这一不变量）。

## 一句话结论（已实测）

- **Kalshi 生产行情 GET 端点（markets / orderbook / trades / events）完全公开、无需鉴权**
  ——已实测无凭证 `HTTP 200`。**拉真实生产价格无需注册、无需 KYC、无需 SSN**，合规红线
  在数据获取环节根本不会触发。
- Kalshi **WebSocket** 连接必须 RSA-PSS 鉴权（无凭证实测 `401`），即使只订阅公开频道；
  故实时流需要一个账户 API key。REST 已能拿真实价，WS 只是「更低延迟」的加分项，不在
  套利研究关键路径上。
- Polymarket（Gamma + CLOB）、Limitless 行情均公开只读。

## 目录

| 文件 | 作用 |
|---|---|
| `config.py` | 基址、费率、只读开关 |
| `models.py` | 统一行情模型 `Quote` / 套利 `ArbEdge`（价格统一归一到 0~1 美元概率价） |
| `fees.py` | 各 venue 手续费/结算模型（Kalshi `ceil(0.07·P·(1-P))`、Poly 0、Limitless 可配置） |
| `kalshi_auth.py` | Kalshi RSA-PSS 请求签名（仅 WS 只读会话用；`cryptography` 惰性导入） |
| `kalshi_client.py` | Kalshi 公开 REST 只读客户端（`*_dollars`/`*_fp` 新旧字段双口径） |
| `kalshi_ws.py` | Kalshi WS 只读客户端（频道白名单强制、断线重连；需 API key） |
| `polymarket_client.py` | Polymarket Gamma+CLOB 只读客户端 |
| `limitless_client.py` | Limitless 只读客户端（`limit≤25` 分页） |
| `event_matcher.py` | 跨 venue 同事件**候选**匹配（Jaccard+结算时间；仅建议，需人工确认） |
| `arb.py` | 跨 venue 二元套利净额（扣费扣结算）与方向择优 |
| `spread_monitor.py` | 拉取→对齐→算净边的编排 |
| `arb_backtest.py` | 对采集快照做纸面回测（净边>0 占比、均值、费率敏感性） |
| `run_spread_monitor.py` | CLI：拉一次/循环采集，打印价差报告 |
| `run_backtest.py` | CLI：对 `data/` 快照做回测 |
| `smoke_test.py` | 在线冒烟：验证三家公开 REST 可拉真价（零凭证） |
| `mappings/curated_pairs.json` | 人工确认的同事件映射（进回测的唯一入口） |

## 快速开始

```bash
pip install -r prediction_markets/requirements.txt   # 仅 REST/回测: requests pandas numpy

# 1) 冒烟：三家公开 REST 拉真实行情（零凭证、零真金）
python -m prediction_markets.smoke_test

# 2) 跑一次跨 venue 价差报告（并存快照供回测）
python -m prediction_markets.run_spread_monitor --save

# 3) 采集时间序列（例：每 5 分钟一次，跑一天）后回测
python -m prediction_markets.run_spread_monitor --save --loop 300 --count 288
python -m prediction_markets.run_backtest

# 4) 单元测试（无需 pytest）
python -m prediction_markets.tests.run_all
```

## Kalshi WS（需 API key，仅只读行情）

REST 已能拿真实生产价；WS 仅用于低延迟流。启用时：

```bash
# .env（严禁入库；.gitignore 已覆盖）
KALSHI_API_KEY_ID=<账户设置里生成的 key id>
KALSHI_PRIVATE_KEY_PATH=/abs/path/to/kalshi_private_key.pem
```

`kalshi_ws.stream(tickers, channels=["ticker","trade"])` 只允许订阅行情白名单频道
（`ticker/trade/orderbook_delta/market_lifecycle_v2`），任何私有/写频道会被直接拒绝。

## 合规边界（硬性）

1. **只读到底**：不下单、不入金、不提现、不撤单。代码里不存在这些路径，静态测试强制。
2. **生产数据零 KYC**：真实价格走公开 REST，不触碰美国 SSN/身份。**不伪造任何身份信息**。
   若未来确需 WS 而账户注册卡在 SSN/无法如实提供的 KYC → **立即停手上报**，不硬闯。
3. Kalshi WS 的 RSA-PSS 会话仅用于订阅公开行情。

## 套利研究的现实警示（务必读）

跨 venue「净边为正」**不等于**可套利。名义价差绝大多数来自：
1. **结算口径错位**：同名事件的结算源/窗口/四舍五入不同（例：BTC 方向市场，Limitless 用
   Chainlink、Polymarket 用自家 oracle；窗口/起始参考价也不同）→ 是**基差风险**不是无风险套利。
2. **参考价 vs 可成交价**：Limitless `prices`、Polymarket Gamma 顶层价是参考/中间价，
   非即时可成交 ask；用它算的边被高估（代码在 `ArbEdge.notes` 标注）。
3. **深度不足 / 报价陈旧**：小盘合约买一压不深，滑点吃掉边。
4. **费用与资金锁定**：赢方到期才结算，资金跨日/周锁定，年化需按持有期折算；且跨 venue
   资金（Kalshi 美元 vs Poly/Limitless 链上 USDC）不能互相净额，实为「库存型」双边持仓。

实测（2026-07-24 早）：三家当前同事件干净重叠极薄；即便挑出同窗口 BTC 方向配对，
最优「净边」在扣一个 1% 量级手续费后即归零——**未发现干净的无风险跨 venie 套利**。
要判定任何真实边，必须：①`curated_pairs.json` 人工确认结算等价 ②两边都用订单簿可成交
ask（`--poly-books`）③计入费用+持有期+基差。本模块把这些约束都做成了硬闸。
