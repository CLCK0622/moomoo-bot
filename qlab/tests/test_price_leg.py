"""价格腿：vendor 归一、fail-closed（不用陈旧价）、bar 序列即权威交易日历。"""
from __future__ import annotations
import pytest
from qlab.llm_paper.price_leg import (Bar, PriceLegUnavailable, _parse_alphavantage,
                                      _parse_tiingo, bar_dates, mark_to_market, _api_key)

def _b(d, c, src="v"): return Bar(date=d, close=c, source=src)

def test_alphavantage_parse_and_sort():
    payload={"Time Series (Daily)":{"2026-08-07":{"1. open":"1","2. high":"2","3. low":"0.5","4. close":"1.5","5. volume":"10"},
                                    "2026-08-06":{"1. open":"1","2. high":"2","3. low":"0.5","4. close":"1.4","5. volume":"11"}}}
    bars=_parse_alphavantage(payload, source="alphavantage")
    assert [b.date for b in bars]==["2026-08-06","2026-08-07"] and bars[-1].close==1.5

def test_alphavantage_rate_limit_note_is_unavailable_not_empty():
    # AV 用 200 + Note 表达限速；必须视为不可用，不能当空数据静默通过
    with pytest.raises(PriceLegUnavailable, match="未返回时间序列"):
        _parse_alphavantage({"Note":"call frequency"}, source="alphavantage")

def test_tiingo_parse():
    bars=_parse_tiingo([{"date":"2026-08-07T00:00:00.000Z","close":10.0,"open":9.5,"volume":100}], source="tiingo")
    assert bars[0].date=="2026-08-07" and bars[0].close==10.0

def test_bar_dates_is_the_calendar():
    # 有 bar 即开市：bar 序列本身就是权威交易日历（不再依赖 SPY 派生日历）
    assert bar_dates([_b("2025-08-29",1),_b("2025-09-02",1)])==["2025-08-29","2025-09-02"]

def test_missing_key_fails_closed():
    import os
    os.environ.pop("ALPHAVANTAGE_API_KEY", None)
    with pytest.raises(PriceLegUnavailable, match="缺 API key"):
        _api_key("alphavantage")

def test_mark_to_market_uses_close_only():
    m=mark_to_market({"AAPL":0.1},{"AAPL":[_b("2026-08-06",100.0),_b("2026-08-07",101.0)]})
    assert m["as_of"]=="2026-08-07" and m["marks"]["AAPL"]==101.0

def test_mark_to_market_fails_closed_on_missing_bar():
    # 持仓标的缺当日 bar → 绝不用陈旧价冒充
    with pytest.raises(PriceLegUnavailable, match="缺 bar"):
        mark_to_market({"AAPL":0.1,"MSFT":0.1},
                       {"AAPL":[_b("2026-08-07",100.0)],"MSFT":[_b("2026-08-05",50.0)]},
                       as_of="2026-08-07")

def test_mark_to_market_no_holdings_is_fine():
    assert mark_to_market({}, {})["marks"]=={}

def test_empty_symbol_bars_fails_closed():
    with pytest.raises(PriceLegUnavailable, match="无任何 bar"):
        mark_to_market({"AAPL":0.1},{})
