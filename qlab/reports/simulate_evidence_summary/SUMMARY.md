# SIMULATE evidence aggregate — EVO-65 (NOT real execution cost)

**TrdEnv:** SIMULATE (hard-locked). SIMULATE matching-engine execution path, NOT real market cost.

**Slots:** 2 total (1 order-path, 1 in-session). Decision needs ≥ 5 in-session → gap 4.

## Six metric classes (pooled across slots)
1. **Order latency (submit→ack)**: p50 566 / p95 677 / max 743 ms (n=41)
2. **Slippage**: vs mid p50 -0.1587477973759718 bps, vs touch p50 -0.6032895154634361 bps (n=11, +bps=worse)
3. **Fill rate**: full_fill_rate 1.0 (10/10)
4. **Reject rate**: 0.0 (0/40)
5. **Disconnects**: 0
6. **Position deviation**: all in-sync=True, worst diffs=0
   - aux: partial fills observed=False; SIMULATE fill lag p50=8.094367980957031s

## Landability judgment
- real_execution_cost_established: **False**
- landable vs Kevin bar (annual return >= 50% AND max drawdown <= 20% (on real fills)): **UNDECIDABLE_FROM_SIMULATE**
- decision_readiness: **INTERMEDIATE**
- The 50%/20% bar is a return/drawdown target on a real-fills strategy PnL; SIMULATE execution-path health cannot satisfy it. Candidate stays needs-evidence / NOT PASS.

### Gaps to a decision
- need >= 5 in-session slots for a stable SIMULATE execution read; have 1 (gap 4) — autopilot supplies these.
- real execution cost (real market impact / slippage) requires REAL fills (real-money or real-market matching) — out of scope, controlled.

**Live market context this run:** {'available': True, 'market_us': 'AFTER_HOURS_END', 'trd_logined': True, 'qot_logined': True}
