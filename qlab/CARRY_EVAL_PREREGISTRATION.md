# EVO-25 candidate-8 — VIX term-structure / vol-ETP carry: FROZEN pre-registration

**Frozen before any backtest result was read.** This document is committed to the
branch *before* the results commit; git timestamp/hash ordering lets 户部 / 都察院
verify pre-registration preceded results. No number below may change after freeze;
any deviation stops and is reported (never silently retuned).

Path C authorized by 工部尚书 (2026-07-10). Signal = CBOE public cash indices;
execution = moomoo OpenD qfq daily ETP bars, quote-only, `TrdEnv.SIMULATE`.

---

## 1. Data provenance (guardrail #1)

| layer | source | file (committed) | coverage | role |
|--|--|--|--|--|
| signal | CBOE `VIX_History.csv` | `data/vix_raw/VIX_History.csv` | 1990-01-02 → 2026-07-09 | PRIMARY |
| signal | CBOE `VIX3M_History.csv` | `data/vix_raw/VIX3M_History.csv` | 2009-09-18 → 2026-07-09 | PRIMARY |
| signal | yfinance `^VIX`/`^VIX3M` | — (not stored) | — | CROSS-CHECK ONLY |
| execution | OpenD qfq daily bars | `data/vix_etp/<SYM>_1d.parquet` | per-ETP inception → 2026-07-09 | execution price |

- Download date: **2026-07-10**. URLs + row counts + coverage recorded in
  `data/carry_provenance.json`.
- **Two-source rule**: CBOE is primary; yfinance is cross-check only. Disagreement
  threshold = median |CBOE−Yahoo| close ≤ **0.75 vol points**. If exceeded, report
  honestly — no silent source-switching. (Observed: VIX median diff ≈0, corr
  0.99999; VIX3M median diff ≈0, corr 0.99999 — consistent.)
- VIX3M coverage (2009-09→) fully spans the SVXY era (inception 2011-10), so the
  signal never gap-fills the backtest window.

## 2. Signal (no-fit — guardrail #4)

- `term_ratio(T) = VIX_close(T) / VIX3M_close(T)`, CBOE cash closes.
- **Contango** ⇔ `term_ratio(T) < τ` ⇒ upward term structure ⇒ positive short-vol roll.
- **τ = 1.00** — the *natural structural boundary* (front 30-day vol = 3-month vol).
  This is a no-fit threshold; **the signal has ZERO parameters fitted on returns.**
- Family (multiple-testing haircut, robustness only): **τ ∈ {0.95, 1.00, 1.05}**,
  **primary = 1.00** (pre-fixed; the band is NOT a best-of-N scan).

## 3. Instrument & direction (hard constraint)

- **Long-only ETP / cash switch.** Contango ⇒ **long SVXY** (−0.5× short-term VIX
  futures). Backwardation ⇒ **cash**. Never shorts a vol product; no options.
- Primary tradable = **SVXY** (full depth 2011-10→). Segment robustness (reported,
  NOT stitched): **SVIX** 2022-03→. ETP history breakpoints honored (guardrail #3):
  SVXY leverage change 2018-02 (−1×→−0.5×) is a product-terms break — the SVXY
  series used here is the post-2011-inception qfq series; the −0.5× era is what the
  backtest trades, and no pre-2018 −1× regime is spliced in as the same asset.

## 4. Execution & anti-look-ahead (guardrail #2)

- VIX/VIX3M settle **16:15 ET**, *after* the ETP **16:00 ET** close ⇒ a signal on
  `close(T)` may not trade until `open(T+1)`.
- **Returns are open-to-open**: exposure decided at `close(T)` earns
  `open(T+2)/open(T+1) − 1`; transaction cost is charged on the rebalanced notional
  at `open(T+1)`. Nothing prices against a bar the signal could not have traded.

## 5. Risk overlay — FROZEN constants (pre-registered conventions, NOT tuned on P&L)

| parameter | value | rationale (a-priori, not fitted) |
|--|--|--|
| vol target (annualized) | **0.15** | standard institutional sleeve risk budget |
| realized-vol lookback | **20** trading days | 1 trading month |
| exposure cap | **0.50** of capital | SVXY is −0.5× ⇒ ≤0.25× effective vol beta |
| drawdown circuit-breaker | **0.15** strategy-equity DD | < the 0.20 MDD gate, trips before the cap |
| breaker cooldown | **10** trading days | 2 weeks flat; HWM resets on resume |
| abnormal-VIX hard stop | VIX close > **35** | ≈ historical 90th pct; flatten next period |
| base cost | **10 bps/side** (EVO-12 CostModel); ×1 **and** ×2 double-reported | decision line = ×2 |

- exposure(T) = `contango(T) · min(exposure_cap, target_vol / realized_vol_SVXY(T))`,
  overridden to 0 by the abnormal-VIX stop or an active breaker cooldown.
- "concurrency/position limit" analog for a single-asset sleeve = exposure_cap 0.50.
- Breaker semantics: on a DD breach, flatten and hold cash `cooldown` days, then
  resume with a fresh high-water mark (a design correctness rule, documented here;
  it gates the breaker only — the reported MDD is recomputed independently on the
  equity curve and is never reset).

## 6. Judgment口径 (single main口径; decided at cost ×2)

Reused **verbatim** (zero edits): EVO-149 `events/gates.py`,
`events/significance.py`, `events/multiple_testing.py`, `events/metrics.py`;
EVO-130 `swing/evaluate.py::evaluate_curve`. Only NEW code = the carry signal
adapter (`swing/carry_signals.py`, `swing/carry_evaluate.py`).

- **Gate 1** full-sample: CAGR ≥ **50%** AND MDD ≤ **20%**.
- **Gate 2** yearly: no negative full year, each full year CAGR ≥ 35%, combined ≥ 50%.
- **Gate 3** rolling 12-mo: median CAGR ≥ 50%, ≥70% windows ≥ 50%, ≤10% negative,
  **every window MDD ≤ 20%**.
- **MDD judgment口径 (首辅 clause #5, written hard):** MDD > 20% on the full sample
  (gate 1) OR in any rolling window (gate 3) OR in any tail window (§7) ⇒ **direct
  negative**, never averaged away.
- **Significance:** moving-block bootstrap, `n_boot=2000`, `seed=12345`, `alpha=0.05`,
  hurdle=0.50; PASS needs `significant_beats_hurdle`.
- **Multiple testing:** Bonferroni + BH + Deflated Sharpe over the 3-cell τ family;
  primary (τ=1.00) must survive Bonferroni. `any_full_pass` (best-of-grid) is NOT used.
- **No-fit / walk-forward (guardrail #4, clause #4):** the signal is no-fit, so the
  full-sample curve **is** the OOS curve and gate 3 is the stability proxy; no fold
  walk-forward is owed. (Were any signal parameter fitted on-sample, this waiver
  would be void and a real fold WF required — it is not the case here.)

## 7. Tail stress (part of the verdict, NOT an appendix — 首辅 clause #5)

Windows: **2018-02** (Volmageddon), **2020-03** (COVID), **2022** (rate-hike vol),
**2025-2026** (recent). Plus a **single-day extreme shock**: apply a **−80%** SVXY
open-to-open gap (2018-02-06 scale) at the max realized exposure ⇒ principal-loss
estimate. Any tail window with MDD > 20% ⇒ direct negative.

## 8. PASS definition (all must hold, at ×2, on the primary τ=1.00 SVXY cell)

1. Gate 1 ∧ Gate 2 ∧ Gate 3 pass; **and**
2. OOS significantly beats the 50% hurdle; **and**
3. Survives the multiple-testing haircut; **and**
4. **No** tail window (§7) breaches MDD ≤ 20%.

Otherwise → negative, labelled by the specific failing numbers (基线未达标 for a
CAGR/MDD gate-1 miss; 尾部未过线 for a tail-MDD breach). Negative is delivered
as-is; the risk-frontier reference (§9) is context, never a verdict basis.

## 9. A-priori risk-frontier reference (NOT a verdict cell, NOT in the family)

One fixed reference config, declared here in advance: same signal, **full exposure
(1.0), no vol target / no breaker / no VIX stop**. Reported only to expose the
CAGR↔MDD incompatibility a risk-constrained sleeve is built to avoid. It can never
turn a fail into a pass.

## 10. Reproduction

```
python -m qlab.swing.fetch_carry_data --download-date 2026-07-10          # data + provenance + crosscheck
python -m qlab.swing.run_carry --instrument SVXY --prereg-commit <HASH>   # verdict + report.json
```
