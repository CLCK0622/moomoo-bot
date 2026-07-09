"""Earnings-event drift package (EVO-24): wiring, look-ahead safety, and the
hard constraints (long-only positive branch, defined-risk-only negative branch,
close-to-open on real open/close). Synthetic numbers are self-tests, never
performance — the tests assert *mechanics*, not returns clearing a hurdle.
"""
from __future__ import annotations

import pandas as pd
import pytest

from qlab.events.eventsource import (EarningsEvent, SyntheticEventSource,
                                      classify_session)
from qlab.events.bars import SyntheticDailyBarSource, DAILY_COLUMNS
from qlab.events.timing import reaction_index, entry_index
from qlab.events.strategy import CostModel, build_event_trade, compute_reaction_return
from qlab.events.options import MissingOptionsChainSource, OptionQuote, price_bear_put_spread
from qlab.events.surprise import QuantileThresholds, analyst_sign
from qlab.events.metrics import evo12_metrics, _cagr, _max_drawdown
from qlab.events.backtest import EventDriftBacktester
from qlab.events.gates import gate1_full_sample, gate3_rolling, walk_forward
from qlab.events import run_events


# ---------- helpers ----------
def _manual_frame(rows):
    """rows = list of (date, open, high, low, close, volume)."""
    df = pd.DataFrame(rows, columns=DAILY_COLUMNS)
    df["date"] = pd.to_datetime(df["date"])
    df["dollar_volume"] = df["volume"] * df["close"]
    return df


# ---------- session classification ----------
@pytest.mark.parametrize("ts,expected", [
    ("2024-05-01 07:30", "bmo"),
    ("2024-05-01 09:29", "bmo"),
    ("2024-05-01 09:30", "intraday"),
    ("2024-05-01 12:00", "intraday"),
    ("2024-05-01 15:59", "intraday"),
    ("2024-05-01 16:00", "amc"),
    ("2024-05-01 16:15", "amc"),
])
def test_session_classification(ts, expected):
    assert classify_session(pd.Timestamp(ts)) == expected


def test_event_rejects_bad_session():
    with pytest.raises(ValueError):
        EarningsEvent.from_parts("AAPL", "2024-05-01 07:30", session="premarket")


# ---------- look-ahead-free timing ----------
def test_timing_bmo_vs_amc_lookahead_free():
    dates = pd.DatetimeIndex(pd.bdate_range("2024-01-01", periods=10))
    d = dates[3]
    # bmo: reaction is announce day, entry is next day
    assert reaction_index(dates, d, "bmo") == 3
    assert entry_index(dates, d, "bmo") == 4
    # amc: reaction is next day (first full session on the news), entry the day after
    assert reaction_index(dates, d, "amc") == 4
    assert entry_index(dates, d, "amc") == 5
    # entry is ALWAYS strictly after the reaction bar
    for sess in ("bmo", "amc", "intraday"):
        assert entry_index(dates, d, sess) == reaction_index(dates, d, sess) + 1


def test_timing_rolls_forward_off_weekend():
    dates = pd.DatetimeIndex(pd.bdate_range("2024-01-01", periods=10))
    # 2024-01-06 is a Saturday -> first session >= it is Monday 2024-01-08
    r = reaction_index(dates, pd.Timestamp("2024-01-06"), "bmo")
    assert dates[r] == pd.Timestamp("2024-01-08")


# ---------- close-to-open uses REAL open/close, not close-close ----------
def test_close_to_open_uses_open_and_close():
    # deterministic frame: distinct opens/closes so close-close != close-open
    rows = [
        ("2024-01-01", 100, 101, 99, 100, 5_000_000),   # 0
        ("2024-01-02", 101, 103, 100, 102, 5_000_000),  # 1  reaction (bmo announce on day1)
        ("2024-01-03", 105, 106, 104, 104, 5_000_000),  # 2  entry day (open=105)
        ("2024-01-04", 108, 109, 107, 107, 5_000_000),  # 3  open=108
        ("2024-01-05", 110, 111, 109, 109, 5_000_000),  # 4  open=110
    ]
    df = _manual_frame(rows)
    dates = pd.DatetimeIndex(df["date"])
    ev = EarningsEvent.from_parts("XYZ", "2024-01-02 07:30", session="bmo", analyst_surprise=1.0)
    t = build_event_trade(df, dates, ev, sign=+1, mode="close_to_open", hold=2,
                          cost=CostModel(0, 0, 1), min_adv=0.0,
                          options_src=MissingOptionsChainSource())
    # entry at index 2 (day after reaction=1). two overnight legs:
    #   leg A: close[2]=104 -> open[3]=108  => 108/104-1
    #   leg B: close[3]=107 -> open[4]=110  => 110/107-1
    legA = 108 / 104 - 1
    legB = 110 / 107 - 1
    expected = (1 + legA) * (1 + legB) - 1
    assert t.branch == "long"
    assert t.net_return == pytest.approx(expected, rel=1e-9)
    # returns attributed to the leg-CLOSING days (open days), never close-close
    assert set(t.daily_returns) == {dates[3], dates[4]}


def test_pead_holds_open_to_close():
    rows = [
        ("2024-01-01", 100, 101, 99, 100, 5_000_000),
        ("2024-01-02", 101, 103, 100, 102, 5_000_000),  # reaction (bmo)
        ("2024-01-03", 105, 106, 104, 106, 5_000_000),  # entry open=105
        ("2024-01-04", 107, 109, 106, 110, 5_000_000),  # exit close=110 (hold=2)
    ]
    df = _manual_frame(rows)
    dates = pd.DatetimeIndex(df["date"])
    ev = EarningsEvent.from_parts("XYZ", "2024-01-02 07:30", session="bmo", analyst_surprise=1.0)
    t = build_event_trade(df, dates, ev, sign=+1, mode="pead", hold=2,
                          cost=CostModel(0, 0, 1), min_adv=0.0,
                          options_src=MissingOptionsChainSource())
    assert t.net_return == pytest.approx(110 / 105 - 1, rel=1e-9)


# ---------- positive branch captures injected drift ----------
@pytest.mark.parametrize("mode", ["pead", "close_to_open"])
def test_positive_branch_captures_drift(mode):
    ev = EarningsEvent.from_parts("AAA", "2022-03-10 07:30", session="bmo", analyst_surprise=2.0)
    bars = SyntheticDailyBarSource(["AAA"], "2022-01-03", "2022-06-30", seed=1,
                                   events=[ev], drift0=0.02, gap0=0.05)
    df = bars.load("AAA")
    dates = pd.DatetimeIndex(df["date"])
    t = build_event_trade(df, dates, ev, sign=+1, mode=mode, hold=10,
                          cost=CostModel(0, 0, 1), min_adv=0.0,
                          options_src=MissingOptionsChainSource())
    assert t.branch == "long" and t.realizable
    assert t.net_return > 0            # captured the injected upward drift
    # entry strictly after the reaction bar (no look-ahead onto the gap)
    r = reaction_index(dates, ev.announce_date, ev.session)
    assert min(t.daily_returns) > dates[r]


# ---------- negative branch: NEVER a naked short ----------
def test_negative_branch_blocked_never_short():
    rows = [(f"2024-01-{i+1:02d}", 100, 101, 99, 100 - i, 5_000_000) for i in range(8)]
    df = _manual_frame(rows)
    dates = pd.DatetimeIndex(df["date"])
    ev = EarningsEvent.from_parts("XYZ", "2024-01-02 07:30", session="bmo", analyst_surprise=-2.0)
    t = build_event_trade(df, dates, ev, sign=-1, mode="pead", hold=3,
                          cost=CostModel(), min_adv=0.0,
                          options_src=MissingOptionsChainSource())
    assert t.branch == "negative_defined_risk"
    assert t.realizable is False
    assert t.net_return == 0.0                       # no realized PnL -> no short exposure
    assert t.reference_return is not None            # reference only, for the options study
    assert "options_chain_unavailable" in t.reason
    assert t.daily_returns == {}                     # nothing enters the equity curve


def test_negative_branch_with_chain_still_not_short():
    """Even if a chain exists, the path prices a defined-risk spread and does NOT
    short stock or fabricate a settlement it cannot compute."""
    class _FakeChain:
        name = "fake"
        def chain(self, symbol, as_of):
            exp = pd.Timestamp(as_of) + pd.Timedelta(days=30)
            return [OptionQuote(exp, 100, "P", 2.0, 2.2),
                    OptionQuote(exp, 95, "P", 0.8, 1.0)]
        def provenance(self):
            return {"source": "fake"}
    rows = [(f"2024-01-{i+1:02d}", 100, 101, 99, 100 - i, 5_000_000) for i in range(8)]
    df = _manual_frame(rows)
    dates = pd.DatetimeIndex(df["date"])
    ev = EarningsEvent.from_parts("XYZ", "2024-01-02 07:30", session="bmo", analyst_surprise=-2.0)
    t = build_event_trade(df, dates, ev, sign=-1, mode="pead", hold=3,
                          cost=CostModel(), min_adv=0.0, options_src=_FakeChain())
    assert t.branch == "negative_defined_risk"
    assert t.realizable is False          # priced, but settlement needs exit chain
    assert t.net_return == 0.0            # never a short PnL
    assert "needs_exit_chain" in t.reason


def test_bear_put_spread_is_defined_risk():
    exp = pd.Timestamp("2024-02-01")
    chain = [OptionQuote(exp, 100, "P", 3.0, 3.4), OptionQuote(exp, 95, "P", 1.0, 1.2)]
    trade = price_bear_put_spread(chain, spot=100.0, target_dte=30, width_pct=0.05)
    assert trade is not None
    assert trade.max_loss == pytest.approx(trade.debit)   # debit structure: loss capped at debit
    assert trade.max_gain > 0
    assert price_bear_put_spread(None, 100.0) is None      # no chain -> no trade (not a short)


# ---------- liquidity filter ----------
def test_liquidity_floor_skips_thin_names():
    rows = [(f"2024-01-{i+1:02d}", 10, 10.1, 9.9, 10, 1000) for i in range(8)]  # ~10k ADV
    df = _manual_frame(rows)
    dates = pd.DatetimeIndex(df["date"])
    ev = EarningsEvent.from_parts("XYZ", "2024-01-02 07:30", session="bmo", analyst_surprise=2.0)
    t = build_event_trade(df, dates, ev, sign=+1, mode="pead", hold=2,
                          cost=CostModel(), min_adv=1_000_000.0,
                          options_src=MissingOptionsChainSource())
    assert t.reason == "below_liquidity_floor"
    assert t.net_return == 0.0


# ---------- cost x2 ----------
def test_cost_x2_reduces_return():
    ev = EarningsEvent.from_parts("AAA", "2022-03-10 07:30", session="bmo", analyst_surprise=2.0)
    bars = SyntheticDailyBarSource(["AAA"], "2022-01-03", "2022-06-30", seed=1,
                                   events=[ev], drift0=0.02)
    df = bars.load("AAA")
    dates = pd.DatetimeIndex(df["date"])
    kw = dict(sign=+1, mode="close_to_open", hold=10, min_adv=0.0,
              options_src=MissingOptionsChainSource())
    base = build_event_trade(df, dates, ev, cost=CostModel(5, 5, 1), **kw)
    dbl = build_event_trade(df, dates, ev, cost=CostModel(5, 5, 2), **kw)
    assert dbl.net_return < base.net_return


# ---------- surprise classification ----------
def test_analyst_sign_dead_zone():
    assert analyst_sign(1.0, 0.5) == 1
    assert analyst_sign(-1.0, 0.5) == -1
    assert analyst_sign(0.2, 0.5) == 0
    assert analyst_sign(None) == 0


def test_quantile_thresholds_classify_tails():
    reactions = [i / 100.0 for i in range(-10, 11)]   # -0.10 .. 0.10
    thr = QuantileThresholds.fit(reactions, q=0.2)
    assert thr.sign(0.10) == 1
    assert thr.sign(-0.10) == -1
    assert thr.sign(0.0) == 0


# ---------- metrics ----------
def test_cagr_geometric_and_mdd():
    import numpy as np
    # 252 bars, end/start = 2 exactly, P=252 -> geometric CAGR = 2^(252/252)-1 = 1.0
    eq = np.array([2.0 ** (i / 251) for i in range(252)])
    assert _cagr(eq, 252) == pytest.approx(1.0, rel=1e-6)
    dd = np.array([100, 120, 90, 110])   # peak 120 -> 90 = 25% dd
    assert _max_drawdown(dd) == pytest.approx(0.25, rel=1e-9)


def test_evo12_metrics_shape():
    eq = pd.DataFrame({
        "date": pd.bdate_range("2022-01-03", periods=60),
        "equity": [1.0 + 0.001 * i for i in range(60)],
        "ret": [0.001] * 60,
        "traded_notional": [0.0] * 60,
    })
    m = evo12_metrics(eq, [{"pnl": 0.05}, {"pnl": -0.02}], P=252)
    for k in ("cagr", "max_drawdown", "sharpe", "sortino", "win_rate",
              "profit_factor", "annualized_turnover", "max_underwater_bars"):
        assert k in m
    assert m["num_trades"] == 2
    assert m["win_rate"] == 0.5


# ---------- backtester determinism + structure ----------
def _make_bt(seed=7):
    syms = ["AAA", "BBB", "CCC", "DDD"]
    ev = SyntheticEventSource(syms, "2021-01-04", "2023-12-31", seed=seed)
    bars = SyntheticDailyBarSource(syms, "2021-01-04", "2023-12-31", seed=seed,
                                   events=ev.events())
    return EventDriftBacktester(bars, ev, mode="pead", hold=10,
                               options_src=MissingOptionsChainSource())


def test_backtester_determinism():
    r1 = _make_bt().run()
    r2 = _make_bt().run()
    pd.testing.assert_frame_equal(r1["equity"], r2["equity"])
    assert r1["trade_log"] == r2["trade_log"]


def test_backtester_no_short_positions_anywhere():
    res = _make_bt().run()
    # every negative-branch trade is unrealized; nothing short ever hits the book
    for t in res["trades"]:
        if t.branch == "negative_defined_risk":
            assert t.realizable is False and t.net_return == 0.0
        if t.realizable:
            assert t.branch == "long"


def test_gates_and_walkforward_run():
    bt = _make_bt()
    res = bt.run()
    g1 = gate1_full_sample(res["equity"])
    g3 = gate3_rolling(res["equity"])
    assert "passed" in g1 and isinstance(g1["passed"], bool)
    assert "passed" in g3
    wf = walk_forward(bt, train_months=12, test_months=6, step_months=6)
    assert "passed" in wf and "folds" in wf


# ---------- honest verdict on synthetic ----------
def test_synthetic_report_verdict_is_needs_evidence():
    args = run_events.build_report(_Args())
    assert args["performance_meaningful"] is False
    assert args["overall_verdict"] == "需补证据"
    assert len(args["data_gap_list"]) >= 3
    assert any(r["risk"] == "options_data_gap" for r in args["risk_register"])


class _Args:
    source = "synthetic"
    mode = "both"
    hold = [5, 10]
    symbols = ["AAA", "BBB", "CCC", "DDD"]
    start = "2021-01-04"
    end = "2022-12-31"
    seed = 7
    data_dir = "data/daily"
    events_csv = None
    min_adv = 1_000_000.0
    max_concurrent = 10
    quantile = 0.2
    surprise_mode = "quantile"
    trading_days = 252
    rf = 0.0
    out = "reports/_test_events"
