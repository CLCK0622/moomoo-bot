# Swing candidate evaluation — pre-registration & harness plan (EVO-130 · P1)

Locked **before** any swing backtest is run, per the EVO-149/首辅 discipline:
a single pre-registered primary config decides PASS; every other cell is
robustness-only; family-wise/FDR haircut applies; **no best-of-N**. This file is
the timestamped "before results" artifact — its git commit predates any S1/S5
equity curve.

Status of the blocking gate: **PASS_NO_GAP** — daily history reaches 2006-06-26
(~20 yr), covering 2018/2020/2022. Evidence: `reports/opend_kline_depth/`.

## Reused infrastructure (do NOT rebuild)

| Concern | Module (verbatim reuse) |
|---|---|
| CAGR / MDD / Sharpe from a daily equity curve | `qlab/events/metrics.py` |
| EVO-12 four gates (full-sample, per-year, rolling, walk-forward) | `qlab/events/gates.py` |
| OOS bootstrap CI + p-values (moving-block, seeded) | `qlab/events/significance.py` |
| Pre-registration + Bonferroni/BH + Deflated Sharpe haircut | `qlab/events/multiple_testing.py` |
| Cost model (commission+slippage bps, ×N multiplier) | `qlab/events/strategy.py::CostModel` |
| Daily bar source (parquet) | `qlab/events/datafetch/opend_daily.py` → `data/daily_full/` |

The swing harness only needs a **signal→daily-equity-curve** adapter per
candidate; the curve then flows verbatim into gates → significance →
multiple_testing → `report.json` (same schema as the earnings package).

## Hard hurdles (EVO-12 v1.0, unchanged)

CAGR ≥ 50%, MDD ≤ 20%; per-year ≥ 35% floor & no negative full year; rolling
median ≥ 50%, ≥ 70% windows ≥ 50%, ≤ 10% negative, every window MDD ≤ 20%; OOS
significance must **survive the multiple-testing haircut** (adjusted p < 0.05).
PASS ⟺ pre-registered primary cell clears gates **and** its haircut-adjusted OOS
p-value < 0.05. All results reported cost-after at **both ×1 and ×2**.

## Data & walk-forward (shared)

- Bars: qfq daily, 2006-06-26 → present, `data/daily_full/` (SPY persisted; rest
  fetched on demand via `fetch_daily_parquet`, ≤ 280 quota remaining).
- Walk-forward: anchored/expanding, 8+ folds; folds explicitly include the 2018,
  2020, 2022 stress regimes. OOS = concatenated out-of-fold returns.
- Execution realism: entries at next bar (T+1), overnight gaps modeled on real
  `open`→`close`/`close`→`open` legs (no close-to-close substitute), liquidity
  floor on 20-day $-ADV.

---

## S5 — FOMC pre-meeting drift (SPY) · methodology-calibration sample

- **Universe:** SPY only. **Events:** scheduled FOMC meetings, 2006→present
  (public calendar; to be committed as a checked-in CSV, source-cited).
- **Pre-registered primary config (single):** long SPY at `close` on the last
  session **before** the FOMC decision day, exit at that day's `close`
  (T-1 → T, one overnight+one session hold). One position at a time, full sleeve,
  cost ×1 primary / ×2 stress. No parameter grid is tuned; hold-window and entry
  offset are fixed here and cannot be re-picked post-hoc.
- **Primary metric:** haircut-adjusted OOS Sharpe of the pre-FOMC drift.
- **Pre-registered hypothesis (falsifiable, default = FAIL):** the effect has
  **decayed post-2015** (Kurov et al. 2021). Test both the full 2006→ sample and
  the 2015→ subsample; PASS requires the **2015→ subsample** to clear gates+haircut.
  Expectation is a **negative result** (drift no longer significant after costs);
  S5's value is as a low-footprint calibration of the walk-forward/OOS/cost stack,
  not as a live strategy. A positive full-sample-only result with a null 2015→
  subsample is reported as **decayed / not viable**, not as PASS.

## S1 — short-term oversold mean reversion (ETF / large-cap) · P1 primary

- **Universe:** liquid US ETFs + large-caps passing the $-ADV floor (from
  `data/daily_full/`).
- **Pre-registered primary config (single):** RSI(2) < 10 entry on names above
  their 200-day SMA (long-only), exit on RSI(2) > 60 or a fixed max-hold of
  **5 trading days**, equal-weight book, `max_concurrent` fixed. Entry timing and
  stop delegated to the existing intraday layer (ORB/VWAP企稳 confirmation,
  ATR/Keltner stop/size) — not re-tuned here.
- **Primary metric:** haircut-adjusted OOS CAGR at **cost ×2** (S1 is
  high-turnover; ×2 is the pass/fail line, ×1 is context only).
- **Note:** because turnover is high, the ×2 cost gate is the decisive test; a
  candidate that only clears ×1 is reported **needs-evidence / cost-fragile**,
  not PASS.

## OpenD hard-lock

Data pulls use `OpenQuoteContext` only (quote side). Any path that would require
`TrdEnv` other than `SIMULATE`, or real-money credentials, **halts and reports to
工部尚书** — it is never coded around.

## P2/P3

S3/S4/S2 (P2) evaluated only after S1/S5 close; S6/S7 (P3) stay blocked pending a
decision on external (non-OpenD) data sources. Not in this pass.
