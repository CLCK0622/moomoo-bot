# EVO-8 (b) 残差动量 首轮回测 — verdict: **REJECTED_cost (NEGATIVE)**

判定经 `research/gate.certify()`（未自建门）。preregistration_commit `dbc032b`。

## 结论
- **REJECTED_cost**：成本 ×1 净 Sharpe = **−0.001**（≤0）→ 在**最便宜的成本早筛门**即被淘汰，
  根本没走到 CAGR/MDD/DSR。×2 Sharpe = −0.011。声明 family 4 格的 ×2 年化 Sharpe 全负
  （−0.167 / −0.163 / −0.377 / −0.53）。
- 直白说：残差动量在这套大盘宇宙、周频、十分位 market-neutral long-short 上，**毛边≈0，
  扣 10bps/side 佣金 + 借券 + 2× 融资后无正的风险调整收益**。与 residual reversal（EVO-162）
  同为负向——这类特质 stat-arb 的薄边被零售成本吃掉。

## 工程健康（证明不是 bug 导致的负向）
- 646 周再平衡；均 22.5 名/腿（min 21，**非 thin-book**，> 20 硬门）；β 中性（|净β| 0.003）；
  gross 上限 2.0×；window 2006-06→2026-07（前 ~3yr E+F+skip warmup 为现金）。
- 反前视：权重 close(T) 决定、open(T+1) 执行；per-stock betas 窗口 ≤ 决策周（无未来）。3/3 单测绿。

## 纪律
- **不自建门**：净收益直灌 `certify()`；官方/影子/DSR/成本/容量门全在门里。
- **诚实 N（工部规矩#1）**：N 取自 `TrialLedger.cumulative_n()` = 4（本轮 family 全登记，无隐藏挖矿），
  trial Sharpes 全量吐给 DSR。跨轮累计真 N 由户部共享台账维护。
- **三值处理（工部规矩#2）**：本例是 `REJECTED_cost`（硬门拒绝，非 FAIL）——metrics 门未运行，
  故无 `shadow_floor_pass` 可言（连成本门都没过，谈不上兜底带）。NEGATIVE，随轮回流。
- 预注册 `dbc032b` 先于结果 commit，git 时序可核。

## 复跑
```
python -m qlab.swing.run_residmom --prereg-commit dbc032b   # py312 venv; 需 research/gate 在 path
python tests/test_residmom.py                                # 3/3
```
