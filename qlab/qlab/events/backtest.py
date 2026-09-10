"""Event-drift backtester: events + daily bars → cost-after equity curve.

Portfolio model (documented, deliberately simple and auditable):

* Only **realizable long** trades deploy capital and compete for slots. An
  equal-weight book of at most ``max_concurrent`` concurrent positions, each
  sized at ``1 / max_concurrent`` of the book, rebalanced daily. Unused slots
  sit in cash (≈ ``rf``). Events arriving with the book full are *capacity
  skipped* (recorded, not silently dropped).
* The daily portfolio return is the slot-weighted sum of each active position's
  per-bar contribution (already cost-after, from ``strategy.build_event_trade``);
  the equity curve is the cumulative product.
* **Negative-branch events never deploy capital here** — no options chain, so
  they are tallied separately as blocked/missing-data with a reference return,
  and are absent from the equity curve. There is no stock-short path.

The equity curve this produces is fed verbatim to :mod:`qlab.events.metrics`
(EVO-12 §2) and :mod:`qlab.events.gates` (EVO-12 §3).
"""
from __future__ import annotations

import heapq
from collections import Counter

import numpy as np
import pandas as pd

from .eventsource import EarningsEvent, EventSource
from .options import OptionsChainSource, MissingOptionsChainSource
from .strategy import CostModel, EventTrade, build_event_trade, compute_reaction_return
from .surprise import QuantileThresholds, analyst_sign
from .timing import reaction_index


class EventDriftBacktester:
    def __init__(self, bar_source, event_source: EventSource, *,
                 mode: str = "pead", hold: int = 10,
                 cost: CostModel | None = None, min_adv: float = 2_000_000.0,
                 max_concurrent: int = 10, surprise_mode: str = "quantile",
                 quantile: float = 0.2, dead_zone: float = 0.0,
                 options_src: OptionsChainSource | None = None,
                 P: int = 252, rf_annual: float = 0.0):
        self.bars = bar_source
        self.event_source = event_source
        self.mode = mode
        self.hold = hold
        self.cost = cost or CostModel()
        self.min_adv = min_adv
        self.max_concurrent = max_concurrent
        self.surprise_mode = surprise_mode
        self.quantile = quantile
        self.dead_zone = dead_zone
        self.options_src = options_src or MissingOptionsChainSource()
        self.P = P
        self.rf_annual = rf_annual

        self._frames: dict[str, pd.DataFrame] = {}
        self._dates: dict[str, pd.DatetimeIndex] = {}
        self._events: list[EarningsEvent] = []
        self._reactions: list[float | None] = []
        self._prepared = False

    # ---- preparation ----
    def prepare(self) -> None:
        for sym in self.bars.symbols():
            df = self.bars.load(sym)
            if df is None or df.empty:
                continue
            self._frames[sym] = df
            self._dates[sym] = pd.DatetimeIndex(df["date"])
        events = self.event_source.events()
        self._events = []
        self._reactions = []
        for ev in events:
            if ev.symbol not in self._frames:
                continue
            dates = self._dates[ev.symbol]
            r = reaction_index(dates, ev.announce_date, ev.session)
            close = self._frames[ev.symbol]["close"].to_numpy(float)
            rr = compute_reaction_return(close, r) if r is not None else None
            self._events.append(ev)
            self._reactions.append(rr)
        if not self._frames:
            raise RuntimeError("No usable symbols after loading bars — check bar source.")
        self._prepared = True

    def all_reaction_returns(self) -> list[float]:
        return [r for r in self._reactions if r is not None and np.isfinite(r)]

    def _sign_for(self, ev: EarningsEvent, reaction: float | None,
                  thresholds: QuantileThresholds | None) -> int:
        if self.surprise_mode == "analyst":
            return analyst_sign(ev.analyst_surprise, self.dead_zone)
        if thresholds is None:
            raise ValueError("quantile surprise mode requires fitted thresholds")
        return thresholds.sign(reaction)

    # ---- run ----
    def run(self, event_idx: list[int] | None = None,
            thresholds: QuantileThresholds | None = None) -> dict:
        """Run over a subset of events (default all). ``thresholds`` (quantile
        mode) should be fitted on the *training* reactions for OOS runs; if
        omitted it is fitted on the runs' own reactions (in-sample, baseline)."""
        if not self._prepared:
            self.prepare()
        idxs = list(range(len(self._events))) if event_idx is None else list(event_idx)

        if self.surprise_mode == "quantile" and thresholds is None:
            thresholds = QuantileThresholds.fit(
                [self._reactions[i] for i in idxs], self.quantile)

        trades: list[EventTrade] = []
        for i in idxs:
            ev = self._events[i]
            rr = self._reactions[i]
            sign = self._sign_for(ev, rr, thresholds)
            t = build_event_trade(
                self._frames[ev.symbol], self._dates[ev.symbol], ev, sign,
                mode=self.mode, hold=self.hold, cost=self.cost,
                min_adv=self.min_adv, options_src=self.options_src, reaction_return=rr)
            trades.append(t)

        equity, trade_log, diag = self._aggregate(trades)
        return {
            "equity": equity,
            "trade_log": trade_log,
            "trades": trades,
            "diagnostics": diag,
            "thresholds": thresholds,
        }

    # ---- portfolio aggregation with slot admission ----
    def _aggregate(self, trades: list[EventTrade]):
        weight = 1.0 / self.max_concurrent
        reasons = Counter(t.reason for t in trades)
        signs = Counter(t.sign for t in trades)

        longs = sorted([t for t in trades if t.branch == "long" and t.realizable],
                       key=lambda t: (t.entry_date, t.symbol))
        negatives = [t for t in trades if t.branch == "negative_defined_risk"]

        # slot admission
        admitted: list[EventTrade] = []
        capacity_skipped = 0
        active: list[tuple[pd.Timestamp, int]] = []  # heap of (exit_date, seq)
        seq = 0
        for t in longs:
            while active and active[0][0] < t.entry_date:
                heapq.heappop(active)
            if len(active) < self.max_concurrent:
                admitted.append(t)
                heapq.heappush(active, (t.exit_date, seq))
                seq += 1
            else:
                capacity_skipped += 1

        # union calendar
        if not admitted:
            equity = pd.DataFrame(columns=["date", "equity", "ret", "traded_notional"])
        else:
            all_dates = sorted(set().union(*[set(d) for d in self._dates.values()]))
            cal = pd.DatetimeIndex(all_dates)
            start = min(t.entry_date for t in admitted)
            end = max(t.exit_date for t in admitted)
            cal = cal[(cal >= start) & (cal <= end)]
            ret = pd.Series(0.0, index=cal)
            notional = pd.Series(0.0, index=cal)
            for t in admitted:
                for d, v in t.daily_returns.items():
                    if d in ret.index:
                        ret.loc[d] += weight * v
                for d, v in t.daily_notional.items():
                    if d in notional.index:
                        notional.loc[d] += weight * v
            eq = (1.0 + ret).cumprod()
            equity = pd.DataFrame({"date": cal, "equity": eq.to_numpy(),
                                   "ret": ret.to_numpy(), "traded_notional": notional.to_numpy()})

        trade_log = [{
            "symbol": t.symbol, "entry_date": t.entry_date, "exit_date": t.exit_date,
            "net_return": t.net_return, "pnl": t.net_return, "sign": t.sign,
            "mode": t.mode, "hold": t.hold, "reaction_return": t.reaction_return,
        } for t in admitted]

        ref = [t.reference_return for t in negatives if t.reference_return is not None]
        diag = {
            "n_events": len(trades),
            "signs": {str(k): v for k, v in signs.items()},
            "reasons": dict(reasons),
            "n_long_feasible": len(longs),
            "n_admitted": len(admitted),
            "capacity_skipped": capacity_skipped,
            "negative_branch": {
                "count": len(negatives),
                "blocked_missing_options": sum(1 for t in negatives if not t.realizable),
                "realized": 0,
                "reference_return_mean": float(np.mean(ref)) if ref else None,
                "note": "negative branch is defined-risk options only; blocked here "
                        "for lack of an options chain — NEVER a naked short. Reference "
                        "return is the (non-realizable) underlying drift, for sizing "
                        "the future options study only.",
            },
        }
        return equity, trade_log, diag

    def provenance(self) -> dict:
        return {
            "bars": self.bars.provenance(),
            "events": self.event_source.provenance(),
            "options": self.options_src.provenance(),
            "config": {
                "mode": self.mode, "hold": self.hold, "max_concurrent": self.max_concurrent,
                "surprise_mode": self.surprise_mode, "quantile": self.quantile,
                "dead_zone": self.dead_zone, "min_adv": self.min_adv,
                "cost_bps_per_side": self.cost.commission_bps + self.cost.slippage_bps,
                "cost_mult": self.cost.cost_mult, "P": self.P, "rf_annual": self.rf_annual,
            },
        }
