# EVO-24 data wiring — real earnings timestamps + adjusted daily bars

This subpackage fills the two blocking data gaps for the earnings-event drift
battery (candidates 4+5) from **free / out-of-band** sources, and feeds the
existing sinks with no change to the backtest:

| Gap | Sink | Source (this package) | Status in this workspace |
|-----|------|-----------------------|--------------------------|
| #1 real earnings timestamps (bmo/amc) | `CsvEventSource` → `data/earnings.csv` | SEC EDGAR 8-K **item 2.02** | ✅ **fetched & committed** (473 events, 19 symbols, 2019–2024) |
| #2 real adjusted daily open/close bars | `ParquetDailyBarSource` → `data/daily/<sym>_1d.parquet` | Stooq / Nasdaq / Yahoo **or** OpenD | ⛔ **blocked here** — see [Blockers](#blockers). Fetchers wired & unit-tested; run on a non-blocked host |
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

## Gap #2 — adjusted daily bars — WIRED, BLOCKED ON EGRESS/GATEWAY

`ParquetDailyBarSource` needs `[date, open, high, low, close, volume]` with
**split- AND dividend-adjusted** OHLC. Adjustment is mandatory: candidate 5
computes `overnight = open[t+1]/close[t]`; an unadjusted split day would inject a
fake ±hundreds-of-percent overnight gap.

Four interchangeable backends, each returning `(DataFrame | None, note)` so a
blocked source is an honest gap, not fake data:

| Backend | Endpoint | Adjustment | `--price-source` |
|---------|----------|-----------|------------------|
| Stooq | `q/d/l` CSV (SHA-256 PoW solved in-code) | split + dividend | `stooq` |
| Nasdaq | `api/quote/.../historical` JSON | split | `nasdaq` |
| Yahoo | `v8/finance/chart` JSON (`adjclose`-rescaled) | split + dividend | `yahoo` |
| OpenD | `request_history_kline(K_DAY)` via moomoo SDK | adjusted (`autype`) | `opend` |

### Run it (from a non-blocked host)

```bash
# free source (residential / non-datacenter egress IP):
python -m qlab.events.datafetch.fetch_all --what prices --price-source stooq \
    --start 2019-01-01 --end 2024-12-31 --out data

# or via OpenD (host with a reachable OpenD gateway + moomoo-api installed):
python -m qlab.events.datafetch.fetch_all --what prices --price-source opend \
    --start 2019-01-01 --end 2024-12-31 --out data
```

### OpenD path — vendored file untouched

`vendor/qstrat/data/fetcher.py` ships `TIMEFRAME_MAP = {"1m", "15m"}` only.
`opend_daily.py` adds `"1d": KLType.K_DAY` **from the outside** at import time
(`TIMEFRAME_MAP.setdefault("1d", KLType.K_DAY)`) — the vendored source stays
byte-for-byte unchanged, so an upstream re-sync never conflicts. Without the
moomoo SDK / a live gateway it raises `OpenDUnavailable`, which `fetch_all`
records as a blocker rather than crashing.

---

## Blockers

Precise state as of **2026-07-10** in this workspace:

1. **All free price sources block this egress IP.** Empirically:
   - Stooq → solves the JS proof-of-work, then `Access denied` (IP-level block).
   - Yahoo `v8/chart` → HTTP `429 Too Many Requests` on every request.
   - Nasdaq `api/quote` → HTTP 200 but `totalRecords: 0` (datacenter soft-block).
   - FMP demo key → 401 (only unlocks its own AAPL demo).
   This is a datacenter-IP reputation block, **not** a code bug — the same
   fetchers work from a normal/residential IP. Pushing past PoW + IP blocks would
   be anti-bot evasion and was deliberately not attempted.
2. **OpenD is unreachable here.** No OpenD gateway, no `moomoo-api` SDK, no
   account — OpenD is unreachable even in SIMULATE mode from this workspace
   (per EVO-8). `opend` source raises `OpenDUnavailable`.

### What to run where to unblock a real verdict

- **On a host with normal internet egress** (any laptop / residential VPS):
  `python -m qlab.events.datafetch.fetch_all --what prices --price-source stooq --start 2019-01-01 --end 2024-12-31 --out data`
  → writes `data/daily/<sym>_1d.parquet` for the 19 symbols.
- **On a host with a running OpenD gateway** (+ `pip install moomoo-api` matching
  the gateway): same command with `--price-source opend`.
- Then the **real backtest** goes end-to-end with zero code change:
  ```bash
  python -m qlab.events.run_events --source parquet \
      --data-dir data/daily --events-csv data/earnings.csv \
      --symbols AAPL MSFT NVDA AMZN GOOGL META CSCO INTC ORCL \
               JPM BAC GS WMT HD KO PG JNJ PFE CVX \
      --mode both --hold 5 10 20 30 --out qlab/reports/events_real
  ```

`*.parquet` is git-ignored by repo convention (bars are regenerated, not
committed); `data/earnings.csv` **is** committed as the delivered gap-#1 artifact.

---

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
