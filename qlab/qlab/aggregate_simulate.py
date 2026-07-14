"""Aggregate the collected OpenD **SIMULATE** evidence slots into one verdict.

Reads the committed per-slot report dirs under ``reports/`` (order-path probe +
in-session probe, and any future autopilot slots that follow the same layout),
pools the six required metric classes, and emits a JSON / CSV / Markdown summary
with a landability judgment.

It does NOT collect new data, re-run history, or place orders — pure aggregation
of already-committed artifacts (an optional quote-only `get_global_state` read
just timestamps the current market state; no trade context, no credentials).

⚠️ Hard scope: every input is `TrdEnv.SIMULATE`. These metrics characterise the
OpenD adapter + the SIMULATE matching engine's execution path — they are NOT real
market execution cost and cannot, on their own, establish landability against
Kevin's 50% annual / 20% drawdown bar (which needs a real-fills strategy PnL).
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np

# For a statistically-defensible SIMULATE execution read (reusing the EVO-149 A/B
# convention of multiple independent samples), we want several in-session slots
# across distinct windows, not a single one.
IN_SESSION_SLOTS_FOR_DECISION = 5
OPEN_STATES = {"MORNING", "AFTERNOON"}


def _pct(vals, p):
    return float(np.percentile(vals, p)) if len(vals) else None


def _stats(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return {"n": 0}
    return {"n": len(vals), "p50": _pct(vals, 50), "p95": _pct(vals, 95),
            "mean": float(np.mean(vals)), "min": float(np.min(vals)),
            "max": float(np.max(vals))}


def _read_jsonl(path: Path):
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def _discover_slots(reports_dir: Path) -> list[Path]:
    slots = []
    for d in sorted(reports_dir.iterdir()):
        if not d.is_dir():
            continue
        if d.name.startswith("opend_probe") or d.name.startswith("opend_session"):
            if any(d.glob("*metrics.json")):
                slots.append(d)
    return slots


def _load_slot(d: Path) -> dict:
    mj = next(iter(d.glob("*metrics.json")))
    m = json.loads(mj.read_text())
    kind = "session" if "fill_rate" in m else "order_path"
    events = _read_jsonl(d / "broker_events.jsonl")

    # first-hand submit->ack latency samples — ONE source per slot to avoid
    # double counting (session metrics.orders[] and its broker_events overlap).
    if kind == "session":
        lat = [o["submit_ack_latency_ms"] for o in m.get("orders", [])
               if o.get("submit_ack_latency_ms") is not None]
    else:  # order_path: latencies live only in broker_events
        lat = [e["latency_ms"] for e in events
               if e.get("event") == "order_submitted" and e.get("latency_ms") is not None]
    cancel_lat = [e["latency_ms"] for e in events
                  if e.get("event") == "order_cancelled" and e.get("latency_ms") is not None]

    # slippage samples (session only)
    slip_mid = [o["slip_mid_bps"] for o in m.get("orders", []) if "slip_mid_bps" in o]
    slip_touch = [o["slip_touch_bps"] for o in m.get("orders", []) if "slip_touch_bps" in o]

    recon = m.get("reconcile", {}) or {}
    return {
        "dir": d.name, "kind": kind, "market_us": m.get("market_us"),
        "status": m.get("status"), "symbol": m.get("symbol"),
        "latency_ms": lat, "cancel_latency_ms": cancel_lat,
        "slip_mid_bps": slip_mid, "slip_touch_bps": slip_touch,
        "fill_rate": m.get("fill_rate"),
        "partial_fill": m.get("partial_fill_behavior"),
        "fill_latency_s": m.get("fill_latency_s"),
        "n_orders": m.get("n_orders") or (m.get("fill_rate", {}) or {}).get("n_buy", 0),
        "rejected": (m.get("rejected") if m.get("rejected") is not None
                     else (m.get("fill_rate", {}) or {}).get("rejected", 0)),
        "disconnects": m.get("disconnects", 0) or 0,
        "reconcile_in_sync": bool(recon.get("in_sync", True)),
        "reconcile_n_diffs": int(recon.get("n_diffs", 0) or 0),
        "positions_flat_after": m.get("positions_flat_after"),
    }


def _live_market_us(host: str, port: int) -> dict:
    """Quote-only get_global_state — no trade context, no orders, no credentials."""
    try:
        import importlib
        sdk = importlib.import_module("moomoo")
    except Exception:
        return {"available": False, "reason": "SDK not importable"}
    try:
        q = sdk.OpenQuoteContext(host=host, port=port)
        r, gs = q.get_global_state()
        q.close()
        if r != sdk.RET_OK:
            return {"available": True, "market_us": None, "reason": str(gs)[:80]}
        return {"available": True, "market_us": gs.get("market_us"),
                "trd_logined": gs.get("trd_logined"), "qot_logined": gs.get("qot_logined")}
    except Exception as e:
        return {"available": False, "reason": str(e)[:120]}


def aggregate(reports_dir: Path, out_dir: Path, live_check: bool = True,
              host: str = "127.0.0.1", port: int = 11111) -> dict:
    slots = [_load_slot(d) for d in _discover_slots(reports_dir)]
    order_path = [s for s in slots if s["kind"] == "order_path"]
    session = [s for s in slots if s["kind"] == "session"]

    all_lat = [v for s in slots for v in s["latency_ms"]]
    all_cancel = [v for s in slots for v in s["cancel_latency_ms"]]
    slip_mid = [v for s in session for v in s["slip_mid_bps"]]
    slip_touch = [v for s in session for v in s["slip_touch_bps"]]

    n_buy = sum((s["fill_rate"] or {}).get("n_buy", 0) for s in session)
    fully = sum((s["fill_rate"] or {}).get("fully_filled", 0) for s in session)
    total_orders = sum(s["n_orders"] or 0 for s in slots)
    total_rejected = sum(s["rejected"] or 0 for s in slots)
    total_disconnects = sum(s["disconnects"] or 0 for s in slots)
    any_partial = any((s["partial_fill"] or {}).get("observed") for s in session)
    worst_diffs = max([s["reconcile_n_diffs"] for s in slots], default=0)
    all_in_sync = all(s["reconcile_in_sync"] for s in slots)

    # The six required metric classes
    metrics = {
        "1_order_latency_ms_submit_to_ack": _stats(all_lat),
        "1b_cancel_latency_ms": _stats(all_cancel),
        "2_slippage_bps_vs_arrival_mid": _stats(slip_mid),
        "2b_slippage_bps_vs_arrival_touch": _stats(slip_touch),
        "3_fill_rate": {"n_buy": n_buy, "fully_filled": fully,
                        "full_fill_rate": round(fully / n_buy, 4) if n_buy else None},
        "4_reject_rate": {"orders": total_orders, "rejected": total_rejected,
                          "reject_rate": round(total_rejected / total_orders, 4) if total_orders else None},
        "5_disconnects": {"total": total_disconnects},
        "6_position_deviation": {"all_reconciles_in_sync": all_in_sync,
                                 "worst_n_diffs": worst_diffs},
        "aux_partial_fill_observed": any_partial,
        "aux_fill_latency_s_simulate_engine": (session[0]["fill_latency_s"] if session else None),
    }

    # Slot inventory / decision-readiness
    in_session_slots = len(session)
    inventory = {
        "slots_total": len(slots),
        "order_path_slots": len(order_path),
        "in_session_slots": in_session_slots,
        "slots": [{"dir": s["dir"], "kind": s["kind"], "market_us": s["market_us"],
                   "status": s["status"], "n_orders": s["n_orders"]} for s in slots],
        "in_session_slots_needed_for_decision": IN_SESSION_SLOTS_FOR_DECISION,
        "in_session_gap": max(0, IN_SESSION_SLOTS_FOR_DECISION - in_session_slots),
    }

    live = _live_market_us(host, port) if live_check else {"available": False, "reason": "skipped"}

    verdict = {
        "real_execution_cost_established": False,
        "reason": "All samples are TrdEnv.SIMULATE. Near-zero slippage, 100% whole-"
                  "lot fills, seconds-scale fill lag and 0 rejects are SIMULATE "
                  "matching-engine traits, NOT real market execution cost.",
        "landable_vs_kevin_bar": "UNDECIDABLE_FROM_SIMULATE",
        "kevin_bar": "annual return >= 50% AND max drawdown <= 20% (on real fills)",
        "note": "The 50%/20% bar is a return/drawdown target on a real-fills "
                "strategy PnL; SIMULATE execution-path health cannot satisfy it. "
                "Candidate stays needs-evidence / NOT PASS.",
        "decision_readiness": (
            "INTERMEDIATE" if in_session_slots < IN_SESSION_SLOTS_FOR_DECISION
            else "SIMULATE_EXECUTION_CHARACTERIZED"),
        "gaps": [
            f"need >= {IN_SESSION_SLOTS_FOR_DECISION} in-session slots for a stable "
            f"SIMULATE execution read; have {in_session_slots} "
            f"(gap {inventory['in_session_gap']}) — autopilot supplies these.",
            "real execution cost (real market impact / slippage) requires REAL "
            "fills (real-money or real-market matching) — out of scope, controlled.",
        ],
    }

    result = {
        "aggregate_of": "OpenD SIMULATE evidence slots (EVO-65)",
        "trd_env": "SIMULATE",
        "scope_note": "SIMULATE matching-engine execution path, NOT real market cost.",
        "inventory": inventory,
        "metrics_six_classes": metrics,
        "live_market_context": live,
        "verdict": verdict,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "aggregate.json").write_text(json.dumps(result, indent=2, default=str))
    _write_csv(out_dir / "metrics.csv", metrics, inventory)
    _write_summary(out_dir / "SUMMARY.md", result)
    return result


def _write_csv(path: Path, metrics: dict, inventory: dict) -> None:
    rows = [
        ["metric_class", "statistic", "value", "unit", "source_scope"],
        ["order_latency_submit_ack", "p50", metrics["1_order_latency_ms_submit_to_ack"].get("p50"), "ms", "SIMULATE gateway"],
        ["order_latency_submit_ack", "p95", metrics["1_order_latency_ms_submit_to_ack"].get("p95"), "ms", "SIMULATE gateway"],
        ["order_latency_submit_ack", "max", metrics["1_order_latency_ms_submit_to_ack"].get("max"), "ms", "SIMULATE gateway"],
        ["order_latency_submit_ack", "n", metrics["1_order_latency_ms_submit_to_ack"].get("n"), "count", "SIMULATE gateway"],
        ["slippage_vs_mid", "p50", metrics["2_slippage_bps_vs_arrival_mid"].get("p50"), "bps(+worse)", "SIMULATE engine"],
        ["slippage_vs_touch", "p50", metrics["2b_slippage_bps_vs_arrival_touch"].get("p50"), "bps(+worse)", "SIMULATE engine"],
        ["fill_rate", "full_fill_rate", metrics["3_fill_rate"]["full_fill_rate"], "ratio", "SIMULATE engine"],
        ["reject_rate", "reject_rate", metrics["4_reject_rate"]["reject_rate"], "ratio", "SIMULATE gateway"],
        ["disconnects", "total", metrics["5_disconnects"]["total"], "count", "SIMULATE session"],
        ["position_deviation", "worst_n_diffs", metrics["6_position_deviation"]["worst_n_diffs"], "count", "engine vs broker"],
        ["position_deviation", "all_in_sync", metrics["6_position_deviation"]["all_reconciles_in_sync"], "bool", "engine vs broker"],
        ["inventory", "in_session_slots", inventory["in_session_slots"], "count", "collected"],
        ["inventory", "in_session_slots_needed", inventory["in_session_slots_needed_for_decision"], "count", "target"],
    ]
    with open(path, "w", newline="") as f:
        csv.writer(f).writerows(rows)


def _write_summary(path: Path, r: dict) -> None:
    m, inv, v = r["metrics_six_classes"], r["inventory"], r["verdict"]
    lat = m["1_order_latency_ms_submit_to_ack"]
    lines = [
        "# SIMULATE evidence aggregate — EVO-65 (NOT real execution cost)",
        "",
        f"**TrdEnv:** SIMULATE (hard-locked). {r['scope_note']}",
        "",
        f"**Slots:** {inv['slots_total']} total "
        f"({inv['order_path_slots']} order-path, {inv['in_session_slots']} in-session). "
        f"Decision needs ≥ {inv['in_session_slots_needed_for_decision']} in-session "
        f"→ gap {inv['in_session_gap']}.",
        "",
        "## Six metric classes (pooled across slots)",
        f"1. **Order latency (submit→ack)**: p50 {lat.get('p50'):.0f} / p95 "
        f"{lat.get('p95'):.0f} / max {lat.get('max'):.0f} ms (n={lat.get('n')})"
        if lat.get("n") else "1. **Order latency**: no samples",
        f"2. **Slippage**: vs mid p50 {m['2_slippage_bps_vs_arrival_mid'].get('p50')} bps, "
        f"vs touch p50 {m['2b_slippage_bps_vs_arrival_touch'].get('p50')} bps "
        f"(n={m['2_slippage_bps_vs_arrival_mid'].get('n')}, +bps=worse)",
        f"3. **Fill rate**: full_fill_rate {m['3_fill_rate']['full_fill_rate']} "
        f"({m['3_fill_rate']['fully_filled']}/{m['3_fill_rate']['n_buy']})",
        f"4. **Reject rate**: {m['4_reject_rate']['reject_rate']} "
        f"({m['4_reject_rate']['rejected']}/{m['4_reject_rate']['orders']})",
        f"5. **Disconnects**: {m['5_disconnects']['total']}",
        f"6. **Position deviation**: all in-sync={m['6_position_deviation']['all_reconciles_in_sync']}, "
        f"worst diffs={m['6_position_deviation']['worst_n_diffs']}",
        f"   - aux: partial fills observed={m['aux_partial_fill_observed']}; "
        f"SIMULATE fill lag p50="
        f"{(m['aux_fill_latency_s_simulate_engine'] or {}).get('p50')}s",
        "",
        "## Landability judgment",
        f"- real_execution_cost_established: **{v['real_execution_cost_established']}**",
        f"- landable vs Kevin bar ({v['kevin_bar']}): **{v['landable_vs_kevin_bar']}**",
        f"- decision_readiness: **{v['decision_readiness']}**",
        f"- {v['note']}",
        "",
        "### Gaps to a decision",
    ] + [f"- {g}" for g in v["gaps"]] + [
        "",
        f"**Live market context this run:** {r['live_market_context']}",
    ]
    path.write_text("\n".join(lines) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Aggregate OpenD SIMULATE evidence slots")
    ap.add_argument("--reports-dir", default="qlab/reports")
    ap.add_argument("--out", default="qlab/reports/simulate_evidence_summary")
    ap.add_argument("--no-live-check", action="store_true")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=11111)
    args = ap.parse_args(argv)
    r = aggregate(Path(args.reports_dir), Path(args.out),
                  live_check=not args.no_live_check, host=args.host, port=args.port)
    print(json.dumps({"inventory": r["inventory"], "verdict": r["verdict"],
                      "live": r["live_market_context"]}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
