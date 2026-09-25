"""factor_export — Qlib expression engine  ->  tidy factor parquet + honest-N manifest.

This is the **generator handoff**. Qlib is used ONLY to evaluate factor
expressions (and, optionally, the Alpha158/Alpha360 field sets) over the store
built by ``build_qlib_data.py``. It writes:

  1. ``factors.parquet`` — tidy long ``(datetime, instrument, factor, value)``
     for the strategy/eval harness (``qlab.swing.*``) and the gate to consume.
  2. ``manifest.json`` — the **honest test-count ledger**: every expression
     *attempted* this round (``n_expressions_attempted``), including the ones
     discarded for erroring or being all-NaN. This is the spine the EVO-149
     multiple-testing gate needs: ``deflated_sharpe_ratio(..., n_trials=N)`` and
     ``haircut_family`` are only honest if N counts the *discarded* trials too.
     Survivorship-biased factor dumps (only the winners) are exactly the failure
     mode 户部/首辅 flagged: **no true N -> not eligible for evaluation.**

Hard boundaries (do not remove):
  * Qlib NEVER decides pass/fail. Its numbers are inputs to the frozen gate in
    ``qlab.events`` — never an acceptance criterion.
  * ``kernels=1`` is REQUIRED on this host: Qlib's multi-process feature
    computation deadlocks under macOS ``spawn``. Single-kernel is correct and
    fast enough on CPU for daily factors.
  * CPU-only, offline (reads the local ``.bin`` store, no network).

Usage::

    python -m tools.qlib_gen.factor_export \
        --store data/qlib_store/bin --out reports/qlib_factors \
        --start 2010-01-01 --end 2024-12-31 --factor-set core
"""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Factor expression sets. Each entry: name -> Qlib expression over adjusted OHLCV.
# These are DEMO/seed expressions to prove the engine + honest-N plumbing. The
# real hypothesis-driven sets are 营缮's to author in the hypothesis->factor
# stage (see ALPHAAGENT_REGEX_METHODOLOGY.md for the originality/complexity
# discipline to apply when a generator proposes new ones).
# ---------------------------------------------------------------------------
FACTOR_SETS: dict[str, dict[str, str]] = {
    "core": {
        "rev1": "Ref($close,1)/$close-1",
        "mom5": "$close/Ref($close,5)-1",
        "mom21": "$close/Ref($close,21)-1",
        "mom252_21": "Ref($close,21)/Ref($close,252)-1",   # 12-1 momentum
        "volratio": "Mean($volume,5)/Mean($volume,20)",
        "range": "($high-$low)/$close",
        "rv20": "Std($close/Ref($close,1)-1,20)",
        "gap": "$open/Ref($close,1)-1",
    },
}


def _git_commit(repo_root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unknown"


def _init_qlib(store: Path) -> None:
    import qlib
    # kernels=1 is mandatory here (see module docstring). Caches off = pure
    # recompute, so a factor value never comes from a stale cache.
    qlib.init(provider_uri=str(store), region="us",
              kernels=1, expression_cache=None, dataset_cache=None)


def export(store: Path, out: Path, *, start: str, end: str,
           factor_set: str = "core",
           extra: dict[str, str] | None = None,
           repo_root: Path | None = None,
           ledger=None, run_id: str | None = None, source: str = "qlib",
           candidate_id: str | None = None, supersedes: str | None = None,
           trial_sharpes=None) -> dict:
    """Evaluate a factor family, write tidy parquet + honest-N manifest.

    If ``ledger`` (a ``research.gate.trial_ledger.TrialLedger``) is given, this
    run is registered into it fail-closed via ``register_run`` — the ONLY honest
    way to feed the gate. The gate then reads ``ledger.cumulative_n()``; this
    manifest's ``n_expressions_attempted`` is a *per-run* count, never the gate N.
    """
    from qlib.data import D

    store = store.expanduser().resolve()
    out = out.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    repo_root = repo_root or Path.cwd()

    exprs = dict(FACTOR_SETS[factor_set])
    if extra:
        exprs.update(extra)

    _init_qlib(store)
    insts = D.list_instruments(D.instruments("all"), as_list=True)

    attempted: list[str] = []           # honest N: everything we tried
    exported: dict[str, str] = {}       # name -> expr that survived
    discarded: dict[str, str] = {}      # name -> reason
    frames = []

    for name, expr in exprs.items():
        attempted.append(name)
        try:
            f = D.features(insts, [expr], start_time=start, end_time=end,
                           freq="day")
        except Exception as e:  # malformed expr / engine error -> discard, still counts in N
            discarded[name] = f"error:{type(e).__name__}:{e}"[:200]
            continue
        s = f.iloc[:, 0]
        if s.notna().sum() == 0:
            discarded[name] = "all_nan"
            continue
        exported[name] = expr
        frames.append(s.rename(name))

    if frames:
        wide = pd.concat(frames, axis=1)
        tidy = (wide.stack(dropna=True)
                    .rename("value").reset_index())
        tidy.columns = ["instrument", "datetime", "factor", "value"] \
            if list(tidy.columns[:2]) == ["instrument", "datetime"] \
            else ["datetime", "instrument", "factor", "value"]
        tidy = tidy[["datetime", "instrument", "factor", "value"]]
        tidy.to_parquet(out / "factors.parquet", index=False)
        n_rows = len(tidy)
    else:
        n_rows = 0

    manifest = {
        "schema": "qlib_gen.factor_export/1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "generator": "qlib",
        "store": str(store),
        "git_commit": _git_commit(repo_root),
        "universe": insts,
        "n_instruments": len(insts),
        "window": {"start": start, "end": end},
        "factor_set": factor_set,
        # ---- honest test-count for THIS run (NOT the gate N) ----
        # n_expressions_attempted is a PER-RUN count (all attempted incl. discarded).
        # It is NOT the value to pass to deflated_sharpe_ratio(n_trials=...). The
        # gate N is the cross-run cumulative from TrialLedger.cumulative_n(); pass
        # a `ledger=` to register this run into it fail-closed (see below).
        "n_expressions_attempted": len(attempted),   # per-run; register into TrialLedger, don't feed raw
        "n_exported": len(exported),
        "n_discarded": len(discarded),
        "attempted": attempted,
        "exported": exported,
        "discarded": discarded,
        "n_rows": n_rows,
        # ---- boundary reminders, machine-readable ----
        "acceptance_authority": "qlab.events (EVO-149) ONLY — Qlib output is never a verdict",
        "n_trials_contract": ("n_expressions_attempted is a PER-RUN count. The gate's "
                              "deflated_sharpe_ratio n_trials MUST come from "
                              "research.gate.trial_ledger.TrialLedger.cumulative_n() "
                              "(cross-run, cross-session, incl. discarded + prior human "
                              "trials). Pass ledger= to register this run fail-closed."),
    }

    # Fail-closed registration into the shared honest-N台账 (optional but the
    # only sanctioned path to the gate). register_run raises HonestyError if the
    # declared N is missing / < evaluated — surfaced, not swallowed.
    if ledger is not None:
        # candidate_id / supersedes 必须透传（工部 2026-08-06）：此前这里不传 candidate_id，
        # 于是经 export 登记的条目一律 candidate_id=None —— 重冻护栏正是按 candidate_id 找
        # prior 的，为 None 就永远匹配不到 ⇒ 同一候选换 prereg commit 重登**不会**触发
        # RefreezeError、静默追加、同批试验计两遍（N 虚高 ⇒ DSR 门抬高 ⇒ 误杀真 alpha）。
        # 营缮当时的绕法是「不传 ledger 给 export、由 runner 显式登记」，对但治标；这里补上透传。
        rec = ledger.register_run(
            run_id=run_id or f"{source}/{start}_{end}/{factor_set}",
            source=source,
            n_trials_total=len(attempted),
            n_evaluated=len(exported),
            trial_sharpes=trial_sharpes,
            candidate_id=candidate_id,
            supersedes=supersedes,
            note=f"factor_export {factor_set}; discarded={sorted(discarded)}",
        )
        manifest["ledger_run_id"] = rec.run_id
        manifest["cumulative_n_trials"] = ledger.cumulative_n()   # <- gate uses THIS
        manifest["trial_ledger"] = str(getattr(ledger, "path", "") or "")

    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def _cli() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--store", default="data/qlib_store/bin", type=Path)
    ap.add_argument("--out", default="reports/qlib_factors", type=Path)
    ap.add_argument("--start", default="2010-01-01")
    ap.add_argument("--end", default="2024-12-31")
    ap.add_argument("--factor-set", default="core", choices=sorted(FACTOR_SETS))
    args = ap.parse_args()
    man = export(args.store, args.out, start=args.start, end=args.end,
                 factor_set=args.factor_set)
    print(f"[factor_export] attempted N={man['n_expressions_attempted']} "
          f"exported={man['n_exported']} discarded={man['n_discarded']} "
          f"rows={man['n_rows']} -> {args.out}")


if __name__ == "__main__":
    _cli()
