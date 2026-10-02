"""rdagent_budget — a HARD, enforceable LLM spend cap + isolated ledger.

RD-Agent (and any LLM-driven factor miner) is only allowed to run here behind a
cap that can actually *stop* it — not a warning, not a dashboard number, an
exception that refuses the call. 首辅/工部's constraint for RD-Agent small-scale
trials: "LLM 花销硬上限（要真能卡停的，不是提示）+ 单独记账".

Two guarantees:
  1. **Hard stop.** ``guard.check(est_usd)`` raises ``BudgetExceeded`` *before*
     the call is made when it would push cumulative spend over ``cap_usd``. A
     miner loop that ignores the return value still cannot spend — the guarded
     wrapper (``guarded_call``) raises and the call never happens.
  2. **Isolated accounting.** Every call is appended as one JSON line to a
     dedicated ledger file (default ``reports/rdagent_ledger/spend.jsonl``),
     separate from all other run artifacts, so spend is auditable per call:
     timestamp, model, tokens, usd, cumulative, and the caller-supplied label.

This module has **no network and no LLM SDK dependency** — you inject the actual
call as a function, so it is unit-testable and provider-agnostic. Pricing is a
small static table (USD per 1M tokens); unknown models must be priced explicitly
or the guard refuses to estimate (fail-closed).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


class BudgetExceeded(RuntimeError):
    """Raised (fail-closed) when a call would exceed the hard cap."""


# USD per 1M tokens (input, output). Extend as needed; unknown model == refuse.
PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-4-8": (15.0, 75.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "gpt-4o": (2.5, 10.0),
    "gpt-4o-mini": (0.15, 0.60),
    "mock": (0.0, 0.0),   # for tests / dry runs
}


def estimate_usd(model: str, in_tokens: int, out_tokens: int) -> float:
    if model not in PRICING:
        raise BudgetExceeded(
            f"model {model!r} has no price entry — refusing to estimate spend "
            f"(fail-closed). Add it to PRICING first.")
    pin, pout = PRICING[model]
    return in_tokens / 1_000_000 * pin + out_tokens / 1_000_000 * pout


@dataclass
class BudgetGuard:
    """A cumulative hard cap with an append-only JSONL ledger."""

    cap_usd: float
    ledger_path: Path
    spent_usd: float = 0.0
    n_calls: int = 0
    _loaded: bool = field(default=False, repr=False)

    def __post_init__(self) -> None:
        self.ledger_path = Path(self.ledger_path).expanduser()
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        # Resume cumulative spend from an existing ledger so a restart cannot
        # reset the cap to zero and overspend across process boundaries.
        if self.ledger_path.exists():
            for line in self.ledger_path.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                self.spent_usd += float(row.get("usd", 0.0))
                self.n_calls += 1
        self._loaded = True

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.cap_usd - self.spent_usd)

    def check(self, est_usd: float) -> None:
        """Raise BEFORE a call if it would breach the cap. Fail-closed."""
        if est_usd < 0:
            raise BudgetExceeded(f"negative estimate {est_usd}")
        if self.spent_usd + est_usd > self.cap_usd + 1e-9:
            raise BudgetExceeded(
                f"call est ${est_usd:.4f} + spent ${self.spent_usd:.4f} "
                f"> cap ${self.cap_usd:.4f} (remaining ${self.remaining_usd:.4f}); "
                f"refusing call")

    def record(self, *, model: str, in_tokens: int, out_tokens: int,
               usd: float, label: str) -> dict:
        self.spent_usd += usd
        self.n_calls += 1
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "label": label,
            "model": model,
            "in_tokens": int(in_tokens),
            "out_tokens": int(out_tokens),
            "usd": round(float(usd), 6),
            "cumulative_usd": round(self.spent_usd, 6),
            "cap_usd": self.cap_usd,
            "n_calls": self.n_calls,
        }
        with self.ledger_path.open("a") as fh:
            fh.write(json.dumps(row) + "\n")
        return row


def guarded_call(
    guard: BudgetGuard,
    *,
    model: str,
    est_in_tokens: int,
    est_out_tokens: int,
    label: str,
    fn: Callable[[], tuple[str, int, int]],
) -> str:
    """Run ``fn`` behind the cap.

    ``fn`` must return ``(text, actual_in_tokens, actual_out_tokens)``.
    Pre-checks the estimated cost (raises BudgetExceeded and does NOT call fn if
    over cap), then records the *actual* cost to the ledger. This is the only
    sanctioned path for an LLM call inside the RD-Agent trial harness.
    """
    est = estimate_usd(model, est_in_tokens, est_out_tokens)
    guard.check(est)                       # <-- hard stop, before spend
    text, in_tok, out_tok = fn()
    actual = estimate_usd(model, in_tok, out_tok)
    guard.record(model=model, in_tokens=in_tok, out_tokens=out_tok,
                 usd=actual, label=label)
    return text


def guard_from_env(ledger_path: str | os.PathLike, *,
                   default_cap_usd: float = 2.0) -> BudgetGuard:
    """Build a guard whose cap comes from ``RDAGENT_LLM_CAP_USD`` (env override)."""
    cap = float(os.environ.get("RDAGENT_LLM_CAP_USD", default_cap_usd))
    return BudgetGuard(cap_usd=cap, ledger_path=Path(ledger_path))
