# qlab.events — earnings-event drift backtest package (EVO-24, candidates 4 + 5)

Built **on** the existing qlab skeleton (branch `agent/qlab-opend-exec-evo65`),
reusing its conventions (pluggable data sources with `provenance()`,
`performance_meaningful` honesty flags, seeded-synthetic-for-harness-only,
EVO-12 cost/gate discipline). It does **not** reuse the intraday-ORB engine in
`vendor/qstrat` — that engine can open *naked short* stock, which this task
forbids. This is a separate daily-frequency, event-driven backtester whose only
downside path is a defined-risk options structure.

- **Candidate 4 — PEAD**: after an earnings surprise, buy-and-hold the drift over
  H ∈ {5,10,20,30} trading days.
- **Candidate 5 — close-to-open**: hold only the overnight (close→open) legs of
  the same window, using reproducible daily open/close bars — never close-close.

## Files

```
qlab/qlab/events/
  eventsource.py   EarningsEvent + bmo/amc/intraday classification; CsvEventSource (real),
                   SyntheticEventSource (harness)
  bars.py          DailyBarSource: ParquetDailyBarSource (real), SyntheticDailyBarSource
                   (harness; injects drift at the reaction bar)
  timing.py        look-ahead-free event→bar-index mapping (single source of truth)
  surprise.py      surprise sign: analyst estimate OR post-announcement abnormal-return
                   quantile proxy (fittable train-only for walk-forward)
  options.py       OptionsChainSource + MissingOptionsChainSource + bear-put-spread pricer.
                   The ONLY downside path; no stock-short code exists.
  strategy.py      per-event trade construction (PEAD & close-to-open), costs, liquidity floor
  backtest.py      EventDriftBacktester: slots → cost-after daily equity curve
  metrics.py       EVO-12 §2 metrics (geometric CAGR, per-bar MDD, DD duration, Sharpe/Sortino…)
  gates.py         EVO-12 §3 four gates + rolling walk-forward
  report.py        data-gap list + risk register (single source of truth)
  run_events.py    CLI → EVO-12 card B/C/D/E JSON report
tests/test_events.py   27 tests (timing, close-to-open open/close, no-naked-short, cost×2, …)
```

## Run

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-lock.txt

# Synthetic harness sweep (both candidates × 5/10/20/30 holds). Reproducible, no deps.
# On synthetic data every number is a self-test and the verdict is forced to 需补证据.
python -m qlab.events.run_events --source synthetic --out reports/events_synth

# Against real data (the path to a real verdict):
python -m qlab.events.run_events --source parquet \
    --data-dir data/daily --events-csv data/earnings.csv \
    --mode both --hold 5 10 20 30 --out reports/events_real

pytest tests/test_events.py -q
```

Report is written to `<out>/report.json` with `provenance`, per-run cards
B/C/D/E, `data_gap_list`, `risk_register`, and `overall_verdict`.

## Data contract (what real data must satisfy)

- **Daily bars** `<symbol>_1d.parquet`, columns `date, open, high, low, close, volume`,
  split/dividend adjusted. Production source: OpenD `request_history_kline(ktype=K_DAY)`
  — the fetcher exists at `vendor/qstrat/data/fetcher.py`; add `"1d": KLType.K_DAY`
  to its `TIMEFRAME_MAP` and persist to parquet (vendored file left untouched here).
  Free alternative: Stooq daily.
- **Earnings events** CSV, columns `symbol, announce_time` (Eastern wall-clock) and
  optional `session, analyst_surprise, source`. Source: SEC EDGAR 8-K timestamps (free)
  or a vendor earnings calendar. `session` MUST be correct — a bmo/amc mislabel or a
  timezone error injects look-ahead.
- **Options chain** (negative branch only): historical strikes/expiries/bid-ask.
  Absent it, the negative branch is recorded blocked/missing-data — **never** a short.

## Status

Runs end-to-end and is reproducible on synthetic data (harness self-test). A real
verdict is **blocked** on real earnings timestamps, real daily open/close bars, and
a historical options chain — none available in this workspace. See `report.json`
→ `data_gap_list`. Synthetic numbers are NOT strategy performance.
