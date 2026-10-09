# In-session OpenD SIMULATE evidence — slippage / fill-rate / partial-fill

First-hand session-only metrics captured against the **live OpenD gateway +
SIMULATE US account** on the user's Mac mini during the **US regular session**.
Reproducible via the committed, fill-lag-safe collector:

```bash
python -m qlab.opend_session_probe --symbol AAPL --n-qty1 8 --n-qty100 2 \
    --out qlab/reports/opend_session_live
```

## ⚠️ Scope — SIMULATE ≠ real market (read this first)

**These three metrics characterise the OpenD adapter + the SIMULATE matching
engine's execution path — NOT real market impact or real slippage.** Near-zero
(slightly price-improving) slippage, whole-lot matching with no order splitting,
and the seconds-scale fill lag are **SIMULATE characteristics** and must not be
read as real execution cost. Real execution quality can only be established with
**real fills** (real-money / real-market matching), which is out of scope for
this round and is access-controlled. Do not read this as "real execution cost is
proven acceptable" — it is not measured here.

No PnL / return claim is made; SIMULATE virtual money is not a performance result.

## Method (fill-lag-safe)

- **Session gate**: only runs when OpenD `get_global_state` reports a regular
  session (`market_us` ∈ MORNING/AFTERNOON), read live — never inferred. Closed →
  exit without writing metrics (no fabrication).
- **Marketable orders**: cross-price LIMIT — buy at `ask + 5c`, sell at
  `bid − 5c`, `TrdEnv.SIMULATE`. 10 BUY (8× qty 1, 2× qty 100 to probe partials).
- **Poll to terminal**: each order polled every 2s up to a **90s** window until
  `FILLED_ALL` / cancelled / failed (full `status_trail` per order); any unfilled
  remainder is cancelled (no leak).
- **Fill-lag-safe close-out (the fix vs the earlier probe)**: after the buys, the
  close-out re-reads the **actual broker position** and flattens exactly that
  quantity — never an assumed fill. This removes the close-out race the previous
  uncommitted probe had (SIMULATE fills lag seconds, so an immediate assumed-fill
  close mis-sized the flatten).
- **Pre-clean + reconcile**: any leftover position is flattened first; the run
  ends with `reconcile_positions` that must be `in_sync` and flat.

## Files

- `session_metrics.json` — full result incl. per-order `orders[]` with
  `status_trail`, `submit_ack_latency_ms`, `slip_mid_bps` / `slip_touch_bps`,
  `fill_latency_s`, plus `fill_rate`, `actual_slippage_bps`,
  `partial_fill_behavior`, `reconcile`.
- `broker_events.jsonl` — connect / global_state / preclean / order events /
  reconcile / complete.
- `orders.jsonl` — per-order records (redacted).
- `errors.jsonl` — errors channel (empty = none this run).

## Result of the committed run (`market_us = AFTERNOON`, AAPL, bid/ask ≈ 315.01/315.03)

- **fill_rate**: n_buy 10, fully_filled 10, rejected 0 → `full_fill_rate = 1.0`.
- **actual_slippage_bps** (signed, + = worse; n=11 legs = 10 buys + 1 close):
  vs arrival mid p50 ≈ −0.16 bps (mean −0.13); vs arrival touch p50 ≈ −0.60 bps.
  → SIMULATE fills at/inside touch (a SIMULATE trait, see scope note).
- **partial_fill_behavior**: not observed (qty 100 filled whole even vs a smaller
  displayed ask size).
- **fill_latency_s** (ack→FILLED_ALL, SIMULATE engine): p50 ≈ 8.1s, p95 ≈ 18.2s,
  max ≈ 18.2s — seconds-scale matching lag, **not** a real-market fill speed.
- **positions_flat_after**: true; `reconcile.in_sync` true.

(Metric values are a fresh measurement and will vary run-to-run; e.g. an earlier
window saw `full_fill_rate 0.90` when one qty-100 order didn't match within 90s.
The methodology and scope are what's fixed.)
