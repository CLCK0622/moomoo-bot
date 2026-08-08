"""api_quota — accounted HARD daily call budget for the free market-data key.

The vendor's free tier is **25 requests/day** (measured, see quotes_api). Left as
a documentation constant that is a trap: the day the quota is silently exhausted,
every later call is throttled -> ``mark_to_market`` refuses -> **that day has no
paper mark** -> a hole in the net-asset-value series. That series is the only
acceptance evidence for this track, and the hole cannot be repaired afterwards
(the close is gone; back-filling it later would be fabricating data).

So the cap is enforced the same way the RD-Agent LLM spend cap is
(``tools/qlib_gen/rdagent_budget.BudgetGuard``), and for the same reason:

  1. **Persisted daily ledger** (one JSONL line per call, bucketed by UTC date)
     that RESUMES across processes and restarts — two runs on the same day share
     one counter instead of each counting from zero.
  2. **Pre-call check**: ``check()`` raises ``QuotaExceeded`` *before* the request
     goes out. We do not wait for the vendor's throttle reply to discover it.
  3. **Reservation for marking**: of the daily cap, ``reserve_for_marking`` is
     ring-fenced. Exploratory calls may only consume ``cap - reserve``, so
     "today's NAV point gets recorded" always outranks any other call.
  4. ``status()`` reports used/remaining per purpose so a tightening quota is
     visible in the weekly status line rather than discovered by hitting a wall.

Day bucketing is by **UTC date**. The vendor's own reset boundary is not
documented precisely; UTC bucketing is stable and auditable, and the reservation
plus ~2x headroom (≈11 marking calls vs 25) absorbs any boundary mismatch. Set
``QLAB_AV_DAILY_CAP`` to lower the cap if the vendor tightens it.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DEFAULT_LEDGER = Path("~/.local/state/qlab/av_quota.jsonl")
DEFAULT_CAP_PER_DAY = 25          # measured on the free key (quotes_api)
DEFAULT_RESERVE_FOR_MARKING = 15  # ring-fenced so the daily NAV point always fits

MARKING = "marking"               # mark-to-market: may use the full cap
EXPLORATION = "exploration"       # anything else: capped at (cap - reserve)


class QuotaExceeded(RuntimeError):
    """Raised BEFORE a call that would breach the daily budget (fail-closed)."""


def _utc_day(when: Optional[datetime] = None) -> str:
    return (when or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%d")


@dataclass
class DailyQuotaGuard:
    """A per-UTC-day call budget with an append-only JSONL ledger."""

    cap_per_day: int = DEFAULT_CAP_PER_DAY
    reserve_for_marking: int = DEFAULT_RESERVE_FOR_MARKING
    ledger_path: Path = field(default_factory=lambda: DEFAULT_LEDGER)
    _counts: dict[str, dict[str, int]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if self.reserve_for_marking > self.cap_per_day:
            raise ValueError("reserve_for_marking cannot exceed cap_per_day")
        self.ledger_path = Path(self.ledger_path).expanduser()
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        # Resume from disk so a second process/run on the same day continues the
        # same count instead of restarting at zero (that would defeat the cap).
        if self.ledger_path.exists():
            for line in self.ledger_path.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                day = row.get("utc_day")
                purpose = row.get("purpose", EXPLORATION)
                if not day:
                    continue
                bucket = self._counts.setdefault(day, {})
                bucket[purpose] = bucket.get(purpose, 0) + int(row.get("n", 1))

    # ---- accounting -------------------------------------------------------
    def used(self, purpose: Optional[str] = None, *, day: Optional[str] = None) -> int:
        bucket = self._counts.get(day or _utc_day(), {})
        return bucket.get(purpose, 0) if purpose else sum(bucket.values())

    @property
    def exploration_cap(self) -> int:
        return self.cap_per_day - self.reserve_for_marking

    def remaining(self, purpose: str = MARKING, *, day: Optional[str] = None) -> int:
        day = day or _utc_day()
        overall_left = self.cap_per_day - self.used(day=day)
        if purpose == MARKING:
            return max(0, overall_left)
        # exploration is additionally bounded by its own sub-budget
        expl_left = self.exploration_cap - self.used(EXPLORATION, day=day)
        return max(0, min(overall_left, expl_left))

    def check(self, n: int = 1, *, purpose: str = MARKING,
              day: Optional[str] = None) -> None:
        """Raise BEFORE issuing ``n`` calls if they would breach the budget."""
        if n < 1:
            raise ValueError("n must be >= 1")
        day = day or _utc_day()
        left = self.remaining(purpose, day=day)
        if n > left:
            raise QuotaExceeded(
                f"{purpose}: requested {n} call(s) but only {left} left today "
                f"({day}; used {self.used(day=day)}/{self.cap_per_day}, "
                f"exploration {self.used(EXPLORATION, day=day)}/{self.exploration_cap}). "
                f"Refusing — the daily mark must not be starved by other calls.")

    def record(self, *, purpose: str = MARKING, symbol: str = "",
               n: int = 1, note: str = "", day: Optional[str] = None) -> dict:
        day = day or _utc_day()
        bucket = self._counts.setdefault(day, {})
        bucket[purpose] = bucket.get(purpose, 0) + n
        row = {"ts": datetime.now(timezone.utc).isoformat(), "utc_day": day,
               "purpose": purpose, "symbol": symbol, "n": n, "note": note,
               "used_today": self.used(day=day), "cap_per_day": self.cap_per_day}
        with self.ledger_path.open("a") as fh:
            fh.write(json.dumps(row) + "\n")
        return row

    def spend(self, *, purpose: str = MARKING, symbol: str = "", n: int = 1,
              note: str = "") -> dict:
        """check() then record() — the sanctioned way to account for a call."""
        self.check(n, purpose=purpose)
        return self.record(purpose=purpose, symbol=symbol, n=n, note=note)

    def status(self, *, day: Optional[str] = None) -> dict:
        """One-glance quota state for the weekly status line."""
        day = day or _utc_day()
        return {
            "utc_day": day,
            "cap_per_day": self.cap_per_day,
            "used_total": self.used(day=day),
            "remaining_total": max(0, self.cap_per_day - self.used(day=day)),
            "used_marking": self.used(MARKING, day=day),
            "used_exploration": self.used(EXPLORATION, day=day),
            "reserve_for_marking": self.reserve_for_marking,
            "exploration_cap": self.exploration_cap,
            "remaining_exploration": self.remaining(EXPLORATION, day=day),
            "ledger": str(self.ledger_path),
        }


def guard_from_env(ledger_path: Optional[str | os.PathLike] = None) -> DailyQuotaGuard:
    """Build a guard; ``QLAB_AV_DAILY_CAP`` / ``QLAB_AV_MARK_RESERVE`` override."""
    return DailyQuotaGuard(
        cap_per_day=int(os.environ.get("QLAB_AV_DAILY_CAP", DEFAULT_CAP_PER_DAY)),
        reserve_for_marking=int(os.environ.get("QLAB_AV_MARK_RESERVE",
                                               DEFAULT_RESERVE_FOR_MARKING)),
        ledger_path=Path(ledger_path or os.environ.get("QLAB_AV_QUOTA_LEDGER",
                                                       DEFAULT_LEDGER)),
    )
