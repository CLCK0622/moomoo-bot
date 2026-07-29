"""rdagent_skeleton — sandboxed, budget-capped small-scale factor-mining loop.

This is the **deferred-full-integration** skeleton for RD-Agent-style automation
(工部: "小规模试跑骨架 ... 全量接入后置"). It does NOT install or run the real
RD-Agent package. It provides the safe shell that any such miner must run inside:

  * **Hard budget.** Every LLM call goes through ``rdagent_budget.guarded_call``;
    when the cap is hit the loop stops — it cannot overspend (see rdagent_budget).
  * **Sandbox.** LLM output is consumed ONLY as Qlib expression-DSL strings and
    fed to Qlib's expression parser (``factor_export``). We NEVER ``eval``/``exec``
    model-generated code, and nothing touches the network or the filesystem
    outside the run's ``out`` dir. (Full RD-Agent's Co-STEER writes & runs Python;
    that stays out until it runs in a real container — this shell won't launch it.)
  * **Honest N across rounds.** Each round's attempted-count is accumulated; the
    combined manifest reports the CUMULATIVE attempted N — the number the EVO-149
    deflated-Sharpe gate must use as ``n_trials``. A miner that proposes 40
    expressions over 5 rounds contributes N=40 (plus prior human trials), never
    just its survivors.

``llm_fn`` is injected: ``llm_fn(prompt) -> (text, in_tokens, out_tokens)`` where
``text`` is a newline-separated list of ``name = <qlib expression>``. A mock is
provided so the skeleton is runnable and testable with zero spend and no network.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .rdagent_budget import BudgetGuard, guarded_call
from . import factor_export as fx

LLMFn = Callable[[str], tuple[str, int, int]]

_LINE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s*$")


def parse_factor_proposals(text: str) -> dict[str, str]:
    """``name = expr`` lines -> mapping. Ignores blanks / comments / junk.

    This is the ONLY thing done with LLM output: parse to (name, expr-string).
    The expr string is later handed to Qlib's parser, not to exec.
    """
    out: dict[str, str] = {}
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        m = _LINE.match(raw)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def mock_llm(prompt: str) -> tuple[str, int, int]:
    """Zero-cost stand-in miner. Returns a small, deterministic expr batch."""
    batch = (
        "mrev2 = Ref($close,2)/$close-1\n"
        "mom10 = $close/Ref($close,10)-1\n"
        "vspike = $volume/Mean($volume,20)\n"
        "hlrange5 = Mean(($high-$low)/$close,5)\n"
    )
    return batch, 800, 120   # pretend token counts


def run_trial(
    store: Path,
    out: Path,
    *,
    guard: BudgetGuard,
    llm_fn: LLMFn = mock_llm,
    model: str = "mock",
    rounds: int = 3,
    start: str = "2015-01-01",
    end: str = "2024-12-31",
    repo_root: Path | None = None,
    prior_n_trials: int = 0,
) -> dict:
    """Run a small capped mining loop; return a combined honest-N manifest."""
    out = Path(out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    repo_root = repo_root or Path.cwd()

    cumulative_attempted = 0
    round_manifests = []
    stopped_reason = "completed"

    for r in range(rounds):
        prompt = (f"Round {r}: propose 3-6 daily cross-sectional factor "
                  f"expressions in Qlib DSL as `name = expr` lines.")
        try:
            text = guarded_call(
                guard, model=model, est_in_tokens=1200, est_out_tokens=400,
                label=f"rdagent_trial/round{r}", fn=lambda: llm_fn(prompt))
        except Exception as e:            # BudgetExceeded (or any call failure) stops the loop
            stopped_reason = f"budget_or_call_stop:{type(e).__name__}"
            break

        proposals = parse_factor_proposals(text)
        if not proposals:
            round_manifests.append({"round": r, "n_proposed": 0, "note": "no parseable proposals"})
            continue

        man = fx.export(store, out / f"round{r}", start=start, end=end,
                        factor_set="core", extra=proposals, repo_root=repo_root)
        # subtract the always-present 'core' seed set so we count only THIS round's
        # newly-proposed expressions toward the miner's honest N
        proposed_n = len(proposals)
        cumulative_attempted += proposed_n
        round_manifests.append({
            "round": r,
            "n_proposed": proposed_n,
            "n_exported_incl_core": man["n_exported"],
            "discarded": man["discarded"],
            "out": str(out / f"round{r}"),
        })

    combined = {
        "schema": "qlib_gen.rdagent_skeleton/1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "small_scale_trial (full RD-Agent integration deferred)",
        "rounds_run": len(round_manifests),
        "stopped_reason": stopped_reason,
        # ---- budget accounting (mirror of the isolated ledger) ----
        "llm_cap_usd": guard.cap_usd,
        "llm_spent_usd": round(guard.spent_usd, 6),
        "llm_calls": guard.n_calls,
        "ledger": str(guard.ledger_path),
        # ---- honest N ----
        "prior_n_trials": prior_n_trials,
        "miner_attempted_this_run": cumulative_attempted,
        "cumulative_n_trials": prior_n_trials + cumulative_attempted,
        "n_trials_contract": ("feed cumulative_n_trials as deflated_sharpe_ratio "
                              "n_trials; the gate (qlab.events) is the only verdict"),
        "rounds": round_manifests,
    }
    (out / "trial_manifest.json").write_text(json.dumps(combined, indent=2))
    return combined
