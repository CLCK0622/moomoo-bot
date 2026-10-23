# S1 — short-term oversold mean reversion (RSI-2) · EVO-130 Phase 2

**Verdict: `基线未达标` (baseline not met) at the cost-×2 decision line.**

Real full-depth universe (2006→2026, qfq): SPY/QQQ/IWM + 19 large-caps under
`data/daily_full/`. Pre-registration frozen at `c025d56`; primary = RSI(2)<10
long above SMA200, exit RSI(2)>60 or **5-bar** max-hold, equal-weight book
(`max_concurrent=10`); **×2 is the pass/fail line**. Full result: [`report.json`](report.json).

## The oversold effect is real gross, but does not survive costs

| hold | ×1 CAGR | ×1 MDD | ×1 win-rate | **×2 CAGR** | ×2 MDD |
|---|---|---|---|---|---|
| 1 | −2.15% | 38% | 0.47 | −6.13% | 72% |
| 3 | +1.51% | 16% | 0.56 | −1.76% | 37% |
| **5 (primary)** | +3.40% | 19% | 0.63 | **+0.37%** | 22% |
| 10 | +4.54% | 14% | 0.66 | +1.65% | 17% |

Per-trade win rates of 0.56-0.66 (holds 3-10) confirm the RSI-2 bounce edge
exists **gross**. But turnover is 19-53×/yr; at ×2 costs the primary (hold=5)
collapses to **0.37% CAGR** — three orders of magnitude below the 50% hurdle —
and the shortest hold goes outright negative. Cost-fragile, not effect-absent.
No cell survives the haircut at ×2.

## Honest caveats (do not flatter the result)

- **Sizing:** `max_concurrent=10` was fixed BEFORE any result was seen (the frozen
  registration said "max_concurrent fixed" without pinning the integer). Mean
  deployment ≈2-3/10 slots ⇒ the book runs ~75% cash, a real CAGR drag that was
  **not** retuned post-hoc (guardrail #1). Concentration is a lever for a future
  P2 pass under a *fresh* registration, not a change to this one.
- **Survivorship:** today's surviving large-caps/ETFs over 2006→ bias the long
  side upward; the negative verdict holds *despite* that bias, which strengthens it.

## Reproduce

```bash
python -m qlab.swing.run_swing --candidate s1 --data-dir data/daily_full \
    --out reports/swing_s1_meanrev
```

Offline logic pinned by `tests/test_swing.py`.
