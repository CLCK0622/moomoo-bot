"""Per-event trade construction (the decision + execution functions).

Given one daily bar frame, one event, and its surprise sign, build the trade for
each candidate:

* **PEAD (candidate 4)** — long buy-and-hold from ``open[entry]`` to
  ``close[entry+H-1]`` over H trading days.
* **close-to-open (candidate 5)** — hold ONLY the overnight legs of the same
  window: each leg buys at ``close[j]`` and sells at ``open[j+1]``. Every leg
  return uses a real open and a real close — never a close-to-close substitute.

Branching (hard constraint):
* positive surprise → **long the underlying** (long-only).
* negative surprise → **defined-risk options only** (``options.py``). If no
  chain is available the branch is recorded blocked/missing-data with a
  *reference* underlying return (flagged non-realizable); it is NEVER a naked
  short. No stock-short code path exists.

All entries execute at the next bar's open (T+1), never same-bar close, and each
side pays commission+slippage (EVO-12 §4). A liquidity filter drops events whose
underlying is too thin to size into.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .eventsource import EarningsEvent
from .options import OptionsChainSource, price_bear_put_spread
from .timing import entry_index, reaction_index


@dataclass(frozen=True)
class CostModel:
    """Per-side commission + slippage in basis points (EVO-12 §4), scalable ×N."""

    commission_bps: float = 5.0     # per side; ≈ 0.1% two-sided fallback
    slippage_bps: float = 5.0       # per side; large-cap default
    cost_mult: float = 1.0

    @property
    def side_frac(self) -> float:
        return (self.commission_bps + self.slippage_bps) / 1e4 * self.cost_mult


@dataclass
class EventTrade:
    """One event's resolved trade (or the reason it wasn't taken)."""

    symbol: str
    event_date: pd.Timestamp
    session: str
    mode: str                       # "pead" | "close_to_open"
    hold: int
    sign: int
    branch: str                     # "long" | "negative_defined_risk" | "no_trade"
    realizable: bool
    entry_date: pd.Timestamp | None = None
    exit_date: pd.Timestamp | None = None
    reaction_return: float | None = None
    net_return: float = 0.0         # realized, cost-after (0 for non-realizable)
    reference_return: float | None = None   # non-realizable negative-branch ref
    daily_returns: dict = field(default_factory=dict)   # date -> per-bar contribution
    daily_notional: dict = field(default_factory=dict)  # date -> one-sided sleeve notional traded
    reason: str = ""


def compute_reaction_return(close: np.ndarray, r_idx: int) -> float | None:
    """Reaction-bar return close[r]/close[r-1]-1 (the abnormal-return proxy input)."""
    if r_idx <= 0 or r_idx >= len(close):
        return None
    prev = close[r_idx - 1]
    if prev <= 0:
        return None
    return float(close[r_idx] / prev - 1.0)


def _liquid_enough(dollar_volume: np.ndarray, e_idx: int, min_adv: float, lookback: int = 20) -> bool:
    lo = max(0, e_idx - lookback)
    window = dollar_volume[lo:e_idx]
    if len(window) == 0:
        return False
    return float(np.mean(window)) >= min_adv


def build_event_trade(df: pd.DataFrame, dates: pd.DatetimeIndex, event: EarningsEvent,
                      sign: int, *, mode: str, hold: int, cost: CostModel,
                      min_adv: float, options_src: OptionsChainSource,
                      reaction_return: float | None = None) -> EventTrade:
    """Resolve one event into an :class:`EventTrade`."""
    base = EventTrade(symbol=event.symbol, event_date=event.announce_date,
                      session=event.session, mode=mode, hold=hold, sign=sign,
                      branch="no_trade", realizable=False, reaction_return=reaction_return)

    if sign == 0:
        base.reason = "neutral_surprise"
        return base

    e_idx = entry_index(dates, event.announce_date, event.session)
    if e_idx is None:
        base.reason = "no_entry_bar_in_range"
        return base

    open_ = df["open"].to_numpy(float)
    close = df["close"].to_numpy(float)
    dvol = df["dollar_volume"].to_numpy(float)
    n = len(df)

    if not _liquid_enough(dvol, e_idx, min_adv):
        base.reason = "below_liquidity_floor"
        return base

    entry_date = dates[e_idx]
    side = cost.side_frac

    # ---- feasibility / return by mode (computed on the underlying) ----
    if mode == "pead":
        x_idx = e_idx + hold - 1                     # exit at close[e+H-1]
        if x_idx >= n:
            base.reason = "insufficient_bars_for_hold"
            return base
        exit_date = dates[x_idx]
        entry_px, exit_px = open_[e_idx], close[x_idx]
        if entry_px <= 0:
            base.reason = "bad_entry_price"
            return base
        gross = exit_px / entry_px - 1.0             # long gross
        # per-day contribution (long): day e uses close/open, then close/close
        daily = {}
        daily[dates[e_idx]] = close[e_idx] / open_[e_idx] - 1.0 - side  # entry cost
        for j in range(e_idx + 1, x_idx + 1):
            daily[dates[j]] = close[j] / close[j - 1] - 1.0
        daily[dates[x_idx]] = daily[dates[x_idx]] - side                 # exit cost
        long_net = float(np.prod([1.0 + v for v in daily.values()]) - 1.0)
        notional = {dates[e_idx]: 1.0}                                    # buy
        notional[dates[x_idx]] = notional.get(dates[x_idx], 0.0) + 1.0    # sell
    elif mode == "close_to_open":
        last_open = e_idx + hold                     # need open[e+H]
        if last_open >= n:
            base.reason = "insufficient_bars_for_hold"
            return base
        exit_date = dates[last_open]
        daily = {}
        notional = {}
        gross_factor = 1.0
        for j in range(e_idx, e_idx + hold):         # overnight legs close[j]->open[j+1]
            if close[j] <= 0:
                base.reason = "bad_leg_price"
                return base
            leg = open_[j + 1] / close[j] - 1.0
            leg_net = leg - 2.0 * side               # each overnight leg is a round trip
            daily[dates[j + 1]] = leg_net
            notional[dates[j + 1]] = 2.0             # buy close[j] + sell open[j+1]
            gross_factor *= (1.0 + leg)
        gross = gross_factor - 1.0
        long_net = float(np.prod([1.0 + v for v in daily.values()]) - 1.0)
    else:
        raise ValueError(f"unknown mode {mode!r}")

    base.entry_date = entry_date
    base.exit_date = exit_date

    # ---- branch ----
    if sign > 0:
        base.branch = "long"
        base.realizable = True
        base.net_return = long_net
        base.daily_returns = daily
        base.daily_notional = notional
        base.reason = "long_ok"
        return base

    # sign < 0 : defined-risk options ONLY — never a naked short.
    base.branch = "negative_defined_risk"
    spot = float(open_[e_idx])
    chain = options_src.chain(event.symbol, entry_date)
    priced = price_bear_put_spread(chain, spot)
    if priced is None:
        base.realizable = False
        base.reference_return = -gross          # what a (forbidden) short would net, reference only
        base.reason = "options_chain_unavailable_blocked"
        return base
    # A real chain exists but settlement needs the chain at exit too; we do NOT
    # fabricate a payoff. Record the priced structure as realizable-pending.
    base.realizable = False
    base.reference_return = -gross
    base.reason = f"priced_{priced.structure}_needs_exit_chain_to_settle"
    return base
