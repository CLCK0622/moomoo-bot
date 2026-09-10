"""Out-of-band data fetchers for the earnings-event drift package (EVO-24).

This subpackage turns the two blocking data gaps into runnable wiring:

* ``sec_earnings`` — real earnings-announcement timestamps from SEC EDGAR
  8-K item 2.02 (Results of Operations), converted to US/Eastern wall-clock and
  classified bmo/amc. Produces ``data/earnings.csv`` for
  :class:`qlab.events.eventsource.CsvEventSource`. **This source works from a
  standard host with a descriptive User-Agent and is the delivered path for
  gap #1.**

* ``prices`` — real split/dividend-adjusted daily OHLC bars from free public
  sources (Stooq / Nasdaq / Yahoo), normalized to the
  ``[date, open, high, low, close, volume]`` contract and persisted to
  ``data/daily/<symbol>_1d.parquet`` for
  :class:`qlab.events.bars.ParquetDailyBarSource`.

* ``opend_daily`` — the moomoo OpenD path for the same daily bars. It extends
  the vendored ``MoomooFetcher.TIMEFRAME_MAP`` with ``"1d": KLType.K_DAY``
  **from the outside** (it does NOT edit the vendored file) and needs a live
  OpenD gateway.

* ``fetch_all`` — CLI that assembles ``data/earnings.csv`` + ``data/daily/*``
  from these sources and reports, per source, what was fetched vs. blocked.

Nothing here is imported by the backtest itself; the backtest only ever reads
the on-disk CSV/parquet, so a missing or unreachable fetcher degrades to the
honest "需补证据" verdict rather than silently faking data.
"""
