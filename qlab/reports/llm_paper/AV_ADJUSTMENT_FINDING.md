# 价格腿的公司行为口径：AV `TIME_SERIES_DAILY` 实测 = **as-traded（分红未回溯复权）**

核实项由工部尚书 2026-08-27 提出（吏部 BIL 裁定同批）：**只出结论与量级，不改任何轮内代码。**
本文件即结论；复跑脚本 `qlab/tools/check_av_adjustment.py`（`--dry-run` 可先看要花什么）。

背景：本轨对公司行为**零处理**——`qlab/qlab/llm_paper/` 零 parquet 引用，`quotes_api.py` 全文
`split|adjust|dividend` 命中 0，而 `qlab/data/quotes_api_provenance.json` 记了 endpoint / 覆盖 /
预算 / fail-closed / 日历 / 配额 / key 泄漏 / 配额分歧，**唯独没提复权**。

## 一、分红：**已实测，AV 未复权**（决定性）

1 次调用（`purpose=exploration`，2026-08-27 当日额度，与 08-31 的 UTC 日桶无关）。
拿 AV 的 SPY 与仓内 `qlab/data/gem/SPY_1d.parquet`（OpenD K_DAY **qfq**，
`rate_carry_provenance.json:treasury_etf_bars.adjustment_basis` 断言 split+dividend 复权）
在重叠区间逐日比 `close`：

```
AV TIME_SERIES_DAILY(SPY, compact)  2026-04-06 → 2026-08-26  (100 行)
重叠区间  2026-04-06 → 2026-07-27  (78 个交易日)

比值 av/pq   首 1.002576   末 1.000000   全窗极差 25.8 bps
台阶（日变动 > 5 bps）：1 处
    2026-06-18  ratio 1.000000  跳 -25.7 bps
累计收益差   -0.289 个百分点
```

**读法**：qfq 以 parquet 自己的末日为锚，故比值末日 = 1。往前只有**一处**台阶，正落在
SPY 六月除息日 `2026-06-18`，幅度 −25.7 bps ≈ 当次股息率；其余 77 天比值恒定到基点级。
⇒ **AV 未把分红回溯进历史价格**，仓内 qfq 序列则复权了，两者差的就是那一次分红。

**对本轨的影响**：持仓期股息**一律丢失**。方向**朝严**（系统性低估收益，不可能造成 50/20 假过），
量级 ≈ 标的股息率：SPY 约 1.1–1.2%/yr，个股 0–4%/yr 不等。在 50% 官方门前不改结论，
但在 §4 下四分位与影子线 15–20% 上不是噪音。

## 二、拆股：**未测出，方法在免费档不可用**

原计划用 `AAPL --outputsize full`（2006→今，含 2014 年 7:1 与 2020 年 4:1 两次拆股；仓内
`daily_full/AAPL_1d.parquet` 实测已复权：2020-08-27 close 121.26、2020-08-31 125.17，跨拆股平滑）。
实跑被供应商挡下：

```
AAPL: Information (daily throttle): Thank you for using Alpha Vantage!
The outputsize=full parameter value is a premium feature for the TIME_SERIES_DAILY endpoint.
```

即**这把免费 key 上 `outputsize=full` 是付费功能**，`compact` 约 100 个交易日的窗口里通常没有拆股，
所以这条路测不了。**结论：分红口径已定，拆股口径仍未知。**

**要补测的话，1 次调用即可**：找一个**拆股日落在最近约 100 个交易日窗口内**、且仓内
`data/daily_full/` 有 qfq parquet 的标的，跑
`python3 qlab/tools/check_av_adjustment.py --symbol <SYM>`——比值在拆股日会出现**数量级**的台阶
（如 4:1 拆股 ⇒ 约 +300%），与分红那种 20–30 bps 完全不会混淆。本轮没有已知的这样一个标的，
故未猜、未多花调用。

**风险仍在，且这一半才是危险的那半**：若 as-traded，持仓周内遇拆股 ⇒ 价格跳变而 `shares` 不变
⇒ 该格当轮读数是假的，**方向不定、量级可达数十个百分点**；若回溯复权，则同一格跨轮的 round JSON
落在不同价格标尺上，拼出的净值序列在拆股处假跳。两种都不好，且**当前实现对两者都不设防**。

### 更好的答法：**批次 1 的 bar 归档会顺带回答它，不必再等运气**

工部尚书 2026-08-27 指出的路子，比上面那个「找一个拆股落在窗内的标的」干净得多：批次 1
（硬期限 2026-10-31，见 `EXECUTOR_CHANGE_NOTE.md` §8.3）要把每轮取到的 bars **append-only 归档**
（内容哈希 + 取数时点，规矩照 BIL parquet 那套）。归档之后，**把当时归档的值与日后重取的值一比，
复权口径自己就现形了**：

* 若 AV 回溯复权 ⇒ 同一 `(symbol, date)` 的历史值会**随后来的公司行为被改写**，两次取数对不上；
* 若 as-traded ⇒ 历史值永不改写，两次取数逐位相同。

这条不挑标的、不等拆股撞进窗口、零额外配额（用的是本来就要取的那批 bars），而且它**顺带就是**
归档层自己的完整性校验。上面那个「1 次调用找拆股标的」降级为可选的提前验证手段。

## 三、顺带一处供应商信息被误分类（无轮内暴露，仅记录）

上面那次 premium 拒绝被 `quotes_api._check_throttle` 归成**日配额节流**，并进一步升级为
`QUOTA_DIVERGENCE`（`ledger_remaining=8, vendor_throttled=True`）——而它其实是「功能需付费」，
与配额、与 key 是否被盗用都无关。真发生在轮内会落一份 `ALERT_quota_divergence_*.json`，
把人引向都水的「停用这把 key + 切换退路供应商」预案。

**轮内无暴露**：本轨取数一律 `outputsize=compact`（`quotes_api.fetch_daily` 默认值，
`get_daily_closes` 未覆写），这条触发路径在轮内走不到。故只记录、不改——**08-31 轮内一行不改**。

---

本文件不改任何轮内代码、不进符号并集、不进配额、不动冻结。动不动由吏部定。
