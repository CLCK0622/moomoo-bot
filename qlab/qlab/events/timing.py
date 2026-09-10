"""Look-ahead-free event → bar-index timing (shared by bars.py and strategy.py).

The single source of truth for *when* an earnings event first moves the tape and
when we are allowed to trade on it. Keeping this in one module guarantees the
synthetic bar generator injects drift at exactly the bar the strategy reads it
from — otherwise a passing harness test would prove nothing.

Convention (conservative, strictly look-ahead-free):

* **reaction bar** = the first full trading day whose close reflects the news.
    - ``bmo`` / ``intraday``: the announcement day itself (index ``i``).
    - ``amc``: the next trading day (index ``i+1``) — the announcement lands
      after ``close[i]``, so day ``i+1`` is the first full session on the news.
* **entry bar** = ``reaction_bar + 1``. We decide using only closes up to and
  including the reaction bar, then execute at the *next* bar's open (EVO-12 §4:
  "信号在 bar 收盘产生的，最早在下一 bar 开盘成交"). This forgoes the initial
  announcement gap on purpose — that gap is the surprise *signal*, and capturing
  it would require trading before the information is public.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def first_session_index(dates: pd.DatetimeIndex, day: pd.Timestamp) -> int | None:
    """Index of the first trading day ``>= day`` (announcements can fall on a
    weekend/holiday; roll forward to the next session). ``None`` if past the end."""
    day = pd.Timestamp(day).normalize()
    pos = int(np.searchsorted(dates.values, np.datetime64(day), side="left"))
    if pos >= len(dates):
        return None
    return pos


def reaction_index(dates: pd.DatetimeIndex, announce_date: pd.Timestamp, session: str) -> int | None:
    """Index of the reaction bar for an announcement, or ``None`` if out of range."""
    i = first_session_index(dates, announce_date)
    if i is None:
        return None
    if session == "amc":
        i = i + 1
    if i >= len(dates):
        return None
    return i


def entry_index(dates: pd.DatetimeIndex, announce_date: pd.Timestamp, session: str) -> int | None:
    """Index of the (look-ahead-free) entry bar, or ``None`` if out of range."""
    r = reaction_index(dates, announce_date, session)
    if r is None:
        return None
    e = r + 1
    if e >= len(dates):
        return None
    return e
