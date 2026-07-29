"""
seed_ledger.py —— 补种全项目唯一共享试验台账的**历史基线**（家族错误率下限）。

跑法（repo 根）：  python3 -m research.gate.seed_ledger

幂等：只补缺失的历史条目（按 run_id 去重），不覆盖后续管线登记的真实轮次。
数值为**保守下限**——门只保证 cumulative_n 不低于此；待都察院/工部据实上调。
没有这个基线，多因子 Alpha158 走到 DSR 时 N 会被低估成"只有本轮"，等于把抓伪 alpha 的
haircut 关掉（工部 2026-07-29 实测）。此文件须入库。
"""
from research.gate.trial_ledger import DEFAULT_LEDGER_PATH, TrialLedger

# 每条给 run_id / 全量试验数 n_trials_total（下限）/ 说明。
SEED = [
    dict(run_id="pre_gate_manual_history", source="manual", n_trials_total=9, n_evaluated=9,
         note="门存在前已证伪的 9 个独立方向：VIX / EVO-158 中性套利 / earnings / swing P1 / "
              "C1 残差反转 stat-arb / 8 腿 TSMOM crisis / crisis-sleeve 组合 EVO-204·238 / "
              "高收益基金复制 / X 预测市场跨场套利。下限——方向内子试验未逐一记录；待核实上调。"),
    dict(run_id="gem_firstround", source="manual", n_trials_total=1, n_evaluated=1,
         note="GEM 规则型择时配置，负向盖棺（未走 DSR 路径，计 1 个假设）。"),
    dict(run_id="residmom_evo162_r1", source="qlib", n_trials_total=4, n_evaluated=1,
         note="残差动量首轮，负向 REJECTED_cost，盖棺（工部核实 N=4）。"),
]


def main():
    led = TrialLedger(DEFAULT_LEDGER_PATH)
    before = led.cumulative_n()
    for s in SEED:
        led.register_run(now_iso="2026-07-29T00:00:00Z", **s)
    print(f"canonical ledger: {DEFAULT_LEDGER_PATH}")
    print(f"cumulative_n: {before} -> {led.cumulative_n()}  ({len(led.runs)} runs)")


if __name__ == "__main__":
    main()
