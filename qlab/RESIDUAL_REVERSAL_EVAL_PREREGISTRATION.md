# EVO-162 C1 — Cross-sectional residual reversal (large-cap, weekly, market-neutral stat-arb): FROZEN pre-registration

**Frozen before any backtest result was read.** This document is committed to the
branch *before* the results commit; the git timestamp/hash ordering lets 户部 /
都察院 verify the pre-registration preceded results (首辅 2026-07-10 hard constraints).
**No number below may change after freeze.** Any deviation stops and is reported —
never silently retuned (candidate-8 death mode). Reused judgment stack is
byte-for-byte the EVO-149 / EVO-130 / EVO-23 modules; the ONLY new modelling code is
the residual-reversal signal adapter (§0).

C1 is a **single pre-registered candidate** with ONE primary cell and an explicitly
declared family for the multiple-testing haircut (mirrors EVO-23 sleeves, EVO-130
S1/S5). Author: 户部 (data/statistics lead). Engineering of the adapter: 工部, which
follows THIS frozen spec and does not tune parameters in parallel. Short-leg risk
red-lines (§6) go to 锦衣卫 for EVO-10 review **before the short leg runs — 不过不跑**.

---

## 0. Reuse manifest (首辅 hard: 复用不重造, 禁 best-of-N)

| reused verbatim (zero edits) | role |
|--|--|
| `qlab/events/gates.py` | EVO-12 gates 1–3 + `three_gate_verdict` (CAGR≥50%, MDD≤20%) |
| `qlab/events/significance.py` | moving-block bootstrap OOS significance |
| `qlab/events/multiple_testing.py` | pre-registration + Bonferroni/BH/Deflated-Sharpe haircut |
| `qlab/events/metrics.py` | EVO-12 §2 metric block (`evo12_metrics`, `_cagr`, `_max_drawdown`) |
| `qlab/swing/evaluate.py::evaluate_curve` | curve → gates + significance wiring |
| `qlab/swing/momentum_signals.py` | reference pattern for the long-short weight→open-to-open curve (extended, not edited) |
| `qlab/events/datafetch/opend_daily.py::fetch_daily_parquet` | OpenD qfq daily fetch (quote-only) |

**New code (this candidate only), to be written by 工部 following this spec:**
`swing/residual_signals.py` (factor-residual signal + dollar/beta-neutral long-short
weight matrix → daily cost-after equity curve, same `equity_df` columns as
`momentum_curve`), `swing/residual_evaluate.py` (verdict builder mirroring
`momentum_evaluate.build_momentum_report`), `swing/run_residual.py` (CLI). **No
metric re-implemented. No best-of-N.** The equity curve MUST carry the EVO-12 columns
`date, ret, equity, traded_notional` verbatim so it flows straight into
`evaluate_curve` → gates/significance/haircut with zero adaptation.

## 1. Data provenance (首辅 hard: 纯 OpenD 日/周线, quote-only, SIMULATE, 零外部源)

| layer | source | coverage | role |
|--|--|--|--|
| price / signal / execution | moomoo OpenD qfq daily bars (`K_DAY`, `autype=qfq`) | per-symbol inception → 2026-07-09 | ONLY data source |
| factor returns | derived from OpenD ETF bars (§3) — SPY, IWM, IVE, IVW | same | built in-sample, no external factor file |

- Signal, factor construction, ranking, and execution all read the **same** OpenD
  daily bars. **Quote-only; `TrdEnv.SIMULATE` hard-locked; no live credential is ever
  touched.** Touching a live credential stops and is reported.
- **No external data source.** Fama-French/CRSP/Compustat factor files, borrow-rate
  feeds, and point-in-time index membership are **out of scope this round** (not
  purchased, not started). All factors are ETF-return proxies built from OpenD bars.
- Weekly returns are resampled from OpenD daily bars (last trading day of each ISO
  week), so no separate weekly feed is needed. Depth (EVO-159 probe, verified
  `reports/opend_kline_depth/report.json`): daily floor **2006-06-26** → 2026-07-09
  (~5040 bars/symbol, ~20yr); covers 2008 / 2018Q4 / 2020-03 / 2022 / 2025-26.
- Fetch (production host with a reachable OpenD gateway), quote-only SIMULATE:
  `fetch_daily_parquet(<RESIDUAL_UNIVERSE ∪ FACTOR_ETFS>, start="2006-01-01",
  end="2026-07-10", data_dir="data/daily_full")`.

### 1a. Data availability at freeze (recorded honestly — drives the gap list)

Real OpenD daily bars **present in this workspace** (`data/daily_full/`, 22 symbols):
`SPY QQQ IWM` + 19 large-caps `AAPL AMZN BAC CSCO CVX GOOGL GS HD INTC JNJ JPM KO META
MSFT NVDA ORCL PFE PG WMT`. **MISSING:** the remaining ≥248 stocks of the frozen
universe and the value/growth factor ETFs `IVE IVW`.

⇒ The frozen universe **cannot be fully evaluated on real data in this workspace now.**
A cross-sectional residual regression needs breadth (N ≫ K); 19 names cannot form
honest deciles. Per 首辅 hard gate, the deliverable is the **reproducible engine + a
run on whatever real subset is present (labelled `数据不足`, NOT a verdict against the
frozen universe) + the explicit gap list.** No 达标 claim may rest on the reduced
subset. The full fetch (≤300 symbols, within the OpenD 300/30-day quota) runs on a
host with OpenD reachable; the resolved universe list is committed to THIS branch
**before any results commit** (§2).

## 2. Universe — FROZEN (首辅 hard constraint #1: ≤300, 看结果前冻结, 不得中途换票)

- **Tradable / cross-section universe: `N_STOCKS = 250` US large-caps.** Selection
  rule (deterministic, OpenD-only, reproducible; resolved list committed **before**
  results as `RESIDUAL_UNIVERSE_RESOLVED.txt`):
  1. candidate pool = US common stocks with a moomoo US quote and **≥ 3yr (156wk)**
     OpenD daily history as of the freeze date 2026-07-10;
  2. rank by **60-trading-day average dollar volume** (from OpenD daily bars,
     `close × volume`); take the **top 250**;
  3. exclude names with no share-borrow availability on moomoo (short leg must be
     borrowable — §6); a dropped name is replaced by the next-ranked, and the
     substitution is logged in the resolved-list commit (this is the ONLY admissible
     substitution and it happens **before** results — never mid-backtest).
- **Factor-regressor ETFs (frozen, 4):** `SPY` (market), `IWM` (small-cap size proxy),
  `IVE` (S&P 500 Value), `IVW` (S&P 500 Growth). Total symbols fetched = 250 + 4 =
  **254 ≤ 300** (OpenD historical-K quota, EVO-159). These ETFs are regressors only,
  never traded.
- **Hard constraint:** total fetched symbols ≤ 300 is a pre-registration invariant.
  The resolved 250-name list is frozen at commit time; **no mid-evaluation swap.**
- **Survivorship caveat (disclosed, not hidden):** "large & liquid as of 2026" over a
  2006→ window is survivorship-biased (delisted names excluded; 2006 vs 2026 large-cap
  sets differ). A weekly **dollar-neutral long-short** on *residuals* is far less
  survivorship-sensitive than a long-only level bet (it trades week-to-week residual
  mean-reversion *within* the surviving cross-section, not which names survive), but
  the bias is upward on any residual autocorrelation that co-moves with survival. A
  point-in-time universe (external, out of scope) would be needed for a clean verdict;
  the limitation is reported with the result and **cannot** turn a fail into a pass.

## 3. Residual factor-neutralization model — FROZEN (户部 core modelling)

Faithful to the cited literature (Blitz/Huij/Lansdorp/Verbeek, *Short-Term Residual
Reversal*, SSRN 1911449; de Groot/Huij/Zhou, SSRN 1605049; residual-momentum
construction of Blitz/Huij/Martens 2011). All constants are **literature conventions
frozen before results** (no-fit — see §11).

**Frequency.** Everything is weekly. Week = ISO week; the week-`t` bar is the **last
OpenD trading day of ISO week `t`** (`_rebalance_mask(..., "weekly")` in the harness).
Weekly simple return `r_{i,t} = close_i(last day wk t) / close_i(last day wk t−1) − 1`.

**Factor returns (weekly, OpenD-only), 3-factor:**
- `MKT_t` = SPY weekly return.
- `SMB_t` = IWM weekly return − SPY weekly return (small-minus-large size proxy).
- `HML_t` = IVE weekly return − IVW weekly return (value-minus-growth proxy).

**Per-stock beta estimation (rolling, genuinely out-of-sample by construction):**
For each stock `i` at each weekly rebalance date `t`, estimate `(α̂_i, β̂^MKT_i,
β̂^SMB_i, β̂^HML_i)` by **OLS time-series regression** of `r_{i,·}` on
`{1, MKT, SMB, HML}` over the trailing **`E = 156` weeks** (3 years) ending at week
`t−1` (strictly past data only). Require **≥ 104** valid weekly observations (2yr) in
the window; a stock with fewer is **excluded that week** (a data gap, recorded — never
silently imputed). Betas are re-estimated every rebalance (rolling window).

**Residual return (the neutralized quantity):**
`ε_{i,τ} = r_{i,τ} − (α̂_i + β̂^MKT_i·MKT_τ + β̂^SMB_i·SMB_τ + β̂^HML_i·HML_τ)`
for weeks `τ` in the formation window. The residual strips market/size/value exposure,
leaving the stock-specific move that the literature shows reverses short-term.

**Reversal signal (primary):** formation window **`F = 1` week** — the signal is the
**most recent single-week residual**:
`signal_{i,t} = − ε_{i,t}` (negative residual → high signal → a *residual loser* to
buy; positive residual → low signal → a *residual winner* to short). This is the
short-term residual-reversal effect (negative autocorrelation of the residual).

**Cross-sectional standardization (frozen):** each rebalance, cross-sectionally
winsorize `signal_{i,t}` at the 1st/99th percentile (tames single-name outliers /
data errors), then rank. No z-scoring beyond winsorize+rank; the portfolio uses ranks,
not raw magnitudes, so the signal is scale-free.

## 4. Signal → portfolio construction — FROZEN

- **Deciles (primary):** each rebalance, sort the eligible cross-section by
  `signal_{i,t}` descending. **Long the top decile** (largest positive signal = biggest
  residual losers), **short the bottom decile** (biggest residual winners). With ~250
  eligible names → **~25 names per leg** (diversified — §6).
- **Weighting:** **equal-weight within each leg.** **Dollar-neutral:** long notional =
  short notional. **Beta-neutral:** because legs are balanced deciles of a
  beta-neutralized residual, net `β^MKT` is ≈0 by construction; additionally, if the
  realized net portfolio `|β^MKT| > 0.05`, scale the two legs' notionals to force net
  `β^MKT` into `[−0.05, +0.05]` (a mechanical neutralization, not a tuned knob).
- **Rebalance = weekly** (last trading day of ISO week signal → next session open
  execution). Hold to the next weekly rebalance. This is the "周频、低换手" construction
  (5× lower turnover than the classic *daily* reversal that dies on costs — the exact
  distinction EVO-158 draws from EVO-129 S1).
- **N is the FROZEN universe size** for sizing: an un-fetched or excluded symbol is a
  permanently-absent cross-section slot (a data gap), never a silent re-size of the
  frozen weights (mirrors `momentum_signals` `N_universe` discipline).

## 5. Leverage口径 — FROZEN (首辅 hard constraint #3: 数值钉死, 单一主口径, 禁看结果后加杠杆)

| parameter | frozen value | rationale (a-priori, cited/standard) |
|--|--|--|
| base gross leverage | **2.0×** (1.0× long + 1.0× short of NAV) | the residual-reversal edge (~30–50 bps/wk net, large-cap) needs ~2× gross to approach the 50% CAGR line; 2× is the structural premise, pinned as a hard **cap**, not a post-hoc dial |
| gross leverage cap | **2.0× (hard)** | never exceeded on any date; forbids candidate-8-style post-hoc leverage inflation |
| ex-ante vol target | **10% annualized** on the long-short book | standard institutional stat-arb target; gross scaled to hit 10% ann. vol using trailing **26-week** realized daily-P&L vol, then **capped at 2.0×, floored at 0.5×**. 10% / 26wk / caps frozen a-priori (round conventions, NOT fitted) |
| stress circuit-breaker | if trailing **5-trading-day book drawdown ≥ 8%**, gross → **0.5×** for the next full rebalance week | a-priori quant-quake de-risk (2007-08 style); 8% / 5d / 0.5× pinned before results |
| margin assumption | Reg-T retail: long funded by NAV (no margin interest on the first 1.0×); financed excess `(gross−1)×NAV` at moomoo retail margin **6.8%/yr**; short pays borrow (§8); **no short-rebate credit assumed** (conservative retail) | moomoo US retail schedule |

The vol-target + breaker together **are** the pre-registered "压力段去杠杆规则" required
by hard constraint #3. They are a single口径, fixed now. Any change after seeing results
voids the run. Disabling them or lifting the 2.0× cap is a lever reserved for a FUTURE
fresh registration, never retuned into this one.

## 6. Short-leg risk red-lines — FROZEN (首辅 hard constraint #2 · EVO-10 · 锦衣卫 复核, 不过不跑)

The short leg is a **diversified, dollar- and beta-neutral, hedged** short — explicitly
**NOT** an unhedged leveraged short or a naked-option structure (EVO-10 无限风险排除).
Maximum loss is bounded and quantified. Pinned controls:

| control | frozen value |
|--|--|
| diversification | **≥ 20 names per leg** (decile of ~250 gives ~25; if the *real-data* eligible set is smaller, the leg still needs ≥ 20 or the run is labelled `数据不足`, never a thin-book verdict) |
| single-name hard cap | **≤ 5% of gross** per name (≈1.25× the equal-weight slot at 25 names); caps a single short squeeze's portfolio impact |
| single-sector net cap | **|long − short| ≤ 10% of gross** per GICS sector (residual model already reduces sector tilt; enforced as a hard cap) |
| per-name short stop | close a single short if it moves **≥ +25% adverse** intra-position (a-priori single-name blow-up guard) |
| borrowability | short universe = only moomoo-borrowable large-caps (§2 rule 3); no hard-to-borrow / no naked short |
| defined-risk alternative | option-collar / put-replacement of the short leg is **reserved** (adds cost, not in the primary); noted for 锦衣卫 as the fallback if borrow/short constraints fail review |
| book-level | dollar-neutral + beta-neutral + 2.0× gross cap + 10% vol target + 8%/5d breaker (§5) bound the tail |

**开跑前交锦衣卫复核 EVO-10 红线；复核不过，做空腿不跑（长腿-only 或 defined-risk 版本回退）。**

## 7. Execution & anti-look-ahead — FROZEN (T 收盘信号 → T+1 执行, 单测)

Signal uses information as of the **weekly rebalance close(T)**; the book may only
trade from **open(T+1)** (next session open). Position returns are **open-to-open**:
weights decided at `close(T)` earn `open(p+1)/open(p) − 1` each subsequent day and pay
cost on the rebalanced notional at the first `open(T+1)` (identical convention to
`momentum_curve`). Nothing prices against a bar the signal could not have traded.
**Unit test (required, 工部):** perturbing any future bar leaves every earlier realized
return unchanged; a future-only price shock cannot move history.

## 8. Cost model — FROZEN (首辅 hard constraint #4: moomoo 真实零售口径 ×1/×2 双报)

Reversal historically dies on costs (swing S1 前车). Cost stress is a **main judgment**,
not an appendix. Decision line = **×2**.

| cost component | frozen value | applied to |
|--|--|--|
| commission + spread (round-trip half = per side) | **10 bps/side base** (EVO-12 `CostModel`), reported **×1 and ×2** | traded notional each rebalance (turnover × side) |
| short borrow fee | **0.5%/yr** (large-cap general-collateral, moomoo retail) | short notional, accrued daily |
| financing on levered excess | **6.8%/yr** (moomoo retail margin) | `(gross−1)×NAV`, accrued daily |
| short rebate | **0%** (conservative retail; no rebate credited) | — |
| PDT / settlement | weekly rebalance ⇒ not pattern-day-trading; noted, no extra charge | — |

The ×1/×2 multiplier applies to **commission+spread**; borrow and financing are
rate-based drags at the pinned rates (also reported at their pinned level in both
variants). Institutional cost assumptions do **not** count. Turnover, borrow, and
financing are reported per run so the cost drag is auditable.

## 9. Judgment口径 (single main口径; decided at cost ×2) — reused verbatim

- **Gate 1** full-sample: CAGR ≥ **50%** AND MDD ≤ **20%**.
- **Gate 2** yearly: no negative full year, each full year CAGR ≥ 35%, combined ≥ 50%.
- **Gate 3** rolling 12-mo: median CAGR ≥ 50%, ≥70% windows ≥ 50%, ≤10% negative,
  **every window MDD ≤ 20%**.
- **MDD main口径 (written hard):** MDD > 20% on the full sample (gate 1) OR in any
  rolling window (gate 3) OR in any tail window (§10) ⇒ **direct negative**, never
  averaged away, never hidden behind a pretty average-return curve.
- **Significance:** moving-block bootstrap, `n_boot=2000`, `seed=12345`, `alpha=0.05`,
  hurdle=0.50; PASS needs `significant_beats_hurdle`.
- **Multiple testing:** Bonferroni + BH + Deflated Sharpe over the declared family
  (§12); the primary must survive Bonferroni. `any_full_pass` (best-of-grid) is NOT used.

## 10. Tail stress (part of the verdict, NOT an appendix) — FROZEN

Windows (首辅 裁定纳入 2008): **2007-08 (quant quake)**, **2008 (GFC)**, **2018Q4**,
**2020-03 (COVID)**, **2022 (rate-hike bear)**, **2025-2026 (recent)**. Each window's
MDD ≤ 20% is required; any breach ⇒ **direct negative**. The 2007-08 quant-quake window
is the decisive stress for a levered market-neutral reversal book (Aug-2007 stat-arb
deleveraging) and is a first-class verdict cell here.

```
STRESS_WINDOWS = {
  "2007-08_quantquake": ("2007-07-01", "2007-09-30"),
  "2008_gfc":           ("2008-01-01", "2008-12-31"),
  "2018Q4_selloff":     ("2018-10-01", "2018-12-31"),
  "2020-03_covid":      ("2020-02-15", "2020-04-30"),
  "2022_ratehike_bear": ("2022-01-01", "2022-12-31"),
  "2025-2026_recent":   ("2025-01-01", "2026-07-09"),
}
```

## 11. No-fit / walk-forward discipline — FROZEN (首辅 clause #4)

Residual reversal has **no natural structural zero** (F / E / factor set / decile
count / rebalance frequency / neutralization口径 are all choices). Per clause #4, we
take the **no-fit route**: every primary parameter is a **literature convention frozen
before results with a cited source** (§3/§4), so no fold walk-forward is *owed*.
Additionally — and stronger than the momentum candidate — the residual model's betas
are estimated **only on trailing data** and applied to the next (disjoint) week, so
**every signal is genuinely out-of-sample by construction**; the full-sample curve *is*
an OOS curve and gate 3 rolling is the stability proxy.

**Waiver-void trigger (written hard):** if ANY primary parameter (F, E, factor set,
decile count, rebalance freq, vol target, breaker, caps) is ever chosen or nudged by
looking at the sample result, this no-fit waiver is **void** and a real fold
walk-forward becomes mandatory before any 达标 claim. That is not the case at freeze.

## 12. Family (haircut / robustness only; primary pre-fixed) — FROZEN

Declared family for the multiple-testing haircut (every cell is robustness evidence,
never a verdict basis):
- formation `F ∈ {1wk (primary), 2wk, 4wk}`;
- estimation `E ∈ {104wk, 156wk (primary)}`;
- portfolio cut `∈ {decile=10% (primary), quintile=20%}`;
- factor set `∈ {3-factor MKT+SMB+HML (primary), 4-factor +industry-sector demean}`.

**Primary cell (pre-fixed, single):** `F=1wk, E=156wk, decile, 3-factor,
weekly rebalance, 2.0× gross cap, 10% vol target`. Only this cell decides PASS.

## 13. PASS definition (all must hold, at ×2, on the primary cell) — FROZEN

1. Gate 1 ∧ Gate 2 ∧ Gate 3 pass; **and**
2. OOS significantly beats the 50% hurdle (`significant_beats_hurdle`); **and**
3. Survives the multiple-testing haircut (primary survives Bonferroni); **and**
4. **No** tail window (§10) breaches MDD ≤ 20%; **and**
5. Short-leg EVO-10 red-lines (§6) passed 锦衣卫 review.

All five ⇒ **PASS**. Otherwise negative, labelled by the failing numbers
(`基线未达标` for a CAGR/MDD gate-1 miss; `尾部未过线` for a tail-MDD breach;
`成本脆弱` if it clears ×1 but not ×2). A run on a reduced (data-insufficient) universe
is **NEVER** reported as 达标 — only as `数据不足-仅工程可复跑` + gap list. Negative is
delivered as-is and does not disturb the user (回本 issue, 吏部 安排三方核验).

## 14. Benchmarks & risk-frontier reference (EVO-12 §4, context only — never a verdict)

- SPY buy-and-hold; equal-weight-universe long-only buy-and-hold; cash.
- **Risk-frontier reference:** the SAME long-short signal at **1.0× gross (un-levered)
  and with vol-target/breaker DISABLED** — to expose how much of both the return and
  the tail come from the 2.0× leverage overlay vs the raw residual edge. Declared in
  advance; can never turn a fail into a pass.

## 15. Reproduction

```bash
# 1) (production host w/ OpenD) resolve + fetch the frozen universe, quote-only SIMULATE.
#    Commit RESIDUAL_UNIVERSE_RESOLVED.txt to THIS branch BEFORE any results commit.
python -m qlab.swing.resolve_universe --top 250 --out RESIDUAL_UNIVERSE_RESOLVED.txt   # 工部
python -c "from qlab.events.datafetch.opend_daily import fetch_daily_parquet as f; \
  import pathlib; syms=[s.strip() for s in open('qlab/RESIDUAL_UNIVERSE_RESOLVED.txt') if s.strip()]; \
  f(syms+['SPY','IWM','IVE','IVW'], start='2006-01-01', end='2026-07-10', data_dir='data/daily_full')"
# 2) verdict + report.json (uses whatever real bars are present; labels gaps; NEVER达标 on a reduced universe):
python -m qlab.swing.run_residual --prereg-commit <HASH>
```

## 16. Frozen parameter table (single source of truth)

| block | parameter | frozen value |
|--|--|--|
| universe | N_STOCKS | 250 (top-250 by 60d $-vol, ≥156wk hist, borrowable) |
| universe | factor ETFs | SPY, IWM, IVE, IVW (regressors only) |
| universe | total fetched | ≤ 254 ≤ 300 (hard) |
| model | frequency | weekly (ISO week, last OpenD trading day) |
| model | factors | MKT=SPY, SMB=IWM−SPY, HML=IVE−IVW |
| model | beta estimation E | 156 weeks rolling OLS, min 104 valid |
| model | residual | r − (α̂ + β̂·f), 3-factor |
| model | formation F | 1 week (signal = −ε of most recent week) |
| model | standardization | cross-sectional winsorize 1/99 pct, then rank |
| portfolio | cut | decile long / decile short (~25 names/leg) |
| portfolio | weighting | equal-weight, dollar-neutral, beta-neutral (|β|≤0.05) |
| portfolio | rebalance | weekly |
| leverage | base / cap | 2.0× / 2.0× hard |
| leverage | vol target | 10% ann., 26wk window, gross∈[0.5×,2.0×] |
| leverage | breaker | 5d DD ≥ 8% → gross 0.5× next week |
| leverage | financing | 6.8%/yr on (gross−1)·NAV |
| risk | names/leg | ≥ 20 |
| risk | single-name cap | ≤ 5% gross |
| risk | single-sector net | ≤ 10% gross |
| risk | per-name short stop | +25% adverse |
| cost | commission+spread | 10 bps/side base, ×1 and ×2 (decision ×2) |
| cost | borrow | 0.5%/yr short notional |
| execution | timing | close(T) signal → open(T+1), open-to-open, unit-tested |
| gates | CAGR / MDD | ≥50% / ≤20% (gate 1∧2∧3) |
| significance | boot / seed / alpha | 2000 / 12345 / 0.05, hurdle 0.50 |
| haircut | family | F{1,2,4}wk × E{104,156}wk × {decile,quintile} × {3f,4f}; primary pre-fixed |
| tails | windows | 2007-08, 2008, 2018Q4, 2020-03, 2022, 2025-26 (each MDD≤20%) |
| data | source | OpenD qfq daily, quote-only, TrdEnv.SIMULATE hard-lock |
