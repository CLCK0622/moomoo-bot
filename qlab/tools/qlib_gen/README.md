# `tools/qlib_gen` — Qlib factor generator + RD-Agent trial shell (工部 · 都水)

Infrastructure for using **Qlib as a factor *generator*** and running **small,
budget-capped RD-Agent-style trials** — wired to the *existing* EVO-149 gate,
not a second one. Built per 工部尚书's split (a): tooling/pipeline/accounting.

## The one rule everything here obeys

> **Qlib (and any miner) generates candidates. It never decides pass/fail.**
> The only verdict comes from `qlab.events` (EVO-149: `gates.py`,
> `multiple_testing.py`, `significance.py`, `metrics.py`). Qlib's own backtest
> is **never** an acceptance criterion. Generator and validator are separate on
> purpose — that separation is what keeps machine-scale search from
> industrialising overfitting.

## What's here

| file | role |
|------|------|
| `build_qlib_data.py` | committed adjusted daily parquet (`data/daily_full/*`) → Qlib `.bin` store |
| `factor_export.py` | Qlib expression engine → tidy `factors.parquet` **+ honest-N `manifest.json`** |
| `rdagent_budget.py` | **hard** LLM spend cap (fail-closed) + isolated JSONL ledger |
| `rdagent_skeleton.py` | sandboxed, budget-capped mining loop (full RD-Agent deferred) |
| `vendor/dump_bin.py` | official Qlib dumper, pinned `v0.9.7` (see `vendor/PROVENANCE.md`) |
| `ALPHAAGENT_REGEX_METHODOLOGY.md` | originality/complexity regex discipline — for 营缮, doc-only (AlphaAgent NOT integrated) |
| `bootstrap_env.sh` | recreate the persistent Python + venv from scratch |
| `../../tests/test_qlib_gen.py` | end-to-end + budget + honest-N tests |

## Environment (persistent, not task-scoped)

Qlib is used repeatedly, so its interpreter lives in the **persistent user
layer**, not a throwaway workdir:

- `uv` 0.12 → `~/.local/bin/uv` (same layer as Node/pnpm).
- CPython 3.12.13 managed by uv → `~/.local/share/uv/python/…` (persistent cache).
- Generator venv → `~/.venvs/qlab-py312` (persistent; `pyqlib==0.9.7`, numpy 1.26.4,
  pandas 2.1.4 — the exact numpy/pandas the qlab lock already uses, so the factor
  values match the harness).
- CPU-only: no torch pulled. Daily factors are cheap.

Recreate anything with `bash tools/qlib_gen/bootstrap_env.sh`. Frozen deps:
`requirements-qlib-lock.txt`.

### Host gotcha (baked into the code)

Qlib **must** init with `kernels=1` on this macOS host — its multi-process
feature computation deadlocks under the `spawn` start method. `factor_export`
hardcodes this; don't "optimise" it back to multi-kernel.

## Run it

```bash
VP=~/.venvs/qlab-py312/bin/python
export PYTHONPATH=$PWD          # from the qlab/ root

# 1) build the binary store (derived, gitignored). --limit N for a smoke run.
$VP -m tools.qlib_gen.build_qlib_data --src data/daily_full --out data/qlib_store

# 2) export a factor family + honest-N manifest
$VP -m tools.qlib_gen.factor_export --store data/qlib_store/bin \
    --out reports/qlib_factors --start 2010-01-01 --end 2024-12-31

# 3) tests
$VP -m pytest tests/test_qlib_gen.py -q
```

`factors.parquet` schema: `datetime, instrument, factor, value` — the handoff
into `qlab.swing.*` (营缮's strategy/eval harness) and the gate.

## Honest test-count (N) — the spine, fail-closed

`manifest.json.n_expressions_attempted` counts **every** expression tried this
run, *including the ones discarded* for erroring or being all-NaN. But that is a
**per-run** count — it is **not** the number you hand to the gate.

The gate `N` is authoritative from **`research.gate.trial_ledger.TrialLedger`**
(brought into this same tree by the evo-162 ↔ PR#1 merge). It is fail-closed the
same way the LLM budget is:

- `TrialLedger.register_run(n_trials_total=<all attempted incl. discarded>, …)`
  **raises `HonestyError`** if the declared N is missing or smaller than the
  number actually evaluated — a batch cannot register only its survivors.
- `TrialLedger.cumulative_n()` is the cross-run, cross-session running total
  (miner rounds **+** the ~7 prior human trials already in the台账). **That**
  is the `n_trials` for `deflated_sharpe_ratio` / `haircut_family`.
- Never feed the per-run `n_expressions_attempted` raw — doing so slackens the
  haircut by orders of magnitude and lets noise factors pass. (This was a real
  fail-open seam — `run_trial` used to take `prior_n_trials=0`; now the ledger
  is a **required** argument and there is no default to forget.)
- A factor set delivered **without** registering into the ledger is **not
  eligible for evaluation** (户部/首辅 red line).

Wiring: `rdagent_skeleton.run_trial(..., ledger=open_ledger(path))` registers
each round and reports `cumulative_n_trials = ledger.cumulative_n()`.
`factor_export.export(..., ledger=…)` does the same for standalone runs.

## RD-Agent status: small-scale shell only, full integration deferred

`rdagent_skeleton.py` is the **safe shell**, not the real package:

- **Hard budget.** Every LLM call goes through `rdagent_budget.guarded_call`; it
  raises `BudgetExceeded` *before* the call when it would breach `cap_usd`
  (env `RDAGENT_LLM_CAP_USD`). Not a warning — the call never fires. Spend is
  resumed from the ledger across restarts, so a relaunch can't reset the cap.
- **Isolated accounting.** One JSONL line per call in
  `reports/rdagent_ledger/…` — auditable, separate from other artifacts.
- **Sandbox.** LLM output is consumed **only** as Qlib expression-DSL strings
  fed to Qlib's parser. We never `eval`/`exec` model-generated code and never
  touch the network or paths outside the run dir. Full RD-Agent's Co-STEER
  writes & runs Python — that only turns on inside a real container, later.

## AlphaAgent: not integrated

Per the split, AlphaAgent is **not** wired in. Its useful idea — regex-style
originality/complexity constraints to suppress overfit/duplicate factors — is
written up in `ALPHAAGENT_REGEX_METHODOLOGY.md` for 营缮 to apply in the
hypothesis→factor stage. No code dependency.
