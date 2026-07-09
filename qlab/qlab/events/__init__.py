"""Earnings-event drift backtest package (EVO-24, candidates 4 + 5).

Built ON the existing qlab skeleton (branch ``agent/qlab-opend-exec-evo65``) — it
reuses the repo's conventions (pluggable data sources with ``provenance()``,
``performance_meaningful`` honesty flags, seeded-synthetic-for-harness-only,
EVO-12 cost/gate discipline) but does NOT reuse the intraday-ORB backtest engine
in ``vendor/qstrat`` — that engine is opening-range-breakout specific and, worse,
can open *naked short* stock positions (``Portfolio.open_short_position``), which
EVO-24's hard constraint forbids. This package is a separate, daily-frequency,
event-driven backtester whose only short exposure path is a defined-risk options
structure (see ``options.py``); there is no code path that shorts stock.

Two candidates, one engine:

* **Candidate 4 — PEAD** (post-earnings-announcement drift): after an earnings
  surprise, buy-and-hold the drift over H ∈ {5,10,20,30} trading days.
* **Candidate 5 — close-to-open overnight drift**: capture only the *overnight*
  (close→open) legs of the same post-earnings window, using reproducible daily
  open/close bars — never close-to-close as a substitute.

Reality in this workspace: no OpenD gateway/SDK, no real earnings-announcement
timestamps, no historical options chain. So the deliverable is a *reproducible,
runnable skeleton* proven end-to-end on deterministic synthetic data, plus a
precise gap list. Numbers produced on synthetic data are HARNESS SELF-TESTS,
never strategy performance.
"""
from __future__ import annotations

from .eventsource import EarningsEvent, classify_session

__all__ = ["EarningsEvent", "classify_session"]
