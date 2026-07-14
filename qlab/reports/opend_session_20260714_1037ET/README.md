# In-session OpenD SIMULATE evidence slot — 2026-07-14 10:37 ET (AFTERNOON)

Autopilot-collected in-session slot (EVO-65). First-hand session-only metrics
captured against the **live OpenD gateway + SIMULATE US account** on the user's
Mac mini during the **US regular session**. One independent window = one slot;
`aggregate_simulate.py` picks it up by the `opend_session*` directory prefix.
Reproducible via the committed, fill-lag-safe collector:

```bash
python -m qlab.opend_session_probe --symbol AAPL --n-qty1 8 --n-qty100 2 \
    --out qlab/reports/opend_session_20260714_1037ET
```

## ⚠️ Scope — SIMULATE ≠ real market (read this first)

**These metrics characterise the OpenD adapter + the SIMULATE matching engine's
execution path — NOT real market impact or real slippage.** Near-zero (slightly
price-improving) slippage, whole-lot matching with no order splitting, and the
seconds-scale fill lag are **SIMULATE characteristics** and must not be read as
real execution cost. Real execution quality can only be established with **real
fills** (real-money / real-market matching), which is out of scope for this round
and is access-controlled. This is **not** proof that real execution cost is
acceptable, and it does **not** speak to Kevin's 50%/20% real-fills bar (EVO-8 /
controlled-live). No PnL / return claim is made; SIMULATE virtual money is not a
performance result.

## Method (fill-lag-safe)

- **Session gate**: only runs when OpenD `get_global_state` reports a regular
  session (`market_us` ∈ MORNING/AFTERNOON), read live — never inferred. This
  slot: `market_us = AFTERNOON`, `trd_logined`/`qot_logined` both true.
- **Hard SIMULATE lock**: broker built with `TrdEnv.SIMULATE`; no REAL path, no
  `unlock_trade`, no trading password touched.
- **Marketable orders**: cross-price LIMIT — buy at `ask + 5c`, sell at
  `bid − 5c`. 10 BUY (8× qty 1, 2× qty 100 to probe partials), qty small.
- **Poll to terminal**: each order polled every 2s up to a 90s window until
  `FILLED_ALL` / cancelled / failed; any unfilled remainder cancelled (no leak).
- **Fill-lag-safe close-out**: re-reads the **actual broker position** (208 sh)
  and flattens exactly that — never an assumed fill.
- **Pre-clean + reconcile**: leftover flattened first; run ends with
  `reconcile_positions` that must be `in_sync` and flat.

## Files

- `session_metrics.json` — full result incl. per-order `orders[]` with
  `status_trail`, `submit_ack_latency_ms`, `slip_mid_bps` / `slip_touch_bps`,
  `fill_latency_s`, plus `fill_rate`, `actual_slippage_bps`,
  `partial_fill_behavior`, `reconcile`.
- `broker_events.jsonl` — connect / global_state / preclean / order events /
  reconcile / complete.
- `orders.jsonl` — per-order records (redacted).
- `errors.jsonl` — errors channel (empty = none this run).

## Result of this window (`market_us = AFTERNOON`, AAPL, arrival bid/ask ≈ 315.85/315.91)

- **order latency (submit→ack)**: n=11, p50 ≈ 182 ms (min 149 / max 342 ms);
  connect latency ≈ 60 ms.
- **fill_rate**: n_buy 10, fully_filled 10, rejected 0 → `full_fill_rate = 1.0`.
- **actual_slippage_bps** (signed, + = worse; n=11 legs = 10 buys + 1 close):
  vs arrival mid p50 = 0.0 bps (mean −0.07); vs arrival touch p50 ≈ −0.95 bps.
  → SIMULATE fills at/inside touch (a SIMULATE trait, see scope note).
- **partial_fill_behavior**: not observed (qty-100 orders filled whole).
- **fill_latency_s** (ack→FILLED_ALL, SIMULATE engine): p50 ≈ 5.9s, p95 ≈ 36.8s,
  max ≈ 41.6s — seconds-scale matching lag, **not** a real-market fill speed.
- **disconnects**: 0. **position deviation**: `reconcile.in_sync` true, 0 diffs.
- **positions_flat_after**: true (account flat after the sweep).

(Metric values are a fresh per-window measurement and will vary run-to-run. The
methodology and scope are what's fixed; this is one independent SIMULATE
execution-path sample, pooled with the others by `aggregate_simulate.py`.)
