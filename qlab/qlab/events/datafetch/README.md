# EVO-24 data wiring — real earnings timestamps + adjusted daily bars

This subpackage fills the two blocking data gaps for the earnings-event drift
battery (candidates 4+5) from **free / out-of-band** sources, and feeds the
existing sinks with no change to the backtest:

| Gap | Sink | Source (this package) | Status in this workspace |
|-----|------|-----------------------|--------------------------|
| #1 real earnings timestamps (bmo/amc) | `CsvEventSource` → `data/earnings.csv` | SEC EDGAR 8-K **item 2.02** | ✅ **fetched & committed** (473 events, 19 symbols, 2019–2024) |
| #2 real adjusted daily open/close bars | `ParquetDailyBarSource` → `data/daily/<sym>_1d.parquet` | **OpenD** (`request_history_kline` K_DAY, qfq) — Stooq/Nasdaq/Yahoo fallback | ✅ **fetched & committed** via the live OpenD gateway on this runtime (19 symbols × 1510 qfq-adjusted bars, 2019–2024). Free sources remain IP-blocked here (fallback for gateway-less hosts) |
| #3 historical options chain | negative branch | — | left as gap (compliance): negative branch stays `blocked`, never naked short |

The backtest only ever reads the on-disk CSV/parquet, so a missing/unreachable
fetcher degrades to the honest `需补证据` verdict instead of faking data.

---

## Gap #1 — earnings timestamps (SEC EDGAR 8-K item 2.02) — DELIVERED

An 8-K carrying **item 2.02** ("Results of Operations and Financial Condition")
is the filing a US issuer submits when it releases quarterly/annual results. Its
EDGAR *acceptance* timestamp is a faithful, free, audit-trail proxy for the
announcement **session** — the issuer files the 8-K within minutes of the press
release, so the acceptance time lands on the same side of the 09:30 open / 16:00
close boundary as the release itself. The exact minute is not load-bearing; only
the session (bmo / amc / intraday) is, and the boundary side is robust.

### Timezone — the load-bearing detail (EVO-24: "时区别错，最卡最高危")

`acceptanceDateTime` comes back as `...Z` (**UTC**). Honor the `Z`, convert to
`America/New_York` with correct DST, drop the tz, then classify on the Eastern
wall-clock. This was **verified empirically** against known reporters:

| Issuer | Known pattern | Raw acceptance (UTC) | → America/New_York | Session |
|--------|---------------|----------------------|--------------------|---------|
| JPMorgan | pre-market ~06:45 ET | `2026-01-13T11:41:09Z` | 06:41 EST | **bmo** ✓ |
| JPMorgan | pre-market ~06:45 ET | `2025-10-14T10:30:57Z` | 06:30 EDT | **bmo** ✓ |
| Apple | after close ~16:30 ET | `2026-01-29T21:30:33Z` | 16:30 EST | **amc** ✓ |
| Apple | after close ~16:30 ET | `2026-04-30T20:30:41Z` | 16:30 EDT | **amc** ✓ |

Both sides match reality **only** under UTC→ET conversion. Treating the stamp as
Eastern, or ignoring DST, silently flips bmo↔amc and injects look-ahead — exactly
the failure the constraint warns against. Pinned in `test_datafetch.py`
(`test_acceptance_utc_to_eastern_session`, `test_dst_offset_differs_across_year`).

`intraday` (item 2.02 accepted inside RTH) is **flagged, never silently
bucketed** — 26 of 473 events. The strategy enters T+1 open regardless, so an
ambiguous session is handled conservatively.

`analyst_surprise` is left blank on purpose (consensus estimates = optional gap
#4), so the backtester uses its abnormal-return quantile proxy per the spec.

### Run it (works from any host with a descriptive User-Agent)

```bash
python -m qlab.events.datafetch.fetch_all --what earnings \
    --start 2019-01-01 --end 2024-12-31 --out data
```

Delivered artifact: `qlab/data/earnings.csv` — 473 events, 19 symbols,
session mix `bmo 249 / amc 198 / intraday 26`, span 2019-01-02 → 2024-12-09.
Per-symbol counts and any 0-count symbols are in `data/fetch_manifest.json`.

---

## Gap #2 — adjusted daily bars — DELIVERED via OpenD

`ParquetDailyBarSource` needs `[date, open, high, low, close, volume]` with
**split- AND dividend-adjusted** OHLC. Adjustment is mandatory: candidate 5
computes `overnight = open[t+1]/close[t]`; an unadjusted split day would inject a
fake ±hundreds-of-percent overnight gap.

**Delivered on this runtime via the live moomoo OpenD gateway** (`--price-source
opend`): 19 symbols × **1510 qfq-adjusted daily bars** each, 2019-01-02 →
2024-12-31, committed under `data/daily/`. Adjustment verified: AAPL is
continuous across its 2020-08-31 4:1 split and NVDA across its 2024-06-10 10:1
split (no split-day jump); the largest 1-day moves are real events (AAPL 12.9%
on the 2020-03-16 COVID crash, NVDA 24.4% on its 2023-05-25 earnings gap), not
adjustment artifacts. `data/fetch_manifest.json` records `written` (19) /
`blocked` (0) per symbol.

Four interchangeable backends, each returning `(DataFrame | None, note)` so a
blocked source is an honest gap, not fake data:

| Backend | Endpoint | Adjustment | `--price-source` |
|---------|----------|-----------|------------------|
| **OpenD** (used) | `request_history_kline(K_DAY)` via moomoo SDK | **qfq (split+dividend, SDK default)** | `opend` |
| Stooq | `q/d/l` CSV (SHA-256 PoW solved in-code) | split + dividend | `stooq` |
| Nasdaq | `api/quote/.../historical` JSON | split | `nasdaq` |
| Yahoo | `v8/finance/chart` JSON (`adjclose`-rescaled) | split + dividend | `yahoo` |

### Reproduce (host with a reachable OpenD gateway + `moomoo-api` installed)

```bash
python -m qlab.events.datafetch.fetch_all --what prices --price-source opend \
    --start 2019-01-01 --end 2024-12-31 --out data
# free fallback for a gateway-less but non-IP-blocked host:
#   --price-source stooq   (see Blockers for the egress-IP caveat here)
```

Historical-K quota is counted by **distinct symbol per 30 days**; the fetch is a
single one-shot pass and never retries a symbol, so the committed parquet exists
precisely to avoid re-pulling on the downstream real-run step.

### OpenD path — vendored file untouched

`vendor/qstrat/data/fetcher.py` ships `TIMEFRAME_MAP = {"1m", "15m"}` only.
`opend_daily.py` puts `vendor/qstrat` on `sys.path` (the same idiom as
`qlab/runner.py`), imports the vendored `data.fetcher` verbatim, then adds
`"1d": KLType.K_DAY` **from the outside** (`TIMEFRAME_MAP.setdefault(...)`) — the
vendored source stays byte-for-byte unchanged, so an upstream re-sync never
conflicts. Without the moomoo SDK / a live gateway it raises `OpenDUnavailable`,
which `fetch_all` records per symbol rather than crashing. Only
`OpenQuoteContext` is opened (read-only quote); **no** trade context / unlock /
order, and the gateway process is never restarted, reconfigured, or logged out.

---

## Blockers

Precise state as of **2026-07-10** in this workspace:

1. **Gap #2 is unblocked here** — a live moomoo OpenD gateway (v10.8.6808) is
   running on this runtime, and `moomoo-api==10.08.6808` (→ `moomoo_api==10.8.6808`,
   `import moomoo`) is installed in the venv. The bars are fetched and committed.
   Note the SDK is `moomoo-api` (NOT `futu-api`, which exposes `import futu`).
2. **Free price sources still block this egress IP** (kept wired as the fallback
   for a gateway-less host). Empirically:
   - Stooq → solves the JS proof-of-work, then `Access denied` (IP-level block).
   - Yahoo `v8/chart` → HTTP `429 Too Many Requests` on every request.
   - Nasdaq `api/quote` → HTTP 200 but `totalRecords: 0` (datacenter soft-block).
   - FMP demo key → 401 (only unlocks its own AAPL demo).
   Datacenter-IP reputation block, **not** a code bug. Pushing past PoW + IP
   blocks would be anti-bot evasion and was deliberately not attempted.

### Downstream real run (both gaps' data now on the branch)

The real backtest goes end-to-end with zero code change, reading the committed
`data/earnings.csv` + `data/daily/*.parquet`:

```bash
python -m qlab.events.run_events --source parquet \
    --data-dir data/daily --events-csv data/earnings.csv \
    --symbols AAPL MSFT NVDA AMZN GOOGL META CSCO INTC ORCL \
             JPM BAC GS WMT HD KO PG JNJ PFE CVX \
    --mode both --hold 5 10 20 30 --out qlab/reports/events_real
```

The delivered daily-bar `*.parquet` under `data/daily/` **is** committed (an
explicit `!data/daily/*.parquet` negation in `.gitignore`) so this real-run step
reads them from the branch without re-hitting the 30-day historical-K quota;
other ad-hoc parquet stays ignored. `data/earnings.csv` is likewise committed.

---

## Candidate A (rate-carry sleeve) data — `fred_yields.py` (EVO-8)

New free source added for the rate-carry sleeve. Two data legs:

- **Yield curve — DELIVERED.** `fred_yields.py` pulls FRED H.15 constant-maturity
  Treasury yields (`DGS3MO/DGS2/DGS5/DGS10/DGS30`) from `fredgraph.csv` — **no API
  key**, not IP-blocked here. Committed to `data/fred_yields.parquet` (wide
  `[date, DGS*]`, 2002-01-02 → 2026-07-27, 6145 rows, 0 NaN; the 2022 rate shock
  and 2s10s inversion are fully covered). FRED `"."` markers are dropped, never
  forward-filled (no synthetic values). Refetch:
  ```bash
  python -c "from qlab.events.datafetch.fred_yields import fetch_curve, write_parquet; \
    w,n=fetch_curve(start='2002-01-01', end='2026-12-31'); write_parquet(w,'data/fred_yields.parquet'); print(n)"
  ```
- **Treasury ETF bars (SHY/IEF/TLT) — BLOCKED, not committed.** Needs
  dividend-adjusted daily bars (coupons are ~all of a bond ETF's total return, so
  split-only is wrong). Both adjusted paths are gated on infra outside the run:
  free equity sources still IP-block this egress (§Blockers), and the OpenD
  gateway was down (`127.0.0.1:11111` closed). No bars were fabricated. Full
  status + exact refetch commands in `data/rate_carry_provenance.json`; unblock =
  bring up OpenD (system `python3` has the SDK) **or** run the free-source fetch
  from a non-datacenter IP.

## Known caveats carried forward (not introduced here)

- **Survivorship bias** — the default 19-name universe is present-day survivors;
  this is *not* point-in-time. Feed a historical constituent list via `--symbols`
  for a real study. Tracked in the risk register / card_E.
- **Ticker→CIK drift** — `resolve_ciks` uses SEC's *current* map; a few tickers
  now resolve to a new holding entity with no filing history (e.g. `XOM` → CIK
  0002115436, 0 events), so they silently yield nothing. Always check the
  manifest's `events_per_symbol` for 0-count symbols. `XOM` is excluded from the
  default universe for this reason.
- **Options chain (gap #3)** still open → negative branch stays `blocked`
  (defined-risk only, never a naked short).
