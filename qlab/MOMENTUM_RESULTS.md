# EVO-23 candidate-1+2 (ETF right-side momentum) — RESULTS

**Pre-registration commit (frozen BEFORE this run):** `6eeccab4` — see
`MOMENTUM_EVAL_PREREGISTRATION.md`. This results doc + the report.json + all
signal/verdict code are committed strictly AFTER that hash (git ordering proves
pre-registration preceded results — 工部尚书 hard gate #1).

## Verdict

| sleeve | frozen universe | real OpenD bars present | verdict |
|--|--|--|--|
| A — TSMOM (cand 1) | 8 ETFs | **3/8** (SPY,QQQ,IWM) | `数据不足-仅工程可复跑` (NOT达标) |
| B — sector RS (cand 2) | 11 SPDR sectors | **0/11** | `数据不足-无法评估` |

**Neither sleeve is达标, and neither is claimed达标.** Sleeve A ran on a reduced,
data-insufficient universe; sleeve B has no real sector data at all. Per hard gate
#3 the deliverable is the reproducible engine + this honest gap list, not a pass.

## Sleeve A primary (12-mo TSMOM, ×2 cost) on the reduced SPY/QQQ/IWM universe

Reported as ENGINEERING EVIDENCE only — 5 of 8 slots are permanently cash by data
gap (max gross = 3/8 = 37.5%), so this structurally understates the frozen design.

- **Gate 1:** CAGR **3.46%** (hurdle 50%) — FAIL; MDD 10.14% (≤20% ok, but the CAGR
  miss is decisive). Gate 2 FAIL (worst full year −5.6%, combined 3.46%). Gate 3
  FAIL (median window CAGR 3.9%, 0% of windows ≥50%). `three_gate_verdict = 基线未达标`.
- **Significance:** `p(CAGR<hurdle)=1.000`, `significant_beats_hurdle=False`.
- **Haircut:** primary does NOT survive (gates fail + Bonferroni).
- **Tail windows:** all four pass MDD≤20% — but that is a by-product of being mostly
  cash at 3.46% CAGR, not evidence of edge.

## Structural finding (risk-frontier reference — context, not a verdict)

Equal-weight **buy&hold** of SPY/QQQ/IWM, no momentum/cash switch (2006-06→2026-07,
×2 cost): **CAGR 12.31%, MDD 55.74%.** Even removing all risk control and running
100% always-on, these liquid unlevered ETFs return ~12% CAGR while drawing down 56%
(2008/2020). ⇒ The 50%-CAGR / ≤20%-MDD **joint** mandate is structurally out of
reach for an unlevered long-only liquid-ETF momentum sleeve — the same wall
candidate-8 (VIX carry) hit. The trend filter caps MDD (10% vs 56%) but cannot
manufacture the missing ~40 CAGR points without leverage the mandate forbids.

## Gap list — to complete the frozen verdict (needs an OpenD gateway host)

Missing real OpenD daily bars (quote-only, `TrdEnv.SIMULATE`), 2006-01→2026-07:

- Sleeve A: `TLT IEF GLD DBC UUP` (+ `SHY` cash proxy)
- Sleeve B: `XLY XLI XLK XLF XLV XLP XLU XLE XLB XLRE XLC` (+ `SHY`)

OpenD is not reachable in this workspace (`opend_daily` raises `OpenDUnavailable`).
External feeds (yfinance/CBOE) are NOT auto-extended from EVO-25 — any external
source is filed case-by-case to 吏部/首辅 first. Fetch on an OpenD host:

```
python -c "from qlab.events.datafetch.opend_daily import fetch_daily_parquet as f; \
  f(['TLT','IEF','GLD','DBC','UUP','SHY','XLY','XLI','XLK','XLF','XLV','XLP', \
     'XLU','XLE','XLB','XLRE','XLC'], start='2006-01-01', end='2026-07-10', \
    data_dir='data/daily_full')"
```

Then re-run — the verdict recomputes with zero code change:

```
python -m qlab.swing.run_momentum --sleeve tsmom     --prereg-commit 6eeccab4
python -m qlab.swing.run_momentum --sleeve sector_rs --prereg-commit 6eeccab4
```

## Reproduce this exact run

```
cd qlab
python -m pytest tests/test_momentum.py -q          # 7 adapter tests (contract/no-look-ahead/long-only)
python -m pytest -q                                  # full suite: 100 passed
PYTHONPATH=. python -m qlab.swing.run_momentum --sleeve tsmom     --prereg-commit 6eeccab4
PYTHONPATH=. python -m qlab.swing.run_momentum --sleeve sector_rs --prereg-commit 6eeccab4
```

Reports: `qlab/reports/momentum_tsmom/report.json`,
`qlab/reports/momentum_sector_rs/report.json` (full EVO-12 B/C/D/E card +
gates 1-3 + significance + haircut + tail stress + benchmarks).
