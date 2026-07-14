"""SIMULATE evidence aggregator: pooling math + honest SIMULATE verdict."""
from __future__ import annotations

import json
from pathlib import Path

from qlab.aggregate_simulate import aggregate


def _write(d: Path, name: str, obj: dict, events: list | None = None):
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps(obj))
    if events is not None:
        (d / "broker_events.jsonl").write_text(
            "\n".join(json.dumps(e) for e in events) + "\n")


def test_aggregate_pools_without_double_count(tmp_path: Path):
    reports = tmp_path / "reports"
    # order-path slot: latencies only in broker_events; 2 orders, 1 reject
    _write(reports / "opend_probe", "opend_metrics.json",
           {"market_us": "AFTER_HOURS_END", "status": "OK", "symbol": "AAA",
            "n_orders": 2, "rejected": 1, "disconnects": 0,
            "reconcile": {"in_sync": True, "n_diffs": 0}},
           events=[{"event": "order_submitted", "latency_ms": 500},
                   {"event": "order_submitted", "latency_ms": 600},
                   {"event": "order_cancelled", "latency_ms": 400}])
    # session slot: latencies in orders[] AND (redundantly) in broker_events —
    # must be counted ONCE.
    _write(reports / "opend_session_live", "session_metrics.json",
           {"market_us": "AFTERNOON", "status": "OK", "symbol": "AAA",
            "fill_rate": {"n_buy": 3, "fully_filled": 3, "rejected": 0},
            "partial_fill_behavior": {"observed": False},
            "fill_latency_s": {"p50": 8.0},
            "orders": [{"submit_ack_latency_ms": 700, "slip_mid_bps": -0.1, "slip_touch_bps": -0.5},
                       {"submit_ack_latency_ms": 800, "slip_mid_bps": 0.2, "slip_touch_bps": -0.3}],
            "reconcile": {"in_sync": True, "n_diffs": 0}},
           events=[{"event": "order_submitted", "latency_ms": 700},
                   {"event": "order_submitted", "latency_ms": 800}])

    r = aggregate(reports, tmp_path / "out", live_check=False)
    m = r["metrics_six_classes"]

    assert m["1_order_latency_ms_submit_to_ack"]["n"] == 4      # 2 + 2, NOT 2 + 4
    assert m["1b_cancel_latency_ms"]["n"] == 1
    assert m["2_slippage_bps_vs_arrival_mid"]["n"] == 2
    assert m["3_fill_rate"]["full_fill_rate"] == 1.0
    assert m["4_reject_rate"] == {"orders": 5, "rejected": 1, "reject_rate": 0.2}
    assert m["5_disconnects"]["total"] == 0
    assert m["6_position_deviation"] == {"all_reconciles_in_sync": True, "worst_n_diffs": 0}

    # honest SIMULATE verdict regardless of how clean the numbers look
    v = r["verdict"]
    assert v["real_execution_cost_established"] is False
    assert v["landable_vs_kevin_bar"] == "UNDECIDABLE_FROM_SIMULATE"
    assert v["decision_readiness"] == "INTERMEDIATE"
    assert r["inventory"]["in_session_slots"] == 1

    # artifacts written
    for f in ("aggregate.json", "metrics.csv", "SUMMARY.md"):
        assert (tmp_path / "out" / f).exists()
