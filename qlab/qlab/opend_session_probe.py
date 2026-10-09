"""In-session OpenD SIMULATE evidence probe — fill-lag-safe.

Captures the session-only real-environment metrics that need the US **regular
session** and marketable orders: measured slippage, fill rate, and partial-fill
behaviour (plus SIMULATE fill latency). Reproducible replacement for the earlier
uncommitted probe, whose close-out raced the fill (SIMULATE fills lag ~seconds,
so closing on an assumed fill mis-sized the flatten).

Fill-lag-safe discipline
------------------------
* Only runs when OpenD reports a **regular session** (``market_us`` in
  MORNING/AFTERNOON), read live via ``get_global_state`` — never inferred. If
  closed, it exits without writing metrics (no fabrication).
* Marketable **cross-price LIMIT** orders (buy = ask+5c, sell = bid-5c) so they
  fill, in ``TrdEnv.SIMULATE``.
* Every order is **polled to a terminal status** (FILLED_ALL / cancelled /
  failed), up to a 90s window; unfilled remainder is cancelled (no leak).
* Close-out re-reads the **actual broker position** and flattens exactly that
  quantity (never an assumed fill) — this is the race fix.
* Pre-clean any leftover position first; finish with a reconcile that must be
  ``in_sync`` and flat.

⚠️ SCOPE: these metrics describe the **OpenD adapter + SIMULATE matching
engine** execution path — NOT real market impact/slippage. Near-zero slippage,
whole-lot matching, no order splitting, and seconds-scale fill lag are SIMULATE
characteristics and must not be read as real execution cost. Real execution
quality requires real fills (real-money / real market matching) and is out of
scope + controlled.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from .brokers.base import Order, OrderType, Side, BrokerError
from .brokers.moomoo_opend import MoomooOpenDBroker
from .observability import Observability

OPEN_STATES = {"MORNING", "AFTERNOON"}          # US regular session (no lunch break)
TERMINAL_FILLED = "FILLED_ALL"
TERMINAL_DEAD = ("CANCELLED_ALL", "CANCELLED_PART", "FAILED", "DELETED", "DISABLED")
POLL_TIMEOUT_S = 90.0
POLL_INTERVAL_S = 2.0
CROSS_CENTS = 0.05


def signed_slippage_bps(side: Side, fill_price: float, ref_price: float):
    """Signed execution slippage in bps. Positive = WORSE than the reference
    (paid above ref on a buy, sold below ref on a sell)."""
    if ref_price is None or ref_price <= 0 or fill_price is None or fill_price <= 0:
        return None
    if side == Side.BUY:
        return (fill_price - ref_price) / ref_price * 1e4
    return (ref_price - fill_price) / ref_price * 1e4


def _pct(vals, p):
    return float(np.percentile(vals, p)) if len(vals) else None


def _stats(vals):
    return {"n": len(vals), "p50": _pct(vals, 50), "p95": _pct(vals, 95),
            "mean": float(np.mean(vals)) if len(vals) else None,
            "min": float(np.min(vals)) if len(vals) else None,
            "max": float(np.max(vals)) if len(vals) else None}


class SessionProbe:
    def __init__(self, broker: MoomooOpenDBroker, obs: Observability, symbol: str):
        self.b = broker
        self.obs = obs
        self.symbol = symbol
        self.orders: list[dict] = []

    def _quote(self):
        # read the book directly for bid/ask (get_snapshot only exposes last_price)
        r, data = self.b._quote_ctx.get_market_snapshot([f"US.{self.symbol}"])
        if r != self.b._sdk.RET_OK:
            raise BrokerError(f"snapshot failed: {data}")
        row = data.to_dict("records")[0]
        bid, ask = float(row["bid_price"]), float(row["ask_price"])
        return {"bid": bid, "ask": ask, "mid": (bid + ask) / 2.0,
                "bid_vol": float(row.get("bid_vol", 0) or 0),
                "ask_vol": float(row.get("ask_vol", 0) or 0),
                "last": float(row.get("last_price", 0) or 0)}

    def _poll_terminal(self, order_id: str, want_qty: int) -> dict:
        """Poll until terminal or timeout; return final state + status_trail."""
        ack = time.time()
        trail = []
        filled_time = None
        while time.time() - ack < POLL_TIMEOUT_S:
            st = self.b.order_status(order_id)
            trail.append({"t": round(time.time() - ack, 2),
                          "status": st["order_status"], "dealt": st["dealt_qty"]})
            if st["order_status"] == TERMINAL_FILLED and filled_time is None:
                filled_time = time.time()
            if st["order_status"] == TERMINAL_FILLED or st["order_status"].startswith(TERMINAL_DEAD):
                break
            time.sleep(POLL_INTERVAL_S)
        st = self.b.order_status(order_id)
        return {"final_status": st["order_status"], "dealt_qty": st["dealt_qty"],
                "avg_price": st["dealt_avg_price"], "status_trail": trail,
                "ack_ts": ack, "fill_latency_s": (filled_time - ack) if filled_time else None}

    def trade_leg(self, side: Side, qty: int, tag: str) -> dict:
        q = self._quote()
        if side == Side.BUY:
            limit = round(q["ask"] + CROSS_CENTS, 2)
            arrival_touch = q["ask"]
        else:
            limit = round(q["bid"] - CROSS_CENTS, 2)
            arrival_touch = q["bid"]
        arrival_mid = q["mid"]
        order = Order(symbol=self.symbol, side=side, qty=qty, order_type=OrderType.LIMIT,
                      limit_price=limit, reason=f"session_probe:{tag}")
        rec = {"tag": tag, "side": side.value, "qty": qty, "limit": limit,
               "arrival_mid": arrival_mid, "arrival_touch": arrival_touch,
               "arrival_bid_vol": q["bid_vol"], "arrival_ask_vol": q["ask_vol"]}
        try:
            o = self.b.place_order(order)
            rec["order_id"] = o.order_id
            rec["submit_ack_latency_ms"] = o.latency_ms
        except BrokerError as e:
            rec["rejected"] = True
            rec["error"] = str(e)[:160]
            self.obs.order(**rec)
            self.orders.append(rec)
            return rec
        poll = self._poll_terminal(o.order_id, qty)
        rec.update(poll)
        rec["filled_qty"] = poll["dealt_qty"]
        rec["fully_filled"] = poll["dealt_qty"] == qty and poll["final_status"] == TERMINAL_FILLED
        rec["partial"] = 0 < poll["dealt_qty"] < qty
        # cancel any un-filled remainder to avoid leak
        if poll["dealt_qty"] < qty and poll["final_status"] not in TERMINAL_DEAD:
            try:
                self.b.cancel_order(o.order_id)
                rec["cancelled_remainder"] = qty - poll["dealt_qty"]
            except BrokerError as e:
                self.obs.error("cancel_remainder", str(e), order_id=o.order_id)
        # signed slippage in bps (+ = worse execution)
        if poll["dealt_qty"] > 0 and poll["avg_price"] > 0:
            fp = poll["avg_price"]
            rec["slip_mid_bps"] = signed_slippage_bps(side, fp, arrival_mid)
            rec["slip_touch_bps"] = signed_slippage_bps(side, fp, arrival_touch)
        self.obs.order(**{k: v for k, v in rec.items() if k != "status_trail"})
        self.orders.append(rec)
        return rec

    def flatten_symbol(self, tag: str) -> dict:
        """Fill-lag-safe close-out: read ACTUAL position, sell exactly that."""
        pos = self.b.get_positions().get(self.symbol)
        held = pos.qty if pos else 0
        if held <= 0:
            self.b.reconcile_positions({})
            return {"held": 0, "closed": 0}
        rec = self.trade_leg(Side.SELL, held, tag)
        return {"held": held, "closed": rec.get("filled_qty", 0), "leg": rec}


def probe(out_dir: Path, symbol: str = "AAPL", n_qty1: int = 8, n_qty100: int = 2,
          host: str = "127.0.0.1", port: int = 11111, security_firm: str = "FUTUSG"):
    out_dir.mkdir(parents=True, exist_ok=True)
    obs = Observability(out_dir, also_stdout=True)
    broker = MoomooOpenDBroker(host=host, port=port, trd_env="SIMULATE",
                               security_firm=security_firm, max_retries=2, logger=obs)
    m: dict = {"probe": "opend_session_simulate", "symbol": symbol,
               "host": f"{host}:{port}", "security_firm": security_firm,
               "scope_note": "SIMULATE matching-engine execution path, NOT real "
                             "market impact/slippage — see README."}

    t0 = time.perf_counter()
    broker.connect()
    m["connect_latency_ms"] = (time.perf_counter() - t0) * 1000.0
    sdk = broker._sdk
    r, gs = broker._quote_ctx.get_global_state()
    market_us = gs.get("market_us") if r == sdk.RET_OK else "UNKNOWN"
    m["market_us"] = market_us
    m["trd_logined"] = gs.get("trd_logined") if r == sdk.RET_OK else None
    m["qot_logined"] = gs.get("qot_logined") if r == sdk.RET_OK else None
    obs.broker_event("opend", "global_state", market_us=market_us,
                     trd_logined=m["trd_logined"], qot_logined=m["qot_logined"])

    if market_us not in OPEN_STATES:
        m["status"] = "SKIPPED_MARKET_CLOSED"
        m["note"] = f"market_us={market_us} not a regular session; session-only " \
                    "metrics require MORNING/AFTERNOON. No data fabricated."
        (out_dir / "session_metrics.json").write_text(json.dumps(m, indent=2, default=str))
        obs.broker_event("opend", "probe_skipped", market_us=market_us)
        broker.close(); obs.close()
        return m

    sp = SessionProbe(broker, obs, symbol)
    q0 = sp._quote()
    m["arrival_book"] = {"bid": q0["bid"], "ask": q0["ask"], "spread": round(q0["ask"] - q0["bid"], 4)}

    # 0) pre-clean leftover position, then reconcile to zero
    pre = sp.flatten_symbol("preclean")
    m["preclean"] = {"held_before": pre["held"], "closed": pre["closed"]}
    obs.broker_event("opend", "preclean_done", **m["preclean"])

    # 1) marketable BUY battery (mix qty to probe partial fills)
    plan = [("buy_q1", 1)] * n_qty1 + [("buy_q100", 100)] * n_qty100
    for tag, qty in plan:
        sp.trade_leg(Side.BUY, qty, tag)

    # 2) fill-lag-safe close-out of the ACTUAL accumulated position
    close = sp.flatten_symbol("closeout")
    m["closeout"] = {"held": close["held"], "closed": close["closed"]}

    # 3) final reconcile (must be flat + in sync)
    recon = broker.reconcile_positions({})
    m["reconcile"] = recon
    m["positions_flat_after"] = recon["in_sync"] and not recon["broker_positions"]

    # --- metrics ---
    buys = [o for o in sp.orders if o["side"] == "BUY" and o["tag"].startswith("buy")]
    n_buy = len(buys)
    fully = sum(1 for o in buys if o.get("fully_filled"))
    rejected = sum(1 for o in buys if o.get("rejected"))
    partials = [o for o in buys if o.get("partial")]
    m["fill_rate"] = {"n_buy": n_buy, "fully_filled": fully, "rejected": rejected,
                      "full_fill_rate": round(fully / n_buy, 4) if n_buy else None}
    legs = [o for o in sp.orders if o.get("filled_qty", 0) > 0 and "slip_mid_bps" in o]
    m["actual_slippage_bps"] = {
        "vs_arrival_mid": _stats([o["slip_mid_bps"] for o in legs]),
        "vs_arrival_touch": _stats([o["slip_touch_bps"] for o in legs]),
        "buy_vs_mid_p50": _pct([o["slip_mid_bps"] for o in legs if o["side"] == "BUY"], 50),
        "sell_vs_mid_p50": _pct([o["slip_mid_bps"] for o in legs if o["side"] == "SELL"], 50),
    }
    m["partial_fill_behavior"] = {
        "observed": len(partials) > 0, "n_partial": len(partials),
        "note": "SIMULATE matches marketable orders whole-lot; no splitting observed."
                if not partials else "partial fills observed (see order list)",
    }
    fl = [o["fill_latency_s"] for o in sp.orders if o.get("fill_latency_s")]
    m["fill_latency_s"] = _stats(fl)
    m["fill_latency_s"]["note"] = "SIMULATE matching-engine lag (ack->FILLED_ALL); " \
                                  "seconds-scale, NOT a real-market fill speed."
    m["orders"] = sp.orders
    m["status"] = "OK_SESSION_METRICS"

    (out_dir / "session_metrics.json").write_text(json.dumps(m, indent=2, default=str))
    obs.broker_event("opend", "probe_complete", status=m["status"],
                     full_fill_rate=m["fill_rate"]["full_fill_rate"])
    broker.close(); obs.close()
    return m


def main(argv=None):
    ap = argparse.ArgumentParser(description="In-session OpenD SIMULATE evidence probe (fill-lag-safe)")
    ap.add_argument("--symbol", default="AAPL")
    ap.add_argument("--n-qty1", type=int, default=8)
    ap.add_argument("--n-qty100", type=int, default=2)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=11111)
    ap.add_argument("--security-firm", default="FUTUSG")
    ap.add_argument("--out", default="qlab/reports/opend_session_live")
    args = ap.parse_args(argv)
    m = probe(Path(args.out), symbol=args.symbol, n_qty1=args.n_qty1, n_qty100=args.n_qty100,
              host=args.host, port=args.port, security_firm=args.security_firm)
    keys = ("status", "market_us", "fill_rate", "actual_slippage_bps",
            "partial_fill_behavior", "fill_latency_s", "positions_flat_after")
    print(json.dumps({k: m[k] for k in keys if k in m}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
