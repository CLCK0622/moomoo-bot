"""Strategy-signal ingest for the execution layer (EVO-13 接入而非重建).

The boundary between a research repo (e.g. ``quant-strategies``) and this execution
layer is a small, explicit **signal handoff**: a list of per-symbol target weights.
We do NOT re-run the research backtest here; the research side emits signals + its
config, and we ingest them. The only checking done is a *lightweight sanity check*
("信号/作者口径是否明显对得上") — not the four-gate/WF门禁.

Interchange format (JSON)::

    {
      "source": "quant-strategies@<sha>",
      "generated_at": "2026-06-18",
      "signals": [
        {"symbol": "TSLA", "target_weight": 0.2, "ts": "2026-06-18", "reason": "vwap_reversion"},
        {"symbol": "NVDA", "target_weight": 0.2}
      ]
    }

``target_weight`` is the fraction of equity to hold (+long / 0 flat / −short).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass(frozen=True)
class TargetSignal:
    symbol: str
    target_weight: float  # fraction of equity in [-1, 1]
    ts: str | None = None
    reason: str = ""


@dataclass
class SignalSet:
    signals: list[TargetSignal] = field(default_factory=list)
    source: str = "unknown"
    generated_at: str | None = None

    @classmethod
    def from_dict(cls, payload: dict) -> SignalSet:
        sigs = [
            TargetSignal(
                symbol=str(s["symbol"]).upper(),
                target_weight=float(s["target_weight"]),
                ts=s.get("ts"),
                reason=s.get("reason", ""),
            )
            for s in payload.get("signals", [])
        ]
        return cls(
            signals=sigs,
            source=payload.get("source", "unknown"),
            generated_at=payload.get("generated_at"),
        )

    def active(self) -> list[TargetSignal]:
        """Signals that request a non-flat position."""
        return [s for s in self.signals if abs(s.target_weight) > 1e-9]


def load_signals(path: str) -> SignalSet:
    with open(path, encoding="utf-8") as fh:
        return SignalSet.from_dict(json.load(fh))


def sanity_check(
    sigset: SignalSet,
    *,
    universe: list[str] | None = None,
    max_positions: int | None = None,
    max_gross: float = 1.0,
) -> list[str]:
    """Lightweight reconciliation only — does the signal set obviously line up with
    the author's stated口径? Returns a list of human-readable issues (empty = ok).

    This is NOT a performance gate; it just catches gross mismatches before the
    signals are routed to the execution layer.
    """
    issues: list[str] = []
    seen: set[str] = set()
    for s in sigset.signals:
        if not -1.0 - 1e-9 <= s.target_weight <= 1.0 + 1e-9:
            issues.append(f"{s.symbol}: target_weight {s.target_weight} out of [-1,1]")
        if s.symbol in seen:
            issues.append(f"{s.symbol}: duplicate signal")
        seen.add(s.symbol)
        if universe is not None and s.symbol not in {u.upper() for u in universe}:
            issues.append(f"{s.symbol}: not in declared universe")

    active = sigset.active()
    if max_positions is not None and len(active) > max_positions:
        issues.append(f"{len(active)} active positions > max_positions {max_positions}")
    gross = sum(abs(s.target_weight) for s in active)
    if gross > max_gross + 1e-9:
        issues.append(f"gross exposure {gross:.2f} > {max_gross:.2f}")
    return issues
