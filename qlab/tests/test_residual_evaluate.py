"""EVO-162 C1 ADDENDUM B (short-leg risk口径) report disclosures — unit tests.

B1 single-sector net-exposure diagnostic (monitor-only, flag >10% gross, never enforced), B2
honest +25%-stop relabel, B3 gap-risk note — all carried on the report by residual_evaluate.
"""
import numpy as np
import pandas as pd

from qlab.swing.residual_evaluate import (B2_SHORT_STOP_DISCLOSURE, B3_GAP_RISK_NOTE, _cell,
                                          _sector_net_exposure, build_residual_report)
from qlab.swing.residual_signals import FACTOR_ETFS


def _series(n, drift, seed, start="2006-01-02"):
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range(start, periods=n)
    close = 50.0 * np.cumprod(1.0 + rng.normal(drift, 0.012, n))
    return pd.DataFrame({"date": dates, "open": close * (1.0 + rng.normal(0.0, 0.002, n)),
                         "close": close})


# --------------------------------------------------------------------------- #
# B1 — single-sector net exposure (monitor-only diagnostic)
# --------------------------------------------------------------------------- #
def test_b1_sector_net_exposure_measured_and_flagged():
    # day 0: TECH net = +2, FIN net = -2, gross = 4 ⇒ each sector |net|/gross = 0.5 (> 10% ⇒ flag)
    wdf = pd.DataFrame({"date": pd.bdate_range("2020-01-01", periods=2),
                        "AAA": [1.0, 0.0], "BBB": [1.0, 0.0],      # TECH
                        "CCC": [-1.0, 0.0], "DDD": [-1.0, 0.0]})   # FIN
    sec = {"AAA": "TECH", "BBB": "TECH", "CCC": "FIN", "DDD": "FIN"}
    d = _sector_net_exposure(wdf, sec)
    assert d["measured"] is True
    assert abs(d["realized_max_single_sector_net_frac_gross"] - 0.5) < 1e-9
    assert d["breaches_10pct_flag"] is True
    assert d["cap_enforced"] is False                 # MONITOR-ONLY, never enforced
    assert d["sector_map_coverage"] == 1.0
    assert d["threshold_frac_gross"] == 0.10


def test_b1_no_breach_when_sector_balanced():
    # each sector is internally long+short balanced ⇒ net ≈ 0 ⇒ no breach
    wdf = pd.DataFrame({"date": pd.bdate_range("2020-01-01", periods=2),
                        "AAA": [1.0, 1.0], "BBB": [-1.0, -1.0],    # TECH net 0
                        "CCC": [1.0, 1.0], "DDD": [-1.0, -1.0]})   # FIN net 0
    sec = {"AAA": "TECH", "BBB": "TECH", "CCC": "FIN", "DDD": "FIN"}
    d = _sector_net_exposure(wdf, sec)
    assert d["realized_max_single_sector_net_frac_gross"] < 1e-9
    assert d["breaches_10pct_flag"] is False


def test_b1_unmeasured_without_sector_map():
    wdf = pd.DataFrame({"date": pd.bdate_range("2020-01-01", periods=2),
                        "AAA": [1.0, 0.0], "BBB": [-1.0, 0.0]})
    d = _sector_net_exposure(wdf, None)
    assert d["measured"] is False
    assert d["monitor_only"] is True
    assert "UNMEASURED" in d["note"] and "OpenD-only" in d["note"]


def test_b1_partial_sector_map_coverage_reported():
    wdf = pd.DataFrame({"date": pd.bdate_range("2020-01-01", periods=1),
                        "AAA": [1.0], "BBB": [-1.0], "CCC": [0.5], "DDD": [-0.5]})
    sec = {"AAA": "TECH", "BBB": "TECH"}               # only 2/4 mapped
    d = _sector_net_exposure(wdf, sec)
    assert d["symbols_mapped"] == 2 and d["symbols_total"] == 4
    assert d["sector_map_coverage"] == 0.5


# --------------------------------------------------------------------------- #
# B2 / B3 — disclosure strings carried on EVERY report branch
# --------------------------------------------------------------------------- #
def test_b2_b3_disclosure_content():
    assert "weekly-hold" in B2_SHORT_STOP_DISCLOSURE
    assert "not active in this SIMULATE run" in B2_SHORT_STOP_DISCLOSURE
    assert "cannot be claimed as an active tail limit" in B2_SHORT_STOP_DISCLOSURE
    assert "LIVE-EXECUTION OVERLAY" in B2_SHORT_STOP_DISCLOSURE
    assert "live-transition" in B3_GAP_RISK_NOTE
    assert "锦衣卫" in B3_GAP_RISK_NOTE and "review" in B3_GAP_RISK_NOTE
    assert "2.5% NAV" in B3_GAP_RISK_NOTE


def test_addendum_b_block_present_in_data_insufficient_branch():
    """Even the数据不足-无法评估 factor-gap branch must carry B2/B3 (锦衣卫 prerequisite: never drop)."""
    stocks = {f"S{i:02d}": _series(300, 0.0002, i) for i in range(5)}
    rep = build_residual_report(stocks, {"SPY": _series(300, 0.0003, 99)}, list(stocks), n_boot=30)
    assert rep["overall_verdict"] == "数据不足-无法评估"
    ab = rep["addendum_b"]
    assert ab["B2_short_stop"] == B2_SHORT_STOP_DISCLOSURE
    assert ab["B3_gap_risk"] == B3_GAP_RISK_NOTE
    assert ab["B1_single_sector_net_exposure"]["computed"] is False   # no run ⇒ not computed
    assert "conditional PASS" in ab["short_leg_review"]


def test_cell_attaches_sector_diagnostic():
    """A runnable primary cell carries its own B1 sector diagnostic (monitor-only)."""
    stocks = {f"S{i:02d}": _series(1100, 0.0002, i) for i in range(30)}
    factors = {s: _series(1100, 0.0003, 500 + k) for k, s in enumerate(FACTOR_ETFS)}
    sectors = {f"S{i:02d}": ["TECH", "FIN", "HEALTH"][i % 3] for i in range(30)}
    spec = {"formation_weeks": 1, "estimation_weeks": 156, "cut": 0.10, "factor_set": "3f"}
    cell = _cell(stocks, factors, list(stocks), spec, P=252, alpha=0.05, n_boot=30, seed=1,
                 sectors=sectors)
    assert "sector_net_exposure" in cell
    b1 = cell["sector_net_exposure"]
    assert b1["measured"] is True and b1["cap_enforced"] is False
    assert 0.0 <= b1["realized_max_single_sector_net_frac_gross"] <= 1.0
