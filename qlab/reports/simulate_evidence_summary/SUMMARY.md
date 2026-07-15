# SIMULATE evidence aggregate — EVO-65 (NOT real execution cost)

**TrdEnv:** SIMULATE (hard-locked). SIMULATE matching-engine execution path, NOT real market cost.

**Slots:** 6 total (1 order-path, 5 in-session, gap 0). In-session ET trading days: 2026-07-09, 2026-07-14, 2026-07-15 (3 distinct — EVO-149 independence).

Qualification gate (only counted slots): TrdEnv.SIMULATE + >0 orders; in-session also requires market_us∈{MORNING,AFTERNOON} + OK_SESSION_METRICS. Rejected slots this run: 0; dropped 0-order: [].

## Six metric classes (pooled across qualified slots)
1. **Order latency (submit→ack)**: p50 560.3 / p95 1159.9 / max 1863.6 ms (n=85)
2. **Slippage**: vs mid p50 -0.1587477973759718 bps, vs touch p50 -0.6347594261787055 bps (n=53, +bps=worse)
3. **Fill rate**: full_fill_rate 0.96 (48/50)
4. **Reject rate (all submitted)**: 0.0 (0/85) — primary buy/order-path 0/80, closeout 0/5
5. **Disconnects**: 0
6. **Position deviation**: all in-sync=True, worst diffs=0
   - aux: partial fills observed=False; **pooled** SIMULATE fill lag p50 8.063596s / p95 25.740094s (n=53, ack→FILLED_ALL, NOT real-market fill speed)

## Landability judgment (verdict — NOT upgraded)
- real_execution_cost_established: **False**
- landable vs Kevin bar (annual return >= 50% AND max drawdown <= 20% (on real fills)): **UNDECIDABLE_FROM_SIMULATE**
- decision_readiness: **SIMULATE_EXECUTION_CHARACTERIZED**
- engineering/risk gate: **CLOSED@7d94a2c** (unchanged); real landability owner: **parent EVO-8 / controlled-live**
- The 50%/20% bar is a return/drawdown target on a real-fills strategy PnL; SIMULATE execution-path health cannot satisfy it. Candidate stays needs-evidence / NOT PASS.

## Limitations
- ET trading dates are derived from each slot's first order ack_ts via America/New_York. The live slot's real trading day is 2026-07-09 (14:01 ET) — correcting an earlier '07-10' narrative. Distinct session trading days remain {2026-07-09, 2026-07-14, 2026-07-15} = 3, so EVO-149 multi-sample independence is unchanged.
- Any 0-order local staging dirs (e.g. opend_session_smoke / opend_session_val) are NOT committed to the tree; re-running aggregation on the committed tree yields dropped_zero_order_slots=[]. They cannot be independently re-verified and do NOT affect the committed evidence slots' count or integrity.

**Live market context this run:** {'available': True, 'market_us': 'AFTERNOON', 'trd_logined': True, 'qot_logined': True}
