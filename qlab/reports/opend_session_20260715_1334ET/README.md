# In-session OpenD SIMULATE evidence slot — 2026-07-15 13:34 ET (AFTERNOON)

Autopilot-collected in-session slot (EVO-65). First-hand session-only metrics
captured against the **live OpenD gateway + SIMULATE US account** on the user's
Mac mini during the **US regular session**. One independent window = one slot;
`aggregate_simulate.py` picks it up by the `opend_session*` directory prefix.
This is the **afternoon (13:34 ET) window of 2026-07-15**, a separate in-session
window from the 10:36 ET slot the same day; pooled with the 2026-07-10 and
2026-07-14 slots it brings the in-session sample count across **three distinct
trading days** (07-10 / 07-14 / 07-15) to the ≥5 target. Reproducible via the
committed, fill-lag-safe collector:

```bash
python -m qlab.opend_session_probe --symbol AAPL --n-qty1 8 --n-qty100 2 \
    --out reports/opend_session_20260715_1334ET
```

## ⚠️ Scope — SIMULATE ≠ real market (read this first)

**These metrics characterise the OpenD adapter + the SIMULATE matching engine's
execution path — NOT real market impact or real slippage.** Near-zero (roughly
touch-level) slippage, whole-lot matching with no order splitting, and the
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
- **Fill-lag-safe close-out**: re-reads the **actual broker position** (207 sh)
  and flattens exactly that — never an assumed fill.
- **Pre-clean + reconcile**: leftover flattened first; run ends with
  `reconcile_positions` that must be `in_sync` and flat.

## This window's result (SIMULATE execution-path characterisation only)

- `status = OK_SESSION_METRICS`; `positions_flat_after = true`;
  `reconcile.in_sync = true`, `n_diffs = 0` (account flat after sweep).
- Fill rate: 10 BUY, 9 fully filled within the 90s poll window, **0 rejects**
  (`full_fill_rate = 0.9`); the one non-full order's remainder was cancelled and
  the actual 207 sh position was flattened — no leak.
- Slippage vs arrival mid p50 ≈ +0.69 bps, vs arrival touch p50 ≈ +0.08 bps
  (near touch; a SIMULATE matching characteristic, **not** real market impact).
- SIMULATE fill lag p50 ≈ 5.9 s (matching-engine lag, not real fill speed).
- No partial fills observed (SIMULATE matches marketable orders whole-lot).

## Files

- `session_metrics.json` — full result incl. per-order `orders[]` with
  `status_trail`, `submit_ack_latency_ms`, `slip_mid_bps` / `slip_touch_bps`,
  `fill_latency_s`, plus `fill_rate`, `actual_slippage_bps`,
  `partial_fill_behavior`, `reconcile`.
- `broker_events.jsonl` / `orders.jsonl` — structured event + order log.
