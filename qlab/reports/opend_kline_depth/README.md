# OpenD `request_history_kline` depth / quota / rate probe — EVO-130 blocking item

**Verdict: `PASS_NO_GAP`.** The current OpenD subscription can retrieve daily
history back to **2006-06-26** (~20 years), which covers all three stress windows
the brief flagged (2018 / 2020 / 2022). No data gap blocks a stress-covering
walk-forward, so the swing evaluation is cleared to proceed on real data.

This is Step 1 of EVO-130 and Step 1 only: measure what is retrievable *before*
any backtest. Measured live against the running gateway on 2026-07-10
(`market_us = PRE_MARKET_BEGIN`). Full machine-readable result: [`report.json`](report.json).

## What was measured

| Dimension | Result |
|---|---|
| **Retrievable depth (daily, qfq)** | floor **2006-06-26** → 2026-07-09, ~5040 bars/symbol (~20 yr). Identical floor for AAPL and SPY ⇒ it is a subscription/provider floor, not a per-security IPO limit. |
| **Stress-window coverage** | 2018 volmageddon ✓, 2018 Q4 selloff ✓, 2020 COVID ✓, 2022 rate bear ✓ — all with real qfq bars. |
| **Historical-K quota** | **300 symbols / 30-day rolling window** (used 20, remaining 280 at probe time). Consumed only when a *new* code is pulled; re-pulling a counted code is free. |
| **Request rate** | ~3.6 req/s sustained over a 20-request burst, no throttle; SDK self-paces. The binding constraint is the 300-symbol quota, not this rate. |

## Constraints honored

- **Quote-only.** The probe opens *only* `OpenQuoteContext`. It never constructs
  a trade context, never unlocks trade, never places an order — so the
  `TrdEnv.SIMULATE` lock is satisfied vacuously (no trade env is ever selected).
  `report.json.trd_ctx_opened == false`.
- **Quota-frugal.** `get_history_kl_quota(get_detail=True)` is queried first and
  is non-consuming; depth is measured on already-counted codes (AAPL, SPY) so a
  re-run consumes **0** additional quota.
- **No fabrication.** Missing SDK/gateway raises `OpenDUnavailable`; API errors
  are recorded, never replaced with invented depth.

## Reproduce

```bash
# needs a reachable OpenD gateway + moomoo-api matching its version
python -m qlab.opend_kline_depth_probe --out qlab/reports/opend_kline_depth
```

Offline logic is pinned by `tests/test_kline_depth_probe.py` (fake quote context,
no gateway needed).

## Implication for the swing evaluation

- Full-depth daily bars (2006→) are available for the candidate universe. The S5
  essential (SPY) is persisted at full depth under `data/daily_full/`
  (`fetch_manifest_full.json`); `data/daily/` (EVO-24, 2019-2024) is left intact.
- Walk-forward can span ≥ 20 years / ~8 folds and include every flagged stress
  regime. Pre-registration + gate/haircut plan for S1 & S5 is in
  [`../../SWING_EVAL_PREREGISTRATION.md`](../../SWING_EVAL_PREREGISTRATION.md).
