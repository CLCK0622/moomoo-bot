"""SIMULATE evidence aggregator — pooling, qualification gate, ET dates,
reject denominator, dropped-slot handling, and the locked SIMULATE verdict.

Covers the five 都察院 final-review items (no market data re-collection):
1. gate actually rejects CLOSED / ERROR / non-SIMULATE / 0-order slots;
2. fill lag pooled per-order across ALL in-session slots (not slot[0]);
3. reject denominator = all submitted (buys + closeouts + order-path) with breakdown;
4. ET trading dates derived from raw ack_ts (live slot = 2026-07-09);
5. verdict never upgraded (SIMULATE_EXECUTION_CHARACTERIZED / NOT PASS /
   UNDECIDABLE_FROM_SIMULATE; gate CLOSED@7d94a2c).
"""
from __future__ import annotations

import json
from pathlib import Path

from qlab.aggregate_simulate import aggregate

# 1783620083 -> 2026-07-09 14:01 ET (the real live-slot trading day)
ET_0709 = 1783620083.0
ONE_DAY = 86400.0


def _write(d: Path, name: str, obj: dict, events: list):
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps(obj))
    (d / "broker_events.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")


def _session(reports: Path, dirname: str, *, market_us="AFTERNOON",
             status="OK_SESSION_METRICS", trd_env="SIMULATE", n_buy=2,
             ack_ts=ET_0709, fill_lats=(8.0, 9.0), connected=True):
    orders = []
    for i in range(n_buy):
        orders.append({"side": "BUY", "tag": "buy_q1", "ack_ts": ack_ts + i,
                       "submit_ack_latency_ms": 500 + i,
                       "fill_latency_s": fill_lats[i % len(fill_lats)],
                       "slip_mid_bps": -0.1, "slip_touch_bps": -0.5,
                       "final_status": "FILLED_ALL", "dealt_qty": 1, "qty": 1,
                       "fully_filled": True, "partial": False})
    orders.append({"side": "SELL", "tag": "closeout", "ack_ts": ack_ts + n_buy,
                   "submit_ack_latency_ms": 510, "fill_latency_s": fill_lats[0],
                   "slip_mid_bps": -0.05, "slip_touch_bps": -0.3,
                   "final_status": "FILLED_ALL", "dealt_qty": n_buy, "qty": n_buy,
                   "fully_filled": True})
    m = {"market_us": market_us, "status": status, "symbol": "AAA",
         "fill_rate": {"n_buy": n_buy, "fully_filled": n_buy, "rejected": 0},
         "partial_fill_behavior": {"observed": False}, "orders": orders,
         "reconcile": {"in_sync": True, "n_diffs": 0}, "positions_flat_after": True}
    ev = ([{"event": "connected", "trd_env": trd_env, "ts": ack_ts - 1}] if connected else [])
    ev += [{"event": "order_submitted", "ts": o["ack_ts"],
            "latency_ms": o["submit_ack_latency_ms"]} for o in orders]
    _write(reports / dirname, "session_metrics.json", m, ev)


def _orderpath(reports: Path, dirname="opend_probe", *, trd_env="SIMULATE",
               status="OK_ORDER_PATH_MEASURED", n=2):
    m = {"market_us": "AFTER_HOURS_END", "status": status, "symbol": "AAA",
         "n_orders": n, "rejected": 0, "disconnects": 0,
         "reconcile": {"in_sync": True, "n_diffs": 0}}
    ev = [{"event": "connected", "trd_env": trd_env, "ts": 1783000000.0}]
    for i in range(n):
        ev.append({"event": "order_submitted", "ts": 1783000001.0 + i, "latency_ms": 550 + i})
        ev.append({"event": "order_cancelled", "ts": 1783000002.0 + i, "latency_ms": 490 + i})
    _write(reports / dirname, "opend_metrics.json", m, ev)


def _five_valid(reports: Path):
    """5 in-session slots across 3 ET days + 1 order-path slot (all SIMULATE)."""
    _orderpath(reports, n=2)
    _session(reports, "opend_session_live", ack_ts=ET_0709)                 # 07-09
    _session(reports, "opend_session_a", ack_ts=ET_0709 + 5 * ONE_DAY)      # 07-14
    _session(reports, "opend_session_b", ack_ts=ET_0709 + 5 * ONE_DAY + 3600)  # 07-14
    _session(reports, "opend_session_c", ack_ts=ET_0709 + 6 * ONE_DAY)      # 07-15
    _session(reports, "opend_session_d", ack_ts=ET_0709 + 6 * ONE_DAY + 3600)  # 07-15


# --- item 1: gate rejects bad slots (the fixtures that used to fool it) ---
def test_gate_rejects_closed_error_and_nonsimulate(tmp_path: Path):
    reports = tmp_path / "reports"
    _session(reports, "opend_session_closed", market_us="CLOSED")
    _session(reports, "opend_session_err", status="ERROR")
    _session(reports, "opend_session_real", trd_env="REAL")
    r = aggregate(reports, tmp_path / "out", live_check=False)
    assert r["inventory"]["in_session_slots"] == 0
    assert r["verdict"]["decision_readiness"] == "INTERMEDIATE"
    reasons = {x["dir"]: x["reason"] for x in r["inventory"]["rejected_slots"]}
    assert "not regular session" in reasons["opend_session_closed"]
    assert "OK_SESSION_METRICS" in reasons["opend_session_err"]
    assert "not SIMULATE" in reasons["opend_session_real"]


# --- item 5: 0-order slots dropped, empty on a clean tree ---
def test_zero_order_slot_dropped_and_empty_when_clean(tmp_path: Path):
    reports = tmp_path / "reports"
    _five_valid(reports)
    r = aggregate(reports, tmp_path / "out", live_check=False)
    assert r["inventory"]["dropped_zero_order_slots"] == []      # clean tree

    _session(reports, "opend_session_smoke", n_buy=0)            # 0 buys -> only closeout... force 0 orders
    # make it truly zero-order: overwrite with empty orders
    (reports / "opend_session_smoke" / "session_metrics.json").write_text(json.dumps(
        {"market_us": "AFTERNOON", "status": "OK_SESSION_METRICS", "symbol": "AAA",
         "fill_rate": {"n_buy": 0, "fully_filled": 0, "rejected": 0}, "orders": [],
         "n_orders": 0, "reconcile": {"in_sync": True, "n_diffs": 0}}))
    r2 = aggregate(reports, tmp_path / "out", live_check=False)
    assert "opend_session_smoke" in r2["inventory"]["dropped_zero_order_slots"]
    assert r2["inventory"]["in_session_slots"] == 5             # smoke not counted


# --- item 2: fill lag pooled per-order across ALL in-session slots ---
def test_fill_lag_pooled_across_all_slots(tmp_path: Path):
    reports = tmp_path / "reports"
    # two sessions with clearly different fill lags so slot[0]-only would differ
    _session(reports, "opend_session_a", n_buy=2, fill_lats=(1.0, 1.0), ack_ts=ET_0709)
    _session(reports, "opend_session_b", n_buy=2, fill_lats=(9.0, 9.0), ack_ts=ET_0709 + ONE_DAY)
    r = aggregate(reports, tmp_path / "out", live_check=False)
    fl = r["metrics_six_classes"]["aux_fill_latency_s_pooled"]
    # each slot contributes n_buy+1 fill-lat samples -> 3 + 3 = 6, pooled (not 3)
    assert fl["n"] == 6
    assert 1.0 < fl["mean"] < 9.0                # spans both slots, not slot[0] only
    assert fl["min"] == 1.0 and fl["max"] == 9.0


# --- item 3: reject denominator = all submitted, with breakdown ---
def test_reject_denominator_all_submitted(tmp_path: Path):
    reports = tmp_path / "reports"
    _orderpath(reports, n=2)
    _session(reports, "opend_session_a", n_buy=2, ack_ts=ET_0709)
    _session(reports, "opend_session_b", n_buy=2, ack_ts=ET_0709 + ONE_DAY)
    rj = aggregate(reports, tmp_path / "out", live_check=False)["metrics_six_classes"]["4_reject_rate"]
    # sessions: (2 buy + 1 close) x2 = 6 ; order-path 2 -> 8 total submitted
    assert rj["submitted"] == 8 and rj["rejected"] == 0 and rj["reject_rate"] == 0.0
    assert rj["breakdown"]["primary_buy_and_order_path"]["submitted"] == 6   # 4 buys + 2 op
    assert rj["breakdown"]["closeout_sells"]["submitted"] == 2               # 2 closeouts


# --- item 4: ET dates derived from raw ack_ts ---
def test_et_dates_from_raw_timestamps(tmp_path: Path):
    reports = tmp_path / "reports"
    _session(reports, "opend_session_live", ack_ts=ET_0709)                 # 07-09
    _session(reports, "opend_session_next", ack_ts=ET_0709 + 5 * ONE_DAY)   # 07-14
    r = aggregate(reports, tmp_path / "out", live_check=False)
    by_dir = {s["dir"]: s["et_date"] for s in r["inventory"]["slots"]}
    assert by_dir["opend_session_live"] == "2026-07-09"                     # NOT 07-10
    assert r["inventory"]["n_distinct_session_trading_days"] == 2


# --- items 1 (accept) + 5 verdict: 5 valid slots => characterized, not upgraded ---
def test_five_valid_characterized_but_not_upgraded(tmp_path: Path):
    reports = tmp_path / "reports"
    _five_valid(reports)
    r = aggregate(reports, tmp_path / "out", live_check=False)
    inv, v = r["inventory"], r["verdict"]
    assert inv["slots_total"] == 6 and inv["in_session_slots"] == 5 and inv["in_session_gap"] == 0
    assert inv["distinct_session_trading_days_et"] == ["2026-07-09", "2026-07-14", "2026-07-15"]
    assert v["decision_readiness"] == "SIMULATE_EXECUTION_CHARACTERIZED"
    assert v["real_execution_cost_established"] is False
    assert v["landable_vs_kevin_bar"] == "UNDECIDABLE_FROM_SIMULATE"
    assert v["engineering_risk_gate"] == "CLOSED@7d94a2c"
    # latency pooled from ONE source per slot (no double count): 5*(2 buys+1 close)=15 + 2 op = 17
    assert r["metrics_six_classes"]["1_order_latency_ms_submit_to_ack"]["n"] == 17
    for f in ("aggregate.json", "metrics.csv", "SUMMARY.md"):
        assert (tmp_path / "out" / f).exists()
