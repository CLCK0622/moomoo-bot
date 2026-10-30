# EVO-884 dynamic-factor gate mechanisms

This package implements the formula-independent part of EVO-881 inside the existing
`qlab` skeleton. It has no broker, account, credential, network, order or scheduler
integration. It does not run a historical strategy backtest. The old `llm_paper`
executor and `research/gate/state` are not read or written.

EVO-883's DSR/N/V definitions and the authoritative ledger genesis have **not been
delivered**. No statistical formula or V estimator is supplied here. All bundled
fixtures/harness cases are non-certifying. A later reviewed adapter must bind the
official preregistration version/SHA, ledger-history policy, DSR and independent V
estimator. Missing preregistration returns DSR/V/Sharpe `null` with `prereg_missing`;
missing genesis authority returns `ledger_authority_unset`. Completing the mechanism
tests does not remove either dependency or authorize forward shadow sampling.

## Run offline

From the repo root, using Python 3.9+ (stdlib only for tools/harness):

```bash
PYTHONPATH=qlab:. python -m qlab.dynamic_factor.harness --workdir ./harness-run-1
PYTHONPATH=qlab:. python -m pytest qlab/tests/dynamic_factor qlab/tests/test_qlib_gen.py -q
ruff check qlab/qlab/dynamic_factor qlab/tests/dynamic_factor
```

The harness directory must be empty. Prior evidence is preserved; repeat into a
second fresh directory to obtain the same JSON bytes on the same interpreter.
All 9 original IDs plus `data.benchmark_calendar_gap` execute real tool calls.
Network access is blocked; inputs have no current-date, RNG, live-data or paid-model
dependency. Output includes Python version, source and fixture SHA256s. The SPY
case uses the real 2011-07-18..27 missing-date interval from EVO-882's addendum;
its prices are synthetic constants, explicitly labelled as such. It tests refusal
of daily beta/IR, not benchmark returns. Formula-dependent assertions only check
refusal/nulls until EVO-883 arrives.

The existing project Python environment already supplies pytest. No extra runtime
dependency is added. Validation used pytest 9.1.1 and Ruff 0.14.3.

## Tool contract and CLI

Every report has `schema`, `tool`, `ok`, `certifiable`, `input_sha256`,
`source_sha256`, `source_files`, `assumptions`, `missing_inputs`, `reasons`,
`metrics`, `metric_availability`, and `artifacts`. SHA256s are lower-case hex.
Input SHA covers canonical semantic JSON; file consumers additionally hash exact
input bytes. Source SHA covers all package Python files and, for fit/DSR callbacks,
the full adapter modules (helpers/constants included). Unknown metrics are JSON
`null`; valid numerical zero is retained. `ok` means that tool's checks/calculation
completed without refusal. `certifiable` is eligibility of statistical evidence,
not evidence that the strategy passed or that an action is authorized. The fee,
manifest and receipt tools never certify a strategy.

```bash
PYTHONPATH=qlab:. python -m qlab.dynamic_factor fee_frontier \
  --input ticket.json --params qlab/qlab/dynamic_factor/fixtures/fee_params_x1.json
PYTHONPATH=qlab:. python -m qlab.dynamic_factor wf_manifest_check --input manifest.json
PYTHONPATH=qlab:. python -m qlab.dynamic_factor prereg_check --input prereg-request.json
PYTHONPATH=qlab:. python -m qlab.dynamic_factor dsr_eval \
  --input dsr-request.json --ledger ./dynamic-factor.sqlite
```

CLI prints JSON and exits 2 for refusal, 0 for an `ok` result. `--out-dir` writes
content-addressed immutable report files and refuses a conflicting existing file.
It adds the raw `input_file_sha256`. The optional `--genesis` selects an explicit
genesis JSON when opening a ledger; it cannot change an existing genesis. The CLI
never imports code named in input JSON. Fold and formula adapters use Python APIs.

### Attempt ledger

```python
from qlab.dynamic_factor.ledger import AttemptLedger

ledger = AttemptLedger("./dynamic-factor.sqlite")
ledger.begin("run/fold/proposal/0", {"expression": "DSL string", "seed": 7})
try:
    # External trusted caller does its work here.
    ledger.finish("run/fold/proposal/0", "success", sharpe=None)
except Exception as exc:
    ledger.finish("run/fold/proposal/0", "failed", reason=type(exc).__name__)
    raise
report = ledger.readout()
```

Default genesis is `{"namespace":"evo881.dynamic_factor","prior_n":null,
"authority_source":null}`. Local `local_attempts_n` counts every begin, including
failed/NaN/duplicate/interrupted attempts. `cumulative_n` remains `null` until an
explicit nonnegative `prior_n` is supplied, then equals `prior_n + local_attempts_n`.
A known count without authority remains non-certifying. A supplied authority must
contain a `reference` and full `sha256`; this is an explicit caller assertion, not
an independently discovered project authority. A new authoritative history must
be imported through a separately reviewed migration, never by resetting this DB.

All records are transactional SQLite events, inserted before execution, with
immutable outcomes and a hash chain. Same attempt ID/same input is an idempotent
transport retry; a repeated proposal under a new ID is another attempt. NaN/Inf
observations retain `status=nan`, `reason=nonfinite_sharpe` and a null Sharpe. The
logical `n_ledger_hash` covers genesis plus all events and survives DB reopening;
it is independent of SQLite page layout and filenames. Export the `artifacts.ledger`
snapshot with each run and preserve the DB for restart. The chain plus exported
hash detects changes relative to that anchor; it is not protection against an
operator rewriting the complete history and all anchors. Concurrent writers use
`BEGIN IMMEDIATE`/FULL synchronous transactions. This is for a local filesystem,
not a distributed multi-host ledger.

### Fees

`ticket.json` example:

```json
{"price":50,"ticket_usd":5000,"gross_edge_bps":10,"sell_date":"2027-01-01",
 "rate_basis":"effective_date","pnl_basis":"reference","one_way_daily_turnover":0.1}
```

Fee rates and ×1/×2 multipliers come directly from the unmodified EVO-882 parameter
files. `fee_schedule.json` is a separate, versioned date-to-rate-field mapping
derived from their `sources.F3` and EVO-884's instruction. TAF is zero in 2026 Q4
and restored on 2027-01-01. Earlier dates are refused with `effective_date`;
`research_restored` explicitly requests the supplied research assumption for all
history. Section 31, GST, eligibility and actual rounding remain the unknowns in
the original parameter files; the tool preserves those assumptions.

`reference` P&L deducts explicit fees plus spread/slippage. `cash_bid_ask` P&L
already contains ×1 friction, so ×2 stress deducts only the extra ×1 friction.
`cash_net_edge_bps` deducts the actual scenario arithmetic; `net_edge_bps` uses the
conservative admission floor. That floor is never charged as an actual cash fee.
Whole shares are rounded down; zero affordable shares and algo orders are refused.

### Calendar and fold manifests

`wf_manifest_check` expects:

```json
{"calendar":["2026-01-05","2026-01-06","2026-01-07","2026-01-08"],
 "portfolio":"portfolio","benchmarks":["SPY"],
 "series":{"portfolio":[{"date":"2026-01-05","close":100}],
           "SPY":[{"date":"2026-01-05","close":100}]},
 "label_horizon":1,"embargo":0,
 "folds":[{"fold_id":"one","train_start":"2026-01-05","train_end":"2026-01-05",
           "test_start":"2026-01-07","test_end":"2026-01-08"}]}
```

Calendar entries are ISO trading dates, sorted and unique. Supply the frozen
calendar's provenance in the manifest as well. Each series is checked within its
own first/last dates; dates outside calendar coverage, internal omissions,
nontrading bars, duplicates/unsorted dates, nonfinite/nonpositive prices and
benchmark/portfolio date mismatches are refusals. No alignment or forward-fill is
performed. Beta/IR stay null: this validation tool is not their estimator.

`run_walk_forward` takes the calendar/fold/horizon/embargo fields, feature/label
rows and trusted miner/fitter factories. Each row has `date`, numeric `features`,
and (in train only) `target` plus `label_end`. Horizon and embargo are **trading-row
counts**: the last training label endpoint plus embargo must be strictly before
test start. This implements a pre-test gap for forward-only folds; it does not
reuse the old CPCV post-test embargo interpretation. EVO-883 must map its frozen
policy into this explicit interface. It supplies all cutoffs; no folds, dates,
holding horizon or statistical thresholds are hardcoded.

Factories receive a frozen `FoldContext`. New miner/fitter/model identities are
required for every fold. `miner.mine(train)` receives immutable `TrainRow`s and
returns ALL proposal specs. They are registered before `fitter.fit(train, proposals)`
can select/scale/refit. Fit returns `FitReceipt(model, fit_dates, train_sha256,
proposals_sha256)`; exact dates and hashes must match the supplied train view.
`model.predict(test)` receives immutable feature-only `FeatureRow`s with no labels.
Full-history/mismatched fit receipts, reused instances, label leakage and duplicate
run/fold invocation are refused. A failed discovery invocation is recorded too.
Invocation records also count locally, conservatively; the official N adapter
must resolve their statistical meaning after EVO-883's policy arrives. Fit
failures and every proposal remain in history.

These are in-process data-flow/receipt checks for **trusted adapters**. They cannot
prove a malicious adapter did not read other files or fabricate a receipt. They
do not execute untrusted/generated Python and do not provide an OS sandbox. The
tests use deterministic toy adapters solely to verify data-flow isolation.

### DSR, receipts and extension seams

`prereg_check` checks a minimal adapter schema: `version`, `dsr` (`formula_id`,
`variance_method`, `sharpe_scale`), `fold_policy`, `fee_params_sha256`, `ledger_policy`.
`prereg_sha256` is its canonical JSON hash; keep the original attachment's raw
SHA separately. This schema is an engineering seam, not an invented statistical
policy. The future EVO-883 integration must preserve all authoritative fields.

`dsr_eval(request, ledger, prereg=..., prereg_sha256=..., plugin=DSRPlugin(...))`
requires matching prereg/formula/source-module identities, explicit Sharpe scale,
and authoritative ledger genesis before invoking a trusted plugin. The plugin
receives the entire event history, not only survivors. It owns DSR, independent V,
missing-observation handling and the passed flag. No plugin ships in this package;
the unit test contains a labelled sentinel solely to verify the interface. Numerical
DSR acceptance assertions are pending EVO-883. Do not plug in the paused track's
formula, variance estimate, ledger or session N as a substitute.

`shadow_readout` evaluates offline confirmed receipts, partial quantities, failed
protective legs, unknown fees and missing marks. `IntentJournal` persistently
deduplicates intent IDs and blocks new registrations behind unresolved receipts;
conflicting retries require an explicit later reconciliation workflow. Neither
function places or simulates orders or calculates a portfolio return. `decay_check`
is an explicit `prereg_missing` stub. The D6-8 shadow ledger remains separate work.

## Frozen input provenance

`fixtures/provenance.json` records exact original member and ZIP SHA256s:

- EVO-882 attachment `01a18a70-4c3d-74b3-a6ff-d497263f00aa`: unmodified `fee_params_x1/x2.json`.
- EVO-881 addendum attachment `01a18a72-9aa3-792e-8ff3-c7175b416a16`: unmodified `calendar_gap_scan.json`.
- EVO-879 attachment `01a18a28-ffae-7976-aea3-fc1b2751daa1`: unmodified 9-case `harness_cases.json`.

The original addendum used AAPL as its reference calendar, without official exchange
cross-check. This limitation remains; it is sufficient to freeze a known negative
case, not to certify the full dataset. No live prices, new quota consumption or
data refresh is part of this change.
