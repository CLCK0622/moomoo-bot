# EVO-884 dynamic-factor gate mechanisms

Offline qlab tools for EVO-881. No broker, account, credential, scheduler, order or
network integration. No strategy backtest is run by this package or its harness.
The old paper executor and shared `research/gate/state` remain untouched.

EVO-883 **v0.1 is wired as a draft**, with raw attachment SHA256
`2e65c77849b936d44c864b056be134e030ddf7f27e746072b70fffe631acf69b`.
It is not a strategy freeze or authorization to run history/shadow sampling.
All official v0 reports include version, raw SHA and draft status and remain
`certifiable: false`. Full current-project N and independent comparable V still
need their own receipts; a high diagnostic DSR cannot bypass these limits.

## Run and verify

From the repository root, using Python 3.9+ (stdlib tools/harness; pytest for tests):

```bash
PYTHONPATH=qlab:. python -m qlab.dynamic_factor.harness --workdir ./harness-run-1
PYTHONPATH=qlab:. python -m pytest qlab/tests/dynamic_factor qlab/tests/test_qlib_gen.py -q
ruff check qlab/qlab/dynamic_factor qlab/tests/dynamic_factor
ruff format --check qlab/qlab/dynamic_factor qlab/tests/dynamic_factor
```

The harness needs an empty directory and preserves prior evidence. Repeat into a
second empty directory to get identical JSON bytes on the same interpreter. It
runs the original 9 case IDs plus `data.benchmark_calendar_gap`, with network
blocked and no current-date, random, live-data or model-call inputs. Output pins
Python version, all source modules and frozen input bytes. Ruff used: 0.14.3.

Every report has `ok`, `certifiable`, input/source SHA256, complete source-file
fingerprints, assumptions, missing inputs, reasons, metrics and availability.
Unknown numerical values are null; zero is retained as zero. Input SHA covers
canonical semantic JSON plus exact consumed-file hashes; CLI additionally reports
`input_file_sha256`. Source SHA covers the full package and injected callback
modules, including helpers/constants. `ok` is tool validation/calculation status;
certifiability and numerical threshold passing are separate fields.

## Pinned conventions and historical seed

`load_conventions()` verifies the v0.1 raw SHA and its bound date table, common
calendar, seed SHA, eight run IDs/counts, formula thresholds, scales, label offsets
and fold widths. Conflicting or unsupported conventions raise `ConventionConflict`.
The JSON is never evaluated as Python: only a restricted arithmetic AST with
explicit math functions is accepted for the published DSR expressions. Returned
policy dictionaries are copies, so callers cannot silently mutate pinned bytes.

`AttemptLedger.from_conventions(path, policy)` imports exactly the seed at commit
`e51f8023bd0c0b6cf45c5badbc9db2c45a3a14e9`,
`research/gate/state/trial_ledger.jsonl`, SHA256
`76ece03d62628a2ca2f0cb089103deaa26584ae9522fdde101df782a738a8f0b`.
Its 8 rows / 47 attempts are stored in genesis as provenance, **not complete N**:

- `cumulative_n: null`, `n_complete: false`;
- `cumulative_n_lower_bound: 47 + local_counted_n`;
- `ledger_history_incomplete`, so no certification;
- old raw strategy Sharpe values and scalar variance estimates never feed active-return V.

A bare `AttemptLedger(path)` still defaults to unknown history and
`authority_source: null`, yielding `ledger_authority_unset`. Genesis is immutable;
reopening with a different genesis fails. A later full reconciliation needs a
separately reviewed migration, never a reset or silent history replacement.

`local_attempts_n` counts begin records; `local_counted_n` follows v0 proposal rules.
Declared family members count even if a later child registration is interrupted;
a fold invocation with a declared family is orchestration metadata, while a failed
pre-family discovery is a conservatively counted structural attempt.

Attempts are transactional SQLite events inserted **before execution**. All
failed/NaN/repeated/interrupted begins remain counted. Same ID/same input is an
idempotent delivery retry; a new performance attempt gets a new ID. Supersedes is
only metadata and never deletes an earlier attempt. NaN/Inf Sharpe observations
retain status/reason and null rather than zero. Family declarations and observed
self-reported N high-water marks are metadata events, not extra attempts. A lower
self-report after restart cannot reduce the gate N. Readout exports the full
logical snapshot plus `n_ledger_hash`, independent of SQLite layout and filename.
Preserve the DB and exported hash. This is a local-filesystem ledger, not a
multi-host distributed database or protection against rewriting every anchor.

## DSR / V numerical interface

```python
from qlab.dynamic_factor.conventions import load_conventions
from qlab.dynamic_factor.ledger import AttemptLedger
from qlab.dynamic_factor.statistics import dsr_eval

policy = load_conventions()
ledger = AttemptLedger.from_conventions("./dynamic-factor.sqlite", policy)
# Before evaluating a run, declare all its family IDs (16 recipes + one meta).
ledger.declare_family("run", all_attempt_ids,
                      basis=policy.document["N"]["DSR_SR_basis"])
# Each member is begun before evaluation, then finished with a Sharpe observation:
ledger.begin(attempt_id, proposal, context={"run_id": "run"})
ledger.finish(attempt_id, "success", sharpe=observed_sr,
              details={"sr_basis": policy.document["N"]["DSR_SR_basis"],
                       "sharpe_scale": "daily", "scale_conversions": 0})
report = dsr_eval({"run_id": "run", "self_report_n": reported_total,
                   "returns": daily_active_returns,
                   "return_basis": policy.document["N"]["DSR_SR_basis"],
                   "return_scale": "daily"}, ledger, conventions=policy)
```

Independent families must have an explicit source reference/SHA and the same
basis, with all members and observations present. Own-run membership is sealed
before performance; added or missing attempts cannot be hidden by choosing a
winner subset. The independent union excludes the entire current run. V is the
max of complete-family and complete-independent-union sample variances, with no
weighted scalar fallback. Missing/failed missing SR, NaN, insufficient independent
records or uncomparable basis yields unavailable V/DSR. Source declarations are
caller assertions, not an independent audit.

DSR expressions, gamma, threshold, sample ddof, population skew/ordinary kurtosis,
and annual/daily conversion factor come from v0.1. Annual observations divide by
sqrt(periods) exactly once before computing V; repeated conversion or mixed units
is refused. Candidate SR/moments are computed from supplied daily active returns,
not a competing scalar SR. Scalar V inputs are rejected. N uses the nondecreasing
maximum of observed lower-bound history and self-report. A numerical DSR using
incomplete N is explicitly **diagnostic**: `diagnostic_passed` may be true while
`passed` and `certifiable` remain false. Missing policy still gives `prereg_missing`.
The earlier generic injected-plugin seam remains for engine tests; the official
EVO-883 route is the `conventions` adapter above.

The fixed synthetic numerical fixture gives family V=0.00255, independent V=0.0102,
SR0=0.24799876432939677, daily SR=0.2903200204700225, ordinary population kurtosis
1.7314285714285709 and DSR=0.6265006201845557. N=81 is only 47+34 observed attempts.
Annual/daily inputs match; missing SR and scale errors are refused.

## Fold and data rules

`policy.fold_manifest()` reads the author-supplied 3,191-day complete common suffix
and 77-fold date table, verifying the formulas from v0.1. It retains each original
`history_end`, the 21-session gap and the prescribed test dates. Eligible training
signals are purged so their label entry/exit and the entire 20-session template
path mature **inside train**, not merely before test. Next-open entry means the
20-session path endpoint is signal+21; the primary 10-session label exits at
signal+11. These offsets are derived from the JSON. `train_end` is the purged
eligible-signal endpoint, while `history_end` preserves the original train bound.
No cutoffs or gap lengths can be overridden in a bound manifest.

`run_walk_forward(..., conventions=policy)` validates that binding, then creates a
new miner, fitter and model per fold. The miner receives immutable train rows;
all proposals (including duplicates) and the meta attempt are logged before fit.
Selection/scaling/refitting occur inside the train-only fitter. A FitReceipt must
match exact training dates, train SHA and proposal SHA. Predict receives immutable
feature-only rows with no test labels. Full-history receipts, reused instances,
unmatured labels/template paths and consumed run/fold IDs are rejected. Failed
mining invocations are conservatively recorded too. This is data-flow checking
for trusted adapters, **not an OS sandbox** against malicious adapters reading
other files or fabricating receipts. It does not authorize a historical run.

`wf_manifest_check(manifest, conventions=policy)` requires the pinned common
calendar and benchmark/portfolio date alignment before daily metrics. A caller
cannot hide holes by intersecting away the same missing date from every series.
The tool checks own-span omissions, nontrading bars, duplicate/unsorted dates,
nonpositive/nonfinite prices and jump/reversal patterns. It never repairs prices,
shifts dates, forward-fills or silently aligns rows. Beta/IR remain null here.

v0.1 supplies no jump threshold; callers must supply `jump_reversal_policy` in the
manifest (otherwise refusal). Fields are `min_abs_jump`, `max_abs_roundtrip`, and
`max_observation_gap_calendar_days`. The explicit harness QA inputs are 0.15, 0.03
and 5, not strategy acceptance parameters. Opposite-sign adjacent-observation
moves with a large first jump and near-restored price are flagged independently
of calendar membership. Observed moves spanning missing/off-calendar sessions are
labelled as such and are never treated as daily returns.

The updated fixed SPY case uses exact frozen parquet prices in three windows:
2011-07-04 bad price/rebound, 2012-04-06 and 2012-05-28 nontrading bars, and the
missing 2012-05-29 session. Date-level reason codes distinguish
`data.jump_reversal`, `data.nontrading_bar` and `data.calendar_gap`. A separate
trading-day variant proves the detector does not depend on holidays. Inputs retain
SPY/AAPL source SHAs and the VTI QA check SHA. AAPL is still a local, unverified
exchange-calendar assumption, exactly as v0.1 discloses.

## Fees and CLI

Fee rates stay in unmodified EVO-882 x1/x2 files. The separate date mapping switches
TAF on sell date at 2027-01-01; earlier history requires the explicit
`research_restored` assumption. A bound v0 call verifies the raw fee-file SHA and
applies v0.1's per-order floor independently to each scenario leg. The cost mapping
business receipt and actual account eligibility remain unverified. Cash bid/ask
P&L already contains x1 friction; x2 stress only adds incremental friction. The
scenario gate floor is not an observed cash fee. No actual shadow portfolio or
partial-fill cost accounting is implemented in this D3–5 tool.

```bash
PYTHONPATH=qlab:. python -m qlab.dynamic_factor dsr_eval \
  --input dsr-request.json --ledger ./dynamic-factor.sqlite \
  --conventions qlab/qlab/dynamic_factor/fixtures/conventions-v0.1.json
PYTHONPATH=qlab:. python -m qlab.dynamic_factor wf_manifest_check \
  --input manifest.json \
  --conventions qlab/qlab/dynamic_factor/fixtures/conventions-v0.1.json
```

CLI DSR input wraps the request under `metrics`. `--conventions-sha256` can specify
an expected raw SHA; default matches the frozen provenance file. CLI never imports
code named in JSON. It prints JSON and exits 2 on refusal, 0 on an ok calculation.
`--out-dir` writes immutable content-addressed reports, refusing conflicting bytes.
`shadow_readout`, `IntentJournal` and `decay_check` remain offline receipt/extension
seams, not the D6–8 shadow ledger or an order simulator. Full input provenance is
in `fixtures/provenance.json`; original attached files remain byte-for-byte intact.
