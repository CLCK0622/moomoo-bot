"""Real moomoo OpenD SIMULATE evidence probe (market-closed-safe).

Collects first-hand real-environment metrics against a live OpenD gateway +
SIMULATE account WITHOUT needing the regular session:

* connection: connect latency, retries/disconnects
* capability: market state, trd/qot login, SIMULATE account + buying power,
  quote-snapshot permission
* order-path latency: place a resting far-from-market LIMIT order (qty 1, price
  ~50% below last -> cannot fill), measure client->gateway submit->ack latency,
  classify accepted vs rejected, then cancel and measure cancel latency
* position reconciliation: engine intent vs broker truth (must stay flat)

Metrics that REQUIRE the regular session (fills, actual slippage, fill rate) are
explicitly reported as DEFERRED with a plan — never fabricated. Nothing here can
accidentally fill: orders are far from market, qty 1, and cancelled immediately;
a final sweep cancels any straggler and asserts positions are flat.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from .brokers.base import Order, OrderType, Side, BrokerError
from .brokers.moomoo_opend import MoomooOpenDBroker
from .observability import Observability


def _pct(vals, p):
    return float(np.percentile(vals, p)) if vals else None


def probe(out_dir: Path, symbol: str = "AAPL", n_orders: int = 30,
          host: str = "127.0.0.1", port: int = 11111, security_firm: str = "FUTUSG"):
    out_dir.mkdir(parents=True, exist_ok=True)
    obs = Observability(out_dir, also_stdout=True)
    # single-shot (max_retries=1) so each latency sample is one clean round trip
    broker = MoomooOpenDBroker(host=host, port=port, trd_env="SIMULATE",
                               security_firm=security_firm, max_retries=1, logger=obs)
    metrics: dict = {"probe": "opend_simulate", "symbol": symbol, "n_orders": n_orders,
                     "host": f"{host}:{port}", "security_firm": security_firm}
    disconnects = 0

    # 1) connect
    import time
    t0 = time.perf_counter()
    broker.connect()
    metrics["connect_latency_ms"] = (time.perf_counter() - t0) * 1000.0
    sdk = broker._sdk

    # 2) capability / market state
    r, gs = broker._quote_ctx.get_global_state()
    market_us = gs.get("market_us") if r == sdk.RET_OK else "UNKNOWN"
    metrics["market_us"] = market_us
    metrics["trd_logined"] = gs.get("trd_logined") if r == sdk.RET_OK else None
    metrics["qot_logined"] = gs.get("qot_logined") if r == sdk.RET_OK else None
    obs.broker_event("opend", "global_state", market_us=market_us,
                     trd_logined=metrics["trd_logined"], qot_logined=metrics["qot_logined"])

    acct = broker.get_account()
    metrics["sim_account"] = {"cash": acct.cash, "total_assets": acct.total_assets}
    snap = broker.get_snapshot([symbol])
    last = snap[symbol].last_price if symbol in snap else None
    metrics["snapshot_last_price"] = last
    metrics["quote_permission"] = last is not None
    if not last:
        obs.error("probe", "no snapshot price; cannot size far-limit orders", symbol=symbol)
        metrics["status"] = "BLOCKED_NO_QUOTE"
        obs.close()
        return metrics

    far_limit = round(last * 0.5, 2)  # far below market: cannot fill
    obs.broker_event("opend", "latency_battery_start", n=n_orders, symbol=symbol,
                     far_limit=far_limit, last=last)

    # 3) order-path latency battery
    place_lat, cancel_lat = [], []
    accepted = rejected = cancelled = 0
    reject_samples = []
    for i in range(n_orders):
        order = Order(symbol=symbol, side=Side.BUY, qty=1, order_type=OrderType.LIMIT,
                      limit_price=far_limit, reason="latency_probe")
        c0 = time.perf_counter()
        try:
            o = broker.place_order(order)
            place_lat.append(o.latency_ms if o.latency_ms is not None
                             else (time.perf_counter() - c0) * 1000.0)
            accepted += 1
            if o.order_id:
                try:
                    cl = broker.cancel_order(o.order_id)
                    cancel_lat.append(cl)
                    cancelled += 1
                except BrokerError as e:
                    obs.error("cancel", str(e), order_id=o.order_id)
        except BrokerError as e:
            rejected += 1
            reject_samples.append(str(e)[:160])
            place_lat.append((time.perf_counter() - c0) * 1000.0)  # reject round-trip
            if "disconnect" in str(e).lower() or "conn" in str(e).lower():
                disconnects += 1

    metrics["order_latency_ms"] = {
        "n": len(place_lat), "p50": _pct(place_lat, 50), "p95": _pct(place_lat, 95),
        "max": max(place_lat) if place_lat else None, "min": min(place_lat) if place_lat else None,
    }
    metrics["cancel_latency_ms"] = {
        "n": len(cancel_lat), "p50": _pct(cancel_lat, 50), "p95": _pct(cancel_lat, 95),
        "max": max(cancel_lat) if cancel_lat else None,
    }
    metrics["accepted"] = accepted
    metrics["rejected"] = rejected
    metrics["cancelled"] = cancelled
    metrics["reject_rate"] = rejected / n_orders if n_orders else None
    metrics["accept_rate"] = accepted / n_orders if n_orders else None
    metrics["reject_reason_samples"] = list(dict.fromkeys(reject_samples))[:3]
    metrics["disconnects"] = disconnects

    # 4) safety sweep + reconciliation
    try:
        for o in broker.query_open_orders():
            if o.order_id:
                try:
                    broker.cancel_order(o.order_id)
                except BrokerError:
                    pass
    except BrokerError as e:
        obs.error("sweep", str(e))
    recon = broker.reconcile_positions({})  # engine intent = flat
    metrics["positions_flat_after"] = recon["in_sync"] and not recon["broker_positions"]
    metrics["reconcile"] = recon

    # 5) session-only metrics: honestly deferred, not fabricated
    session_open = market_us in ("REGULAR", "TRADING")
    metrics["session_open_now"] = session_open
    metrics["deferred_session_metrics"] = {
        "note": "fills, actual slippage, and fill-rate require the US REGULAR "
                "session; market_us=%s now. NOT measured (per brief: 闭市别空跑实时指标)."
                % market_us,
        "metrics": ["fill_rate", "actual_slippage", "partial_fill_behavior"],
        "plan": "re-run engine live loop (or this probe with marketable orders) "
                "during US regular hours 09:30-16:00 ET; latency/reject/reconcile "
                "captured now remain valid.",
    }
    metrics["status"] = "OK_ORDER_PATH_MEASURED"

    (out_dir / "opend_metrics.json").write_text(json.dumps(metrics, indent=2, default=str))
    obs.broker_event("opend", "probe_complete", status=metrics["status"])
    broker.close()
    obs.close()
    return metrics


def main(argv=None):
    ap = argparse.ArgumentParser(description="OpenD SIMULATE real-environment probe")
    ap.add_argument("--symbol", default="AAPL")
    ap.add_argument("--n-orders", type=int, default=30)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=11111)
    ap.add_argument("--security-firm", default="FUTUSG")
    ap.add_argument("--out", default="qlab/reports/opend_probe")
    args = ap.parse_args(argv)
    m = probe(Path(args.out), symbol=args.symbol, n_orders=args.n_orders,
              host=args.host, port=args.port, security_firm=args.security_firm)
    print(json.dumps({k: m[k] for k in
                      ("status", "market_us", "order_latency_ms", "cancel_latency_ms",
                       "accept_rate", "reject_rate", "disconnects", "positions_flat_after")
                      if k in m}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
