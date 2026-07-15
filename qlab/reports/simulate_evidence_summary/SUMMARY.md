# SIMULATE evidence aggregate — EVO-65 (NOT real execution cost)

**TrdEnv:** SIMULATE (hard-locked). SIMULATE matching-engine execution path, NOT real market cost.

**Slots:** 5 total (1 order-path, 4 in-session). Decision needs ≥ 5 in-session → gap 1.

## Six metric classes (pooled across slots)
1. **Order latency (submit→ack)**: p50 562 / p95 1239 / max 1864 ms (n=74)
2. **Slippage**: vs mid p50 -0.1588158688832797 bps, vs touch p50 -0.7940289026531396 bps (n=43, +bps=worse)
3. **Fill rate**: full_fill_rate 0.975 (39/40)
4. **Reject rate**: 0.0 (0/70)
5. **Disconnects**: 0
6. **Position deviation**: all in-sync=True, worst diffs=0
   - aux: partial fills observed=False; SIMULATE fill lag p50=5.8842549324035645s

## Landability judgment
- real_execution_cost_established: **False**
- landable vs Kevin bar (annual return >= 50% AND max drawdown <= 20% (on real fills)): **UNDECIDABLE_FROM_SIMULATE**
- decision_readiness: **INTERMEDIATE**
- The 50%/20% bar is a return/drawdown target on a real-fills strategy PnL; SIMULATE execution-path health cannot satisfy it. Candidate stays needs-evidence / NOT PASS.

### Gaps to a decision
- need >= 5 in-session slots for a stable SIMULATE execution read; have 4 (gap 1) — autopilot supplies these.
- real execution cost (real market impact / slippage) requires REAL fills (real-money or real-market matching) — out of scope, controlled.

**Live market context this run:** {'available': True, 'market_us': 'AFTERNOON', 'trd_logined': True, 'qot_logined': True}
