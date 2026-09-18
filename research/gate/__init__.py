"""
research.gate —— EVO-149 冻结验收门（户部门禁护栏）

给 Qlib / RD-Agent 试跑管线接线用的**验收门**。三工具只当假设生成器，
验收权 100% 留在这里；工具自带回测永不作接受判据。

典型用法（工部的管线里）：

    from research.gate import certify, Candidate, TrialLedger, OOSBudget, GateThresholds
    from research.gate import freeze_config

    ledger = TrialLedger("research/gate/state/trial_ledger.json")
    ledger.register_run("qlib-alpha158-run1", source="qlib",
                        n_trials_total=158, n_evaluated=3,
                        trial_sharpes=[...])           # 必须吐全量 N

    cfg = {"universe": [...], "leverage_cap": 2.0, "signal_params": {...},
           "rebalance": "monthly", "cost_model": "moomoo_retail_x1",
           "train_test_split": "2019-12-31", "gate_thresholds": "50/20+shadow"}
    fhash = freeze_config(cfg)                          # 跑前冻结

    cand = Candidate(name="dual_momentum", oos_net_returns=oos_r, oos_dates=oos_d,
                     gross_returns=g, turnover=to, cost_per_turnover=0.0005,
                     prereg_config=cfg, frozen_hash=fhash,
                     economic_rationale="动量溢价：横截面/时序趋势的行为与风险解释……",
                     trial_sharpes=[...])
    verdict = certify(cand, ledger=ledger, oos_budget=OOSBudget(max_evals=1))
    print(verdict.summary())
    # verdict.certified==True 且 decision in {REPORT_5020, DECISION_POINT} 才回报首辅。
"""
from .cost_capacity import (COST_MODELS, CapacityResult, CostStressResult,
                            apply_costs, capacity_gate, cost_stress_gate,
                            resolve_cost_per_turnover)
from .deflated_sharpe import (DSRResult, deflated_sharpe_ratio,
                              expected_max_sharpe, probabilistic_sharpe_ratio)
from .capital_efficiency import (CapEffReport, EventExposureSpec, ExposureCheck,
                                 capital_efficiency_report,
                                 realized_exposure_fraction, verify_exposure)
from .gate import Candidate, Verdict, certify
from .llm_paradigm import (AdmissibilityCheck, AttributionReport,
                           ContaminationError, LLMParadigmVerdict, SeedReport,
                           admissibility_check, prescreen, seed_distribution,
                           style_attribution, trials_from_seeds,
                           validate_decision_log)
from .metrics import (DEFAULT_CRISIS_WINDOWS, GateThresholds, MetricsReport,
                      cagr, evaluate, joint_gate, max_drawdown, mar, sharpe)
from .prereg import (economic_rationale_gate, freeze_config,
                     validate_prereg_completeness, verify_unchanged)
from .trial_ledger import (DEFAULT_LEDGER_PATH, HonestyError, RefreezeError,
                           RunRecord, TrialLedger, project_ledger)
from .walk_forward import (DEFAULT_OOS_BUDGET_PATH, OOSBudget, OOSBudgetExceeded,
                           cpcv_splits, project_oos_budget,
                           walk_forward_splits)

__all__ = [
    "certify", "Candidate", "Verdict",
    "TrialLedger", "RunRecord", "HonestyError", "RefreezeError",
    "project_ledger", "DEFAULT_LEDGER_PATH",
    "project_oos_budget", "DEFAULT_OOS_BUDGET_PATH",
    "GateThresholds", "MetricsReport", "evaluate", "joint_gate",
    "cagr", "max_drawdown", "sharpe", "mar", "DEFAULT_CRISIS_WINDOWS",
    "deflated_sharpe_ratio", "probabilistic_sharpe_ratio",
    "expected_max_sharpe", "DSRResult",
    "cost_stress_gate", "capacity_gate", "apply_costs",
    "resolve_cost_per_turnover", "COST_MODELS",
    "CostStressResult", "CapacityResult",
    "freeze_config", "verify_unchanged", "validate_prereg_completeness",
    "economic_rationale_gate",
    "walk_forward_splits", "cpcv_splits", "OOSBudget", "OOSBudgetExceeded",
    "capital_efficiency_report", "EventExposureSpec", "verify_exposure",
    "realized_exposure_fraction", "CapEffReport", "ExposureCheck",
    "admissibility_check", "validate_decision_log", "seed_distribution",
    "trials_from_seeds", "style_attribution", "prescreen",
    "AdmissibilityCheck", "SeedReport", "AttributionReport",
    "LLMParadigmVerdict", "ContaminationError",
]

# 便捷别名，供管线：project_oos_budget()。RefreezeError 从 trial_ledger 暴露。
