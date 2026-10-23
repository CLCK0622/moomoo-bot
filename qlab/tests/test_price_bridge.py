"""桥接：actual_start 由都水 quotes_api 观测到的真实交易日回填（不重实现价格腿）。"""
from __future__ import annotations
import pandas as pd, pytest
from qlab.events.datafetch.quotes_api import DailyBar
from qlab.llm_paper.decision_chain import build_decision
from qlab.llm_paper.price_bridge import settle_actual_start

ET = "America/New_York"
def _bar(sym, d, c=100.0):
    return DailyBar(symbol=sym, date=d, close=c, open=c, high=c, low=c, volume=1.0,
                    source="alphavantage", retrieved_utc="2026-08-08T00:00:00+00:00")
def _ev(ts): return {"source_time_utc": pd.Timestamp(ts, tz=ET).tz_convert("UTC").isoformat(), "ref_id": "r1"}

# 当日/近日证据必须带 observed_days（价格腿观测到的真实交易日），否则陈旧 SPY 日历会 fail-closed
OBS = ["2026-08-05", "2026-08-06", "2026-08-07", "2026-08-10"]

def _decision(dts="2026-08-06 15:00"):
    return build_decision(symbol="AAPL", target_weight=0.05, confidence=0.6, thesis="t",
                          evidence_records=[_ev("2026-08-06 14:00")],
                          decision_ts=pd.Timestamp(dts, tz=ET), seed=11, prompt_variant="pv1_baseline",
                          observed_days=OBS)

def test_actual_start_filled_from_observed_bars():
    d = _decision()                            # intended = 2026-08-07 09:30 ET
    out = settle_actual_start([d], {"AAPL": [_bar("AAPL", "2026-08-07"), _bar("AAPL", "2026-08-10")]})
    assert out["settled"] == 1 and out["pending"] == 0
    assert d.actual_start.startswith("2026-08-07") and d.actual_start_rolled_days == 0

def test_actual_start_rolls_when_intended_day_has_no_bar():
    d = _decision()                            # intended 08-07；价格腿只有 08-10 → 顺延
    out = settle_actual_start([d], {"AAPL": [_bar("AAPL", "2026-08-10")]})
    assert out["settled"] == 1 and d.actual_start.startswith("2026-08-10")
    assert d.actual_start_rolled_days == 3 and "顺延" in d.actual_start_reason

def test_pending_when_price_leg_has_no_forward_bar():
    d = _decision()
    out = settle_actual_start([d], {"AAPL": [_bar("AAPL", "2026-08-05")]})   # 全在 intended 之前
    assert out["pending"] == 1 and d.actual_start is None and "pending" in d.actual_start_reason

def test_log_entry_uses_actual_once_settled():
    d = _decision()
    assert d.to_log_entry()["effective_from_is_actual"] is False
    settle_actual_start([d], {"AAPL": [_bar("AAPL", "2026-08-07")]})
    e = d.to_log_entry()
    assert e["effective_from_is_actual"] is True and e["effective_from"] == d.actual_start
