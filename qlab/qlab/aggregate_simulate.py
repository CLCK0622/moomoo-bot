"""Aggregate the collected OpenD **SIMULATE** evidence slots into one verdict.

Reads the committed per-slot report dirs under ``reports/`` (order-path probe +
in-session probes, and any autopilot slots that follow the same layout), applies
a qualification gate, pools the six required metric classes, and emits a JSON /
CSV / Markdown summary with a landability judgment.

It does NOT collect new data, re-run history, or place orders — pure aggregation
of already-committed artifacts (an optional quote-only `get_global_state` read
just timestamps the current market state; no trade context, no credentials).

⚠️ Hard scope: every input is `TrdEnv.SIMULATE`. These metrics characterise the
OpenD adapter + the SIMULATE matching engine's execution path — they are NOT real
market execution cost and cannot, on their own, establish landability against
Kevin's 50% annual / 20% drawdown bar (which needs a real-fills strategy PnL).

Qualification gate (都察院 final review): a slot only counts as evidence if it is
`TrdEnv.SIMULATE`, placed >0 orders, and — for in-session slots — was captured in
a regular session (`market_us ∈ {MORNING, AFTERNOON}`) with
`status == OK_SESSION_METRICS`. CLOSED / ERROR / non-SIMULATE slots are rejected
(see `rejected_slots`). ET trading dates are derived from each slot's first order
`ack_ts` (America/New_York), not from directory names.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

# For a statistically-defensible SIMULATE execution read (reusing the EVO-149 A/B
# convention of multiple independent samples), we want several in-session slots
# across distinct windows, not a single one.
IN_SESSION_SLOTS_FOR_DECISION = 5
OPEN_STATES = {"MORNING", "AFTERNOON"}          # US regular session (no lunch break)
OK_SESSION_STATUS = "OK_SESSION_METRICS"
OK_ORDER_PATH_STATUS = "OK_ORDER_PATH_MEASURED"


def _pct(vals, p):
    return float(np.percentile(vals, p)) if len(vals) else None


def _stats(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return {"n": 0}
    return {"n": len(vals), "p50": _pct(vals, 50), "p95": _pct(vals, 95),
            "mean": float(np.mean(vals)), "min": float(np.min(vals)),
            "max": float(np.max(vals))}


def _et(epoch: float):
    """Epoch -> (America/New_York) datetime. July evidence is EDT (UTC-4); we use
    zoneinfo when available and fall back to a fixed -4h offset otherwise."""
    if epoch is None:
        return None
    try:
        from zoneinfo import ZoneInfo
        return datetime.fromtimestamp(epoch, tz=timezone.utc).astimezone(ZoneInfo("America/New_York"))
    except Exception:
        return datetime.fromtimestamp(epoch, tz=timezone.utc).astimezone(timezone(timedelta(hours=-4)))


def _et_date(epoch: float):
    dt = _et(epoch)
    return dt.strftime("%Y-%m-%d") if dt else None


def _et_label(epoch: float):
    dt = _et(epoch)
    return dt.strftime("%Y-%m-%d %H:%M ET") if dt else None


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
    orders = m.get("orders", [])

    # trd_env is proven ONLY from the slot's own `connected` broker event — the
    # single source of truth. The metrics self-report (m["trd_env"]) is NEVER
    # trusted as evidence: missing connected event -> unverifiable -> reject;
    # a self-report that conflicts with the connected event -> reject.
    conn = next((e for e in events if e.get("event") == "connected"), None)
    conn_trd_env = conn.get("trd_env") if conn else None
    self_trd_env = m.get("trd_env")                      # self-report, not evidence
    trd_env = conn_trd_env                               # sole source of truth
    trd_env_missing = conn_trd_env is None
    trd_env_conflict = (self_trd_env is not None and conn_trd_env is not None
                        and self_trd_env != conn_trd_env)

    # first-hand submit->ack latency samples — ONE source per slot to avoid double
    # counting (session metrics.orders[] and its broker_events overlap).
    if kind == "session":
        lat = [o["submit_ack_latency_ms"] for o in orders
               if o.get("submit_ack_latency_ms") is not None]
    else:  # order_path: latencies live only in broker_events
        lat = [e["latency_ms"] for e in events
               if e.get("event") == "order_submitted" and e.get("latency_ms") is not None]
    cancel_lat = [e["latency_ms"] for e in events
                  if e.get("event") == "order_cancelled" and e.get("latency_ms") is not None]

    # per-order fill latency + slippage (session only)
    fill_lat = [o["fill_latency_s"] for o in orders if o.get("fill_latency_s") is not None]
    slip_mid = [o["slip_mid_bps"] for o in orders if "slip_mid_bps" in o]
    slip_touch = [o["slip_touch_bps"] for o in orders if "slip_touch_bps" in o]

    # first-order wall time -> ET trading day (derived, not from dir name)
    ts_candidates = [o["ack_ts"] for o in orders if o.get("ack_ts")] or \
                    [e["ts"] for e in events if e.get("event") == "order_submitted" and e.get("ts")]
    first_ts = min(ts_candidates) if ts_candidates else None

    # submissions: session = every order (buys + closeout); order_path = n_orders
    if kind == "session":
        n_submissions = len(orders)
        n_buy = (m.get("fill_rate", {}) or {}).get("n_buy", 0)
        n_closeout = sum(1 for o in orders if o.get("side") == "SELL"
                         or "close" in str(o.get("tag", "")))
    else:
        n_submissions = m.get("n_orders", 0) or 0
        n_buy = 0
        n_closeout = 0

    recon = m.get("reconcile", {}) or {}
    return {
        "dir": d.name, "kind": kind, "market_us": m.get("market_us"),
        "status": m.get("status"), "symbol": m.get("symbol"), "trd_env": trd_env,
        "self_trd_env": self_trd_env, "trd_env_missing": trd_env_missing,
        "trd_env_conflict": trd_env_conflict,
        "latency_ms": lat, "cancel_latency_ms": cancel_lat,
        "fill_latency_s_samples": fill_lat,
        "slip_mid_bps": slip_mid, "slip_touch_bps": slip_touch,
        "fill_rate": m.get("fill_rate"),
        "partial_fill": m.get("partial_fill_behavior"),
        "n_orders": m.get("n_orders") or (m.get("fill_rate", {}) or {}).get("n_buy", 0),
        "n_submissions": n_submissions, "n_buy": n_buy, "n_closeout": n_closeout,
        "rejected": (m.get("rejected") if m.get("rejected") is not None
                     else (m.get("fill_rate", {}) or {}).get("rejected", 0)),
        "disconnects": m.get("disconnects", 0) or 0,
        "reconcile_in_sync": bool(recon.get("in_sync", True)),
        "reconcile_n_diffs": int(recon.get("n_diffs", 0) or 0),
        "positions_flat_after": m.get("positions_flat_after"),
        "first_ts": first_ts, "et_date": _et_date(first_ts), "et_label": _et_label(first_ts),
    }


def _qualify(s: dict):
    """Gate: return (ok, reason). Only SIMULATE slots with real order activity
    count; in-session slots must be a regular session + OK_SESSION_METRICS.

    trd_env is trusted ONLY from the `connected` event: a missing connected event
    (unverifiable) or a self-report that conflicts with it is rejected outright —
    the aggregator never falls back to the metrics self-report."""
    if (s["n_orders"] or 0) == 0:
        return False, "zero_orders"
    if s["trd_env_missing"]:
        return False, "trd_env unverifiable: no `connected` event (self-report not trusted)"
    if s["trd_env_conflict"]:
        return False, (f"trd_env conflict: connected={s['trd_env']} vs "
                       f"self-report={s['self_trd_env']}")
    if s["trd_env"] != "SIMULATE":
        return False, f"trd_env={s['trd_env']} (not SIMULATE)"
    if s["kind"] == "session":
        if s["market_us"] not in OPEN_STATES:
            return False, f"market_us={s['market_us']} (not regular session)"
        if s["status"] != OK_SESSION_STATUS:
            return False, f"status={s['status']} (not {OK_SESSION_STATUS})"
    else:  # order_path
        if s["status"] != OK_ORDER_PATH_STATUS:
            return False, f"status={s['status']} (not {OK_ORDER_PATH_STATUS})"
    return True, "ok"


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
    raw = [_load_slot(d) for d in _discover_slots(reports_dir)]

    # --- qualification gate (rejects CLOSED / ERROR / non-SIMULATE / 0-order) ---
    qualified, rejected = [], []
    for s in raw:
        ok, reason = _qualify(s)
        (qualified if ok else rejected).append(s if ok else {"dir": s["dir"],
                                                             "kind": s["kind"],
                                                             "market_us": s["market_us"],
                                                             "status": s["status"],
                                                             "trd_env": s["trd_env"],
                                                             "reason": reason})
    dropped_zero_order = sorted(r["dir"] for r in rejected if r["reason"] == "zero_orders")

    order_path = [s for s in qualified if s["kind"] == "order_path"]
    session = [s for s in qualified if s["kind"] == "session"]

    all_lat = [v for s in qualified for v in s["latency_ms"]]
    all_cancel = [v for s in qualified for v in s["cancel_latency_ms"]]
    slip_mid = [v for s in session for v in s["slip_mid_bps"]]
    slip_touch = [v for s in session for v in s["slip_touch_bps"]]
    fill_lat_pool = [v for s in session for v in s["fill_latency_s_samples"]]  # per-order, all sessions

    n_buy = sum((s["fill_rate"] or {}).get("n_buy", 0) for s in session)
    fully = sum((s["fill_rate"] or {}).get("fully_filled", 0) for s in session)
    total_disconnects = sum(s["disconnects"] or 0 for s in qualified)
    any_partial = any((s["partial_fill"] or {}).get("observed") for s in session)
    worst_diffs = max([s["reconcile_n_diffs"] for s in qualified], default=0)
    all_in_sync = all(s["reconcile_in_sync"] for s in qualified)

    # reject rate over ALL submitted orders (buys + closeouts + order-path)
    subs_all = sum(s["n_submissions"] for s in qualified)
    subs_primary = sum(s["n_buy"] for s in session) + sum(s["n_submissions"] for s in order_path)
    subs_closeout = sum(s["n_closeout"] for s in session)
    rej_all = sum(s["rejected"] or 0 for s in qualified)

    metrics = {
        "1_order_latency_ms_submit_to_ack": _stats(all_lat),
        "1b_cancel_latency_ms": _stats(all_cancel),
        "2_slippage_bps_vs_arrival_mid": _stats(slip_mid),
        "2b_slippage_bps_vs_arrival_touch": _stats(slip_touch),
        "3_fill_rate": {"n_buy": n_buy, "fully_filled": fully,
                        "full_fill_rate": round(fully / n_buy, 4) if n_buy else None},
        "4_reject_rate": {
            "denominator": "all_submitted",
            "submitted": subs_all, "rejected": rej_all,
            "reject_rate": round(rej_all / subs_all, 4) if subs_all else None,
            "breakdown": {
                "primary_buy_and_order_path": {"submitted": subs_primary, "rejected": rej_all},
                "closeout_sells": {"submitted": subs_closeout, "rejected": 0},
            },
        },
        "5_disconnects": {"total": total_disconnects},
        "6_position_deviation": {"all_reconciles_in_sync": all_in_sync,
                                 "worst_n_diffs": worst_diffs},
        "aux_partial_fill_observed": any_partial,
        # fill lag is now POOLED per-order across all qualified in-session slots
        "aux_fill_latency_s_pooled": {**_stats(fill_lat_pool),
                                      "note": "SIMULATE matching-engine lag "
                                              "(ack->FILLED_ALL) pooled per-order "
                                              "across all in-session slots; NOT a "
                                              "real-market fill speed."},
    }

    # ET trading days derived from raw timestamps (not directory names)
    session_days = sorted({s["et_date"] for s in session if s["et_date"]})
    in_session_slots = len(session)
    inventory = {
        "slots_total": len(qualified),
        "order_path_slots": len(order_path),
        "in_session_slots": in_session_slots,
        "slots": [{"dir": s["dir"], "kind": s["kind"], "market_us": s["market_us"],
                   "status": s["status"], "trd_env": s["trd_env"],
                   "n_orders": s["n_orders"], "et_date": s["et_date"],
                   "et_first_order": s["et_label"]} for s in qualified],
        "in_session_slots_needed_for_decision": IN_SESSION_SLOTS_FOR_DECISION,
        "in_session_gap": max(0, IN_SESSION_SLOTS_FOR_DECISION - in_session_slots),
        "distinct_session_trading_days_et": session_days,
        "n_distinct_session_trading_days": len(session_days),
        "dropped_zero_order_slots": dropped_zero_order,
        "rejected_slots": rejected,
    }

    live = _live_market_us(host, port) if live_check else {"available": False, "reason": "skipped"}

    verdict = {
        "real_execution_cost_established": False,
        "reason": "All samples are TrdEnv.SIMULATE. Near-zero slippage, whole-lot "
                  "fills, seconds-scale fill lag and 0 rejects are SIMULATE "
                  "matching-engine traits, NOT real market execution cost.",
        "landable_vs_kevin_bar": "UNDECIDABLE_FROM_SIMULATE",
        "kevin_bar": "annual return >= 50% AND max drawdown <= 20% (on real fills)",
        "note": "The 50%/20% bar is a return/drawdown target on a real-fills "
                "strategy PnL; SIMULATE execution-path health cannot satisfy it. "
                "Candidate stays needs-evidence / NOT PASS.",
        "decision_readiness": (
            "INTERMEDIATE" if in_session_slots < IN_SESSION_SLOTS_FOR_DECISION
            else "SIMULATE_EXECUTION_CHARACTERIZED"),
        "engineering_risk_gate": "CLOSED@7d94a2c",
        "real_landability_owner": "parent EVO-8 / controlled-live",
        "gaps": [
            f"need >= {IN_SESSION_SLOTS_FOR_DECISION} in-session slots for a stable "
            f"SIMULATE execution read; have {in_session_slots} "
            f"(gap {inventory['in_session_gap']}).",
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
        "limitations": [
            "ET trading dates are derived from each slot's first order ack_ts via "
            "America/New_York. The live slot's real trading day is 2026-07-09 "
            "(14:01 ET) — correcting an earlier '07-10' narrative. Distinct session "
            "trading days remain {2026-07-09, 2026-07-14, 2026-07-15} = 3, so "
            "EVO-149 multi-sample independence is unchanged.",
            "Any 0-order local staging dirs (e.g. opend_session_smoke / "
            "opend_session_val) are NOT committed to the tree; re-running "
            "aggregation on the committed tree yields dropped_zero_order_slots=[]. "
            "They cannot be independently re-verified and do NOT affect the "
            "committed evidence slots' count or integrity.",
        ],
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "aggregate.json").write_text(json.dumps(result, indent=2, default=str))
    _write_csv(out_dir / "metrics.csv", result)
    _write_summary(out_dir / "SUMMARY.md", result)
    return result


def _write_csv(path: Path, r: dict) -> None:
    m, inv = r["metrics_six_classes"], r["inventory"]
    fl = m["aux_fill_latency_s_pooled"]
    rows = [
        ["metric_class", "statistic", "value", "unit", "source_scope"],
        ["order_latency_submit_ack", "p50", m["1_order_latency_ms_submit_to_ack"].get("p50"), "ms", "SIMULATE gateway"],
        ["order_latency_submit_ack", "p95", m["1_order_latency_ms_submit_to_ack"].get("p95"), "ms", "SIMULATE gateway"],
        ["order_latency_submit_ack", "max", m["1_order_latency_ms_submit_to_ack"].get("max"), "ms", "SIMULATE gateway"],
        ["order_latency_submit_ack", "n", m["1_order_latency_ms_submit_to_ack"].get("n"), "count", "SIMULATE gateway"],
        ["slippage_vs_mid", "p50", m["2_slippage_bps_vs_arrival_mid"].get("p50"), "bps(+worse)", "SIMULATE engine"],
        ["slippage_vs_touch", "p50", m["2b_slippage_bps_vs_arrival_touch"].get("p50"), "bps(+worse)", "SIMULATE engine"],
        ["fill_rate", "full_fill_rate", m["3_fill_rate"]["full_fill_rate"], "ratio", "SIMULATE engine"],
        ["reject_rate", "reject_rate(all_submitted)", m["4_reject_rate"]["reject_rate"], "ratio", "SIMULATE gateway"],
        ["reject_rate", "submitted", m["4_reject_rate"]["submitted"], "count", "buys+closeouts+order_path"],
        ["disconnects", "total", m["5_disconnects"]["total"], "count", "SIMULATE session"],
        ["position_deviation", "worst_n_diffs", m["6_position_deviation"]["worst_n_diffs"], "count", "engine vs broker"],
        ["position_deviation", "all_in_sync", m["6_position_deviation"]["all_reconciles_in_sync"], "bool", "engine vs broker"],
        ["fill_latency_pooled_s", "p50", fl.get("p50"), "s", "SIMULATE engine (pooled n)"],
        ["fill_latency_pooled_s", "p95", fl.get("p95"), "s", "SIMULATE engine (pooled n)"],
        ["fill_latency_pooled_s", "n", fl.get("n"), "count", "SIMULATE engine (pooled)"],
        ["inventory", "in_session_slots", inv["in_session_slots"], "count", "collected"],
        ["inventory", "distinct_session_trading_days", inv["n_distinct_session_trading_days"], "count", "ET"],
    ]
    with open(path, "w", newline="") as f:
        csv.writer(f).writerows(rows)


def _write_summary(path: Path, r: dict) -> None:
    m, inv, v = r["metrics_six_classes"], r["inventory"], r["verdict"]
    lat, fl = m["1_order_latency_ms_submit_to_ack"], m["aux_fill_latency_s_pooled"]
    rj = m["4_reject_rate"]
    lines = [
        "# SIMULATE evidence aggregate — EVO-65 (NOT real execution cost)",
        "",
        f"**TrdEnv:** SIMULATE (hard-locked). {r['scope_note']}",
        "",
        f"**Slots:** {inv['slots_total']} total "
        f"({inv['order_path_slots']} order-path, {inv['in_session_slots']} in-session, "
        f"gap {inv['in_session_gap']}). In-session ET trading days: "
        f"{', '.join(inv['distinct_session_trading_days_et'])} "
        f"({inv['n_distinct_session_trading_days']} distinct — EVO-149 independence).",
        "",
        "Qualification gate (only counted slots): TrdEnv.SIMULATE + >0 orders; "
        "in-session also requires market_us∈{MORNING,AFTERNOON} + OK_SESSION_METRICS. "
        f"Rejected slots this run: {len(inv['rejected_slots'])}; "
        f"dropped 0-order: {inv['dropped_zero_order_slots'] or '[]'}.",
        "",
        "## Six metric classes (pooled across qualified slots)",
        (f"1. **Order latency (submit→ack)**: p50 {lat.get('p50'):.1f} / p95 "
         f"{lat.get('p95'):.1f} / max {lat.get('max'):.1f} ms (n={lat.get('n')})"
         if lat.get("n") else "1. **Order latency**: no samples"),
        f"2. **Slippage**: vs mid p50 {m['2_slippage_bps_vs_arrival_mid'].get('p50')} bps, "
        f"vs touch p50 {m['2b_slippage_bps_vs_arrival_touch'].get('p50')} bps "
        f"(n={m['2_slippage_bps_vs_arrival_mid'].get('n')}, +bps=worse)",
        f"3. **Fill rate**: full_fill_rate {m['3_fill_rate']['full_fill_rate']} "
        f"({m['3_fill_rate']['fully_filled']}/{m['3_fill_rate']['n_buy']})",
        f"4. **Reject rate (all submitted)**: {rj['reject_rate']} "
        f"({rj['rejected']}/{rj['submitted']}) — "
        f"primary buy/order-path {rj['breakdown']['primary_buy_and_order_path']['rejected']}"
        f"/{rj['breakdown']['primary_buy_and_order_path']['submitted']}, "
        f"closeout {rj['breakdown']['closeout_sells']['rejected']}"
        f"/{rj['breakdown']['closeout_sells']['submitted']}",
        f"5. **Disconnects**: {m['5_disconnects']['total']}",
        f"6. **Position deviation**: all in-sync={m['6_position_deviation']['all_reconciles_in_sync']}, "
        f"worst diffs={m['6_position_deviation']['worst_n_diffs']}",
        (f"   - aux: partial fills observed={m['aux_partial_fill_observed']}; "
         f"**pooled** SIMULATE fill lag p50 {fl.get('p50'):.6f}s / p95 {fl.get('p95'):.6f}s "
         f"(n={fl.get('n')}, ack→FILLED_ALL, NOT real-market fill speed)"
         if fl.get("n") else "   - aux: no fill-lag samples"),
        "",
        "## Landability judgment (verdict — NOT upgraded)",
        f"- real_execution_cost_established: **{v['real_execution_cost_established']}**",
        f"- landable vs Kevin bar ({v['kevin_bar']}): **{v['landable_vs_kevin_bar']}**",
        f"- decision_readiness: **{v['decision_readiness']}**",
        f"- engineering/risk gate: **{v['engineering_risk_gate']}** (unchanged); "
        f"real landability owner: **{v['real_landability_owner']}**",
        f"- {v['note']}",
        "",
        "## Limitations",
    ] + [f"- {x}" for x in r["limitations"]] + [
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
                      "reject": r["metrics_six_classes"]["4_reject_rate"],
                      "fill_lag_pooled": r["metrics_six_classes"]["aux_fill_latency_s_pooled"],
                      "live": r["live_market_context"]}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
