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
  * **Honest N across rounds — fail-closed, not hand-passed.** Every round is
    registered into the shared, persisted ``research.gate.trial_ledger.TrialLedger``
    via ``register_run(n_trials_total=<all attempted incl. discarded>, ...)``,
    which *raises* ``HonestyError`` if the declared N is missing or smaller than
    the number actually evaluated. The gate's ``n_trials`` is then read back from
    ``ledger.cumulative_n()`` — the cross-round, cross-session running total
    (miner rounds + the ~7 prior human trials already in the ledger). There is no
    ``prior_n_trials=0`` default to forget: the count is enforced the same way the
    LLM budget is (see ``rdagent_budget``), so N can't be silently under-counted
    while money is fail-closed — the exact seam 工部尚书 flagged.

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


def _load_trial_ledger():
    """Import the gate's TrialLedger, adding the repo root to sys.path if needed.

    ``research/gate`` lives at the repo root (sibling of ``qlab/``); when the
    generator is run with ``PYTHONPATH=qlab`` the root is not importable yet, so
    we add it. Kept lazy so importing this module never requires the gate tree.
    """
    try:
        from research.gate.trial_ledger import TrialLedger, HonestyError
    except ModuleNotFoundError:
        import sys
        root = Path(__file__).resolve().parents[3]   # .../<repo>/qlab/tools/qlib_gen -> <repo>
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from research.gate.trial_ledger import TrialLedger, HonestyError
    return TrialLedger, HonestyError


def open_ledger(path: str | Path):
    """Construct a persisted TrialLedger at ``path`` (the honest-N台账)."""
    TrialLedger, _ = _load_trial_ledger()
    return TrialLedger(str(Path(path).expanduser()))


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
    ledger,                      # research.gate.trial_ledger.TrialLedger — REQUIRED, no fail-open default
    llm_fn: LLMFn = mock_llm,
    model: str = "mock",
    rounds: int = 3,
    start: str = "2015-01-01",
    end: str = "2024-12-31",
    repo_root: Path | None = None,
    run_id_prefix: str = "rdagent",
) -> dict:
    """Run a small capped mining loop; return a combined honest-N manifest.

    ``ledger`` is a persisted ``TrialLedger`` (use ``open_ledger(path)``). It is
    REQUIRED — there is no ``prior_n_trials=0`` default to under-count N. Each
    round is registered fail-closed via ``ledger.register_run(...)``; the gate's
    ``n_trials`` is read back as ``ledger.cumulative_n()`` (cross-round,
    cross-session, includes the prior human trials already in the台账).
    """
    if ledger is None:
        raise ValueError("run_trial requires a TrialLedger (open_ledger(path)); "
                         "N must be counted fail-closed, never defaulted to 0")
    out = Path(out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    repo_root = repo_root or Path.cwd()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")

    miner_attempted_this_run = 0
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
        # This round's honest N = every proposal attempted (incl. discarded);
        # n_evaluated = the proposals that actually survived to the gate.
        proposed_n = len(proposals)
        discarded_proposals = [k for k in proposals if k in man["discarded"]]
        n_evaluated = proposed_n - len(discarded_proposals)

        # Register fail-closed. HonestyError here is a real stop, not swallowed.
        rec = ledger.register_run(
            run_id=f"{run_id_prefix}/{stamp}/round{r}",
            source="rd-agent",
            n_trials_total=proposed_n,        # <- all attempted, the honest N
            n_evaluated=n_evaluated,
            note=f"qlib_gen small-scale trial; discarded={discarded_proposals}",
        )
        miner_attempted_this_run += rec.n_trials_total
        round_manifests.append({
            "round": r,
            "n_proposed": proposed_n,
            "n_evaluated": n_evaluated,
            "discarded": man["discarded"],
            "ledger_run_id": rec.run_id,
            "out": str(out / f"round{r}"),
        })

    combined = {
        "schema": "qlib_gen.rdagent_skeleton/2",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "small_scale_trial (full RD-Agent integration deferred)",
        "rounds_run": len(round_manifests),
        "stopped_reason": stopped_reason,
        # ---- budget accounting (mirror of the isolated ledger) ----
        "llm_cap_usd": guard.cap_usd,
        "llm_spent_usd": round(guard.spent_usd, 6),
        "llm_calls": guard.n_calls,
        "budget_ledger": str(guard.ledger_path),
        # ---- honest N: authoritative source is the TrialLedger, not this file ----
        "trial_ledger": str(getattr(ledger, "path", "") or ""),
        "miner_attempted_this_run": miner_attempted_this_run,
        "cumulative_n_trials": ledger.cumulative_n(),   # <- feed THIS to the gate
        "n_trials_contract": ("gate n_trials MUST be ledger.cumulative_n() (fail-closed, "
                              "cross-session); NEVER a per-round count. Verdict = qlab.events only."),
        "rounds": round_manifests,
    }
    (out / "trial_manifest.json").write_text(json.dumps(combined, indent=2))
    return combined
