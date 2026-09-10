"""Fixed deliverable text: the data-gap list and the risk register (EVO-24).

Kept as data (not prose buried in the CLI) so the report and the tests reference
one source of truth, and so a future run that closes a gap edits exactly one place.
"""
from __future__ import annotations

# What real data must be supplied before ANY number here can be a verdict.
DATA_GAP_LIST = [
    {
        "gap": "real_earnings_timestamps",
        "blocks": "everything (event definition)",
        "detail": "No real earnings-announcement timestamps with correct bmo/amc "
                  "tagging are available in this workspace. Needed: per-symbol "
                  "announcement datetime (Eastern) + session. Sources: SEC EDGAR 8-K "
                  "filing timestamps (free), or a vendor earnings calendar. Feed via "
                  "CsvEventSource.",
    },
    {
        "gap": "real_daily_open_close_bars",
        "blocks": "candidate 5 (close-to-open) and all returns",
        "detail": "close-to-open requires reproducible daily open AND close per "
                  "session. OpenD supplies these via request_history_kline(K_DAY) — "
                  "the fetcher exists at vendor/qstrat/data/fetcher.py; add "
                  "'1d': KLType.K_DAY to TIMEFRAME_MAP, persist to "
                  "<symbol>_1d.parquet, load via ParquetDailyBarSource. Free "
                  "alternatives: Stooq daily. Must be split/dividend adjusted.",
    },
    {
        "gap": "historical_options_chain",
        "blocks": "negative branch (defined-risk short)",
        "detail": "No historical options chain (strikes, expiries, bid/ask, IV). "
                  "Without it the negative branch CANNOT be priced or settled and is "
                  "recorded blocked/missing-data — it is NEVER converted to a naked "
                  "short. Source: OpenD option chain + historical option quotes, or a "
                  "vendor. Feed via an OptionsChainSource implementation.",
    },
    {
        "gap": "point_in_time_universe",
        "blocks": "survivorship-bias control",
        "detail": "Backtest universe must be the point-in-time membership including "
                  "delisted/acquired names, not today's survivors. Needs a historical "
                  "constituents source.",
    },
    {
        "gap": "analyst_consensus_estimates",
        "blocks": "surprise sign quality (optional)",
        "detail": "Consensus EPS estimates would give a cleaner surprise sign (SUE). "
                  "Absent, the package falls back to the post-announcement abnormal-"
                  "return quantile proxy (as EVO-24 specifies), which is noisier.",
    },
]

# Standing risks to report alongside any result (EVO-24 requires these listed).
RISK_REGISTER = [
    {"risk": "timestamp_error", "severity": "high",
     "detail": "A bmo/amc mislabel or a timezone error flips which bar is the "
               "reaction bar and can inject look-ahead. Entry timing is built to be "
               "T+1-open conservative, but it is only as correct as the announcement "
               "timestamps fed in."},
    {"risk": "survivorship_bias", "severity": "high",
     "detail": "Until a point-in-time universe is supplied, results computed on "
               "surviving names will overstate returns."},
    {"risk": "liquidity", "severity": "medium",
     "detail": "PEAD/overnight names can be thin; a min-ADV floor is enforced and "
               "capacity must be reported, but real slippage on small caps can exceed "
               "the modeled bps."},
    {"risk": "options_data_gap", "severity": "high",
     "detail": "The entire negative branch is unrealized here. Any full-strategy "
               "return that pretends to capture negative-surprise drift without a "
               "priced defined-risk structure is invalid."},
    {"risk": "overfitting_multiple_testing", "severity": "medium",
     "detail": "Holding-period (5/10/20/30) and quantile are searched; the winner "
               "must survive walk-forward OOS and a multiple-testing haircut before "
               "any PASS."},
    {"risk": "short_sample", "severity": "medium",
     "detail": "EVO-12 §5.5 wants ≥5y incl. a bull/bear. Short windows yield low-"
               "confidence conclusions."},
]
