"""Offline unit tests for the EVO-130 OpenD history-K depth/quota/rate probe.

No gateway, no SDK: a fake ``OpenQuoteContext`` is injected via ``ctx_factory``
so the load-bearing logic — depth floor → stress coverage → PASS/GAP gate, the
``(ret, (used, remaining, detail))`` quota parse, and the quote-only / no-trade
invariant — is pinned deterministically. The live pull is exercised out of band
and recorded in ``reports/opend_kline_depth/report.json``, not here.
"""
from __future__ import annotations

import pandas as pd

from qlab.opend_kline_depth_probe import COVERAGE_FLOOR_DATE, STRESS_WINDOWS, probe

RET_OK = 0


def _daily_frame(code: str, floor: str, end: str = "2026-07-09") -> pd.DataFrame:
    """Synthetic daily OHLCV frame on US business days in [floor, end]."""
    idx = pd.bdate_range(floor, end)
    n = len(idx)
    return pd.DataFrame({
        "code": code,
        "time_key": idx,
        "open": [100.0 + i * 0.01 for i in range(n)],
        "high": [101.0 + i * 0.01 for i in range(n)],
        "low": [99.0 + i * 0.01 for i in range(n)],
        "close": [100.5 + i * 0.01 for i in range(n)],
        "volume": [1_000_000] * n,
    })


class _FakeQuoteCtx:
    """Minimal stand-in for OpenQuoteContext — quote calls only.

    ``opened_trade_ctx`` stays False forever: a probe that ever reached for the
    trade path would have to call a method this fake does not provide, which
    would raise — so the quote-only invariant is enforced by construction.
    """

    def __init__(self, floor: str, counted: list, used: int = 20, remaining: int = 280,
                 kline_ret: int = RET_OK):
        self._floor = floor
        self._counted = counted
        self._used = used
        self._remaining = remaining
        self._kline_ret = kline_ret
        self.closed = False
        self.opened_trade_ctx = False  # never flipped — no trade method exists here

    def get_global_state(self):
        return RET_OK, {"market_us": "CLOSED", "qot_logined": True, "trd_logined": True}

    def get_history_kl_quota(self, get_detail=False):
        detail = [{"code": c, "name": c, "request_time": "2026-07-10 16:00:00"}
                  for c in self._counted] if get_detail else []
        return RET_OK, (self._used, self._remaining, detail)

    def request_history_kline(self, code, start=None, end=None, ktype="K_DAY",
                              autype="qfq", max_count=1000, page_req_key=None):
        if self._kline_ret != RET_OK:
            return self._kline_ret, "FAKE_API_ERROR: no permission", None
        df = _daily_frame(code, self._floor, end or "2026-07-09")
        if start:
            df = df[df["time_key"] >= pd.Timestamp(start)]
        # single page — no pagination in the fake
        return RET_OK, df.reset_index(drop=True), None

    def close(self):
        self.closed = True


def test_gate_passes_when_floor_covers_all_stress_windows(tmp_path):
    ctx = _FakeQuoteCtx(floor="2006-06-26", counted=["US.AAPL", "US.SPY"])
    rep = probe(tmp_path, depth_symbols=["US.AAPL", "US.SPY"], deep_start="2000-01-01",
                burst_n=5, ctx_factory=lambda: ctx, ret_ok=RET_OK, write=True)

    assert rep["gate"]["verdict"] == "PASS_NO_GAP"
    assert rep["gate"]["gap_list"] == []
    assert rep["gate"]["measured_floor_date"] == "2006-06-26"
    assert rep["gate"]["measured_floor_date"] <= COVERAGE_FLOOR_DATE
    # every flagged stress window is covered by at least one probed symbol
    assert all(v["covered"] for v in rep["stress_coverage_union"].values())
    assert set(rep["stress_coverage_union"]) == set(STRESS_WINDOWS)
    # (ret, (used, remaining, detail)) parsed correctly
    assert rep["quota"]["total"] == 300
    assert rep["quota"]["used"] == 20 and rep["quota"]["remaining"] == 280
    # quote-only invariant surfaced for a reviewer, and no trade ctx was opened
    assert rep["trd_ctx_opened"] is False
    assert ctx.opened_trade_ctx is False
    assert ctx.closed is True
    # report persisted
    assert (tmp_path / "report.json").exists()


def test_gate_flags_gap_when_floor_too_shallow(tmp_path):
    # floor in 2020 cannot reach the 2018 windows
    ctx = _FakeQuoteCtx(floor="2020-01-02", counted=["US.AAPL", "US.SPY"])
    rep = probe(tmp_path, depth_symbols=["US.AAPL", "US.SPY"], deep_start="2000-01-01",
                burst_n=3, ctx_factory=lambda: ctx, ret_ok=RET_OK, write=False)

    assert rep["gate"]["verdict"] == "GAP"
    assert rep["gate"]["covers_2018_2020_2022"] is False
    # both the floor shortfall and the uncovered 2018 windows are itemised
    joined = " ".join(rep["gate"]["gap_list"])
    assert "floor" in joined
    assert any("2018" in g for g in rep["gate"]["gap_list"])
    # 2020/2022 windows remain covered even in the shallow case
    assert rep["stress_coverage_union"]["2022_rate_bear"]["covered"] is True


def test_quota_plan_marks_uncounted_symbols_as_consuming(tmp_path):
    # SPY not yet counted -> flagged as would-consume (frugality guard)
    ctx = _FakeQuoteCtx(floor="2006-06-26", counted=["US.AAPL"])
    rep = probe(tmp_path, depth_symbols=["US.AAPL", "US.SPY"], deep_start="2000-01-01",
                burst_n=1, ctx_factory=lambda: ctx, ret_ok=RET_OK, write=False)
    assert rep["quota_plan"]["already_counted"] == ["US.AAPL"]
    assert rep["quota_plan"]["would_consume"] == ["US.SPY"]


def test_api_error_yields_gap_not_fabricated_depth(tmp_path):
    ctx = _FakeQuoteCtx(floor="2006-06-26", counted=["US.AAPL"], kline_ret=1)
    rep = probe(tmp_path, depth_symbols=["US.AAPL"], deep_start="2000-01-01",
                burst_n=1, ctx_factory=lambda: ctx, ret_ok=RET_OK, write=False)
    # no bars returned -> floor is None, gate is GAP, error recorded (never faked)
    assert rep["depth"]["floor_date"] is None
    assert rep["gate"]["verdict"] == "GAP"
    assert rep["depth"]["symbols"]["US.AAPL"]["error"] is not None
