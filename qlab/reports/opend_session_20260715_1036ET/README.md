# In-session OpenD SIMULATE evidence slot — 2026-07-15 10:36 ET (AFTERNOON)

Autopilot-collected in-session slot (EVO-65). First-hand session-only metrics
captured against the **live OpenD gateway + SIMULATE US account** on the user's
Mac mini during the **US regular session**. One independent window = one slot;
`aggregate_simulate.py` picks it up by the `opend_session*` directory prefix.
This is a **distinct trading day** (2026-07-15) from the two 2026-07-14 slots,
adding cross-day independence. Reproducible via the committed, fill-lag-safe
collector:

```bash
python -m qlab.opend_session_probe --symbol AAPL --n-qty1 8 --n-qty100 2 \
    --out reports/opend_session_20260715_1036ET
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
- **Fill-lag-safe close-out**: re-reads the **actual broker position** (108 sh)
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

## Result of this window (`market_us = AFTERNOON`, AAPL, arrival bid/ask ≈ 324.51/324.57)

- **order latency (submit→ack)**: n=11, p50 ≈ 1069 ms (min 606 / max 1864 ms);
  connect latency ≈ 57 ms.
- **fill_rate**: n_buy 10, fully_filled 9, rejected 0 → `full_fill_rate = 0.9`.
  One qty-100 BUY stayed `SUBMITTED` past the 90s poll window (dealt 0) and its
  remainder was **cancelled cleanly** (`cancelled_remainder = 100`, no leak) —
  this is a SIMULATE **fill-lag** outcome, **not** a broker reject and **not** a
  real-market fill-rate signal.
- **actual_slippage_bps** (signed, + = worse; n=10 filled legs): vs arrival mid
  p50 = −0.72 bps (mean −1.30); vs arrival touch p50 ≈ −1.54 bps.
  → SIMULATE fills at/inside touch (a SIMULATE trait, see scope note).
- **partial_fill_behavior**: not observed (filled qty-100 order filled whole).
- **fill_latency_s** (ack→FILLED_ALL, SIMULATE engine): p50 ≈ 7.0s, p95 ≈ 36.6s,
  max ≈ 48.9s — seconds-scale matching lag, **not** a real-market fill speed.
- **disconnects**: 0. **position deviation**: `reconcile.in_sync` true, 0 diffs.
- **positions_flat_after**: true (closeout 108/108; account flat after the sweep;
  live re-check confirmed AAPL qty 0 and no open orders).

(Metric values are a fresh per-window measurement and will vary run-to-run. The
methodology and scope are what's fixed; this is one independent SIMULATE
execution-path sample, pooled with the others by `aggregate_simulate.py`.)
