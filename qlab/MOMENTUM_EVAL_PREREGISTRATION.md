# EVO-23 candidate-1+2 — ETF right-side momentum package: FROZEN pre-registration

**Frozen before any backtest result was read.** This document is committed to the
branch *before* the results commit; the git timestamp/hash ordering lets 户部 /
都察院 verify pre-registration preceded results (per 工部尚书 2026-07-10, hard gate
#1). No number below may change after freeze; any deviation stops and is reported
(never silently retuned).

Two sleeves, each a *separately pre-registered* candidate with ONE primary cell
and an explicitly declared family (mirrors EVO-130 S1/S5 being two registered
candidates). The reused judgment stack is byte-for-byte the EVO-149 / EVO-130
modules; the ONLY new modelling code is the momentum signal adapter
(`swing/momentum_signals.py`) and its verdict wiring (`swing/momentum_evaluate.py`).

---

## 0. Reuse manifest (hard gate #2 — no re-implementation)

| reused verbatim (zero edits) | role |
|--|--|
| `qlab/events/gates.py` | EVO-12 gates 1–3 + `three_gate_verdict` (CAGR≥50%, MDD≤20%) |
| `qlab/events/significance.py` | moving-block bootstrap OOS significance |
| `qlab/events/multiple_testing.py` | pre-registration + Bonferroni/BH/Deflated-Sharpe haircut |
| `qlab/events/metrics.py` | EVO-12 §2 metric block (`evo12_metrics`) |
| `qlab/swing/evaluate.py::evaluate_curve` | curve → gates + significance wiring |

New code (this candidate only): `swing/momentum_signals.py` (signal→daily-equity),
`swing/momentum_evaluate.py` (verdict), `swing/run_momentum.py` (CLI). **No
best-of-N; no metric re-implemented.**

## 1. Data provenance (hard gate #3 — pure OpenD daily ETF, quote-only, SIMULATE)

| layer | source | coverage | role |
|--|--|--|--|
| price/signal/execution | moomoo OpenD qfq daily bars (`K_DAY`, `autype=qfq`) | per-ETF inception → 2026-07-09 | ONLY data source |

- Signal, ranking, and execution all read the **same** OpenD daily ETF bars.
  Quote-only; `TrdEnv.SIMULATE` hard-locked; no live credential is ever touched.
  Touching a live credential stops and is reported.
- **No external data source.** The EVO-25 CBOE/yfinance precedent does NOT extend
  here; any external feed would be filed case-by-case to 吏部/首辅 before use.
- Fetch command (production host with a reachable OpenD gateway):
  `python -m qlab.events.datafetch.opend_daily` → `fetch_daily_parquet(<UNIVERSE>,
  start="2006-01-01", end="2026-07-10", data_dir="data/daily_full")`.

### 1a. Data availability at freeze (recorded honestly, drives the gap list)

Real OpenD daily bars **present in the repo**: `SPY, QQQ, IWM` (full depth
2006-06→2026-07). **MISSING** (never fetched into this workspace): `TLT, IEF, GLD,
DBC, UUP, SHY` and all 11 sectors `XLY XLI XLK XLF XLV XLP XLU XLE XLB XLRE XLC`.
⇒ The frozen universes below **cannot be fully evaluated on real data now.** Per
工部尚书 hard gate #3, the deliverable is the reproducible engine + a run on the
available real subset (labelled data-insufficient, NOT a verdict against the frozen
universe) + the explicit gap list. No達标 claim may rest on the reduced subset.

## 2. Sleeve A — candidate 1: multi-asset ETF time-series (absolute) momentum

- **Universe (8, frozen):** `SPY QQQ IWM TLT IEF GLD DBC UUP`. Cash proxy: `SHY`
  (else flat cash = 0% return).
- **Signal (no-fit, hard gate #2 clause #4):** `mom(T) = close(T)/close(T−L) − 1`,
  L = lookback in trading days. Per-asset **absolute-momentum in/out** (Faber 2007
  GTAA; Moskowitz–Ooi–Pedersen 2012 TSMOM; Antonacci 2014 dual-momentum absolute
  filter): asset held **iff `mom(T) > 0`**, else that asset → cash. **Long-only, no
  shorting, no leverage.**
- **Sizing (frozen, no knob):** each asset gets a **fixed 1/N_universe = 1/8 =
  12.5%** slot; a slot is invested only while its own `mom>0`, else cash. Gross
  exposure = (#positive)/8 ∈ [0,1]. This is the canonical GTAA/diversified-TSMOM
  allocation — no concentration parameter to tune.
- **Primary lookback = 12 months (L=252d).** Family (haircut, robustness only):
  **L ∈ {6mo=126d, 12mo=252d}**, **primary = 12mo** (pre-fixed; NOT a best-of-N).
- **Rebalance = monthly** (last trading day of month, close→next open). Weekly is a
  reported sensitivity only, never a verdict cell.

## 3. Sleeve B — candidate 2: sector ETF relative-strength rotation

- **Universe (11 SPDR sectors, frozen):** `XLY XLI XLK XLF XLV XLP XLU XLE XLB XLRE
  XLC`. Cash proxy: `SHY`.
- **Signal:** rank the sectors by trailing K-month return `mom(T)=close(T)/close(T−K)−1`
  (relative strength; Jegadeesh–Titman 1993 formation; Faber–Richardson 2011 sector
  RS). Hold the **top-N**, equal-weight. **Dual-momentum absolute overlay:** a
  selected sector is taken only if its own `mom(T) > 0`, else that slot → cash
  (downtrend ⇒ cash). Long-only, no shorting.
- **Sizing (frozen):** top-N equal-weight = **1/N each**; N held → gross = (#of
  top-N that also pass abs filter)/N.
- **Primary = (K=12 months, N=top-3).** Family (haircut): **K ∈ {3mo=63d, 6mo=126d,
  12mo=252d}** at **N=3 fixed**, **primary = K=12** (pre-fixed). Holdings N∈{2,4}
  are reported as sensitivity only, NOT verdict cells.
- **Rebalance = monthly.**

## 4. Execution & anti-look-ahead (hard gate #2)

- Signal uses information as of **close(T)** at a rebalance date; the book may only
  trade from **open(T+1)**. Returns are **open-to-open**: weights decided at
  `close(T)` earn `open(p+1)/open(p) − 1` each subsequent period and pay cost on the
  rebalanced notional at the first `open(T+1)`. Nothing prices against a bar the
  signal could not have traded. **Unit-tested** (perturbing a future bar leaves all
  earlier realized returns unchanged; a future-only price shock cannot move history).

## 5. Risk overlay — FROZEN (pre-registered conventions, NOT tuned on P&L)

| parameter | value | rationale (a-priori) |
|--|--|--|
| vol target | **DISABLED** | the absolute-momentum cash switch IS the risk control (canonical trend-following); a tuned vol-target constant would void the no-fit declaration |
| circuit-breaker / cooldown | **DISABLED** | same — cash-on-downtrend already de-risks |
| abnormal-price stop | **DISABLED** | not a vol product; no analog needed |
| per-asset cap | 1/N slot (§2/§3) | equal-weight, no leverage, gross ≤ 100% |
| base cost | **10 bps/side** (EVO-12 CostModel); ×1 **and** ×2 | decision line = ×2 |

Disabling the vol overlay is a **frozen choice**, not an omission. It is a lever
reserved for a FUTURE fresh registration, never retuned into this one.

## 6. Judgment口径 (single main口径; decided at cost ×2) — reused verbatim

- **Gate 1** full-sample: CAGR ≥ **50%** AND MDD ≤ **20%**.
- **Gate 2** yearly: no negative full year, each full year CAGR ≥ 35%, combined ≥ 50%.
- **Gate 3** rolling 12-mo: median CAGR ≥ 50%, ≥70% windows ≥ 50%, ≤10% negative,
  **every window MDD ≤ 20%**.
- **MDD main口径 (written hard):** MDD > 20% on the full sample (gate 1) OR in any
  rolling window (gate 3) OR in any tail window (§7) ⇒ **direct negative**, never
  averaged away, never hidden behind a pretty average-return curve.
- **Significance:** moving-block bootstrap, `n_boot=2000`, `seed=12345`, `alpha=0.05`,
  hurdle=0.50; PASS needs `significant_beats_hurdle`.
- **Multiple testing:** Bonferroni + BH + Deflated Sharpe over the sleeve's lookback
  family; the primary must survive Bonferroni. `any_full_pass` (best-of-grid) is NOT
  used.
- **No-fit / walk-forward (hard gate #2 clause #4):** every primary parameter above
  is a **literature convention frozen before results** (sources cited in §2/§3), so
  the signal is no-fit ⇒ the full-sample curve **is** the OOS curve and gate 3 is the
  stability proxy; no fold walk-forward is owed. **If any parameter were ever chosen
  by looking at the sample, this waiver is void and a real fold walk-forward becomes
  mandatory** — that is not the case here.

## 7. Tail stress (part of the verdict, NOT an appendix)

Windows: **2018-02** (Volmageddon), **2020-03** (COVID), **2022** (rate-hike
bear), **2025-2026** (recent). Each window's MDD ≤ 20% is required; any breach ⇒
direct negative.

## 8. PASS definition (per sleeve, all must hold, at ×2, on the sleeve's primary cell)

1. Gate 1 ∧ Gate 2 ∧ Gate 3 pass; **and**
2. OOS significantly beats the 50% hurdle; **and**
3. Survives the multiple-testing haircut; **and**
4. **No** tail window (§7) breaches MDD ≤ 20%.

The candidate-1+2 package PASSES iff **at least one** sleeve's primary fully passes.
Both failing ⇒ negative, labelled by the specific failing numbers (`基线未达标` for a
CAGR/MDD gate-1 miss; `尾部未过线` for a tail-MDD breach). Negative is delivered
as-is; the risk-frontier reference (§9) and benchmarks (§10) are context, never a
verdict basis. A run on a reduced (data-insufficient) universe can NEVER be reported
as达标.

## 9. A-priori risk-frontier reference (NOT a verdict cell, NOT in the family)

One fixed reference per sleeve, declared in advance: the **equal-weight
buy-and-hold** of the sleeve's universe with **no momentum/cash switch** — to expose
the CAGR↔MDD frontier the trend filter is built to avoid. It can never turn a fail
into a pass.

## 10. Benchmarks (EVO-12 §4, reported for context)

SPY buy-and-hold, equal-weight-universe long-only buy-and-hold, cash/SHY, and 60/40
(SPY 60 / IEF-TLT 40). Any benchmark whose data is missing is marked `N/A (data gap)`.

## 11. Reproduction

```
# 1) (production host w/ OpenD) fetch the full frozen universe, quote-only SIMULATE:
python -c "from qlab.events.datafetch.opend_daily import fetch_daily_parquet as f; \
  f(['SPY','QQQ','IWM','TLT','IEF','GLD','DBC','UUP','SHY', \
     'XLY','XLI','XLK','XLF','XLV','XLP','XLU','XLE','XLB','XLRE','XLC'], \
    start='2006-01-01', end='2026-07-10', data_dir='data/daily_full')"
# 2) verdict + report.json (uses whatever real bars are present; labels gaps):
python -m qlab.swing.run_momentum --sleeve tsmom     --prereg-commit <HASH>
python -m qlab.swing.run_momentum --sleeve sector_rs --prereg-commit <HASH>
```
