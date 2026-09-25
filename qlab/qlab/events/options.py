"""Defined-risk options structures for the negative (downward-drift) branch.

EVO-24 hard constraint: a negative earnings surprise implies downward drift, but
we may express it ONLY through a *defined-risk* structure — a long put or a bear
put spread — never a naked short of the stock. This module is the ONLY place the
package can obtain downside exposure, and pricing a structure REQUIRES real
option quotes. There is deliberately no synthetic-premium fallback: without a
real chain the negative branch returns ``None`` and the backtester records it as
a *blocked, missing-data* branch (its notional never enters the equity curve).

Because there is no code path here (or anywhere in the package) that shorts
stock, "accidentally became a naked short" is structurally impossible, not just
discouraged.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import pandas as pd


@dataclass(frozen=True)
class OptionQuote:
    """One option leg quote at a point in time (bid/ask, so the EVO-12 §4 spread
    cost can be charged honestly rather than mid-priced)."""

    expiry: pd.Timestamp
    strike: float
    right: str          # "P" or "C"
    bid: float
    ask: float

    @property
    def mid(self) -> float:
        return 0.5 * (self.bid + self.ask)


@dataclass(frozen=True)
class DefinedRiskTrade:
    """A priced, defined-risk options position. ``max_loss`` is the capital at
    risk (debit paid incl. spread cost); the position can never lose more."""

    structure: str          # "long_put" | "bear_put_spread"
    debit: float            # net premium paid per spread (already spread-adjusted)
    max_loss: float         # == debit for a debit structure
    max_gain: float
    legs: tuple[OptionQuote, ...]
    realizable: bool = True
    note: str = ""


class OptionsChainSource(Protocol):
    name: str

    def chain(self, symbol: str, as_of: pd.Timestamp) -> list[OptionQuote] | None:
        """Return the option chain for ``symbol`` at ``as_of``, or ``None`` if
        unavailable (missing data — NOT an occasion to fall back to shorting)."""
        ...

    def provenance(self) -> dict:
        ...


class MissingOptionsChainSource:
    """The only chain source available in this workspace: none.

    ``chain`` always returns ``None``. This is not a stub to be silently swapped
    for a short — it is the honest state of the data, and the backtester treats a
    ``None`` chain as a blocked negative branch with a gap flag.
    """

    name = "missing"

    def chain(self, symbol: str, as_of: pd.Timestamp) -> list[OptionQuote] | None:
        return None

    def provenance(self) -> dict:
        return {
            "source": "missing",
            "performance_meaningful": False,
            "note": "No historical options chain is available in this workspace "
                    "(no OpenD option-chain feed, no vendor). Negative-branch trades "
                    "cannot be priced and are recorded as blocked/missing-data. They "
                    "are NEVER converted to a naked short.",
        }


def price_bear_put_spread(chain: list[OptionQuote] | None, spot: float,
                          target_dte: int = 30, width_pct: float = 0.05,
                          spread_cost_frac: float = 0.75) -> DefinedRiskTrade | None:
    """Price a defined-risk bear put spread from a real chain, or return ``None``.

    Buys a near-the-money put and sells a lower-strike put (~``width_pct`` below),
    both at roughly ``target_dte`` days to expiry. Charges ``spread_cost_frac`` of
    each leg's bid-ask as slippage (EVO-12 §4: option spreads are large and must
    be paid, not mid-priced). Returns ``None`` when no chain is supplied — the
    caller must then flag the branch as blocked, not short the stock.
    """
    if not chain:
        return None
    puts = [q for q in chain if q.right.upper() == "P"]
    if not puts:
        return None

    # nearest expiry to target_dte
    as_of = min(q.expiry for q in puts)  # placeholder anchor; caller passes as_of chains
    expiries = sorted({q.expiry for q in puts})
    long_k_target = spot
    short_k_target = spot * (1.0 - width_pct)

    def _nearest(strikes: list[OptionQuote], target: float) -> OptionQuote:
        return min(strikes, key=lambda q: abs(q.strike - target))

    best = min(expiries, key=lambda e: abs((e - as_of).days - target_dte))
    legs_at_exp = [q for q in puts if q.expiry == best]
    long_leg = _nearest(legs_at_exp, long_k_target)
    short_leg = _nearest([q for q in legs_at_exp if q.strike < long_leg.strike] or legs_at_exp,
                         short_k_target)

    # buy long put at ask+spread cost, sell short put at bid-spread cost
    long_px = long_leg.mid + spread_cost_frac * (long_leg.ask - long_leg.mid)
    short_px = short_leg.mid - spread_cost_frac * (short_leg.mid - short_leg.bid)
    debit = max(long_px - short_px, 0.0)
    width = max(long_leg.strike - short_leg.strike, 0.0)
    max_gain = max(width - debit, 0.0)
    if debit <= 0 or width <= 0:
        return None
    return DefinedRiskTrade(
        structure="bear_put_spread", debit=debit, max_loss=debit, max_gain=max_gain,
        legs=(long_leg, short_leg), realizable=True,
        note=f"long {long_leg.strike}P / short {short_leg.strike}P exp {best.date()}",
    )
