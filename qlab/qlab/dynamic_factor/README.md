# EVO-884 offline dynamic-factor tools

Deterministic contracts, data guards, ledgers and arithmetic for EVO-881. No
broker/account writer or scheduler. Harness inputs are labelled synthetic units,
not strategy backtests. EVO-885's `shadow15k` files are separate.

## Frozen identity and unavailable runtime

| Artifact | SHA256 |
| --- | --- |
| EVO-883 executable conventions v1.0.1 | `1767b7cf844721468f506e984c303c49e8ff58c395515404187d403661abe97b` |
| Prereg v1 | `3139ab15b8cb53b3c7cdc81816ce9fa4a6ad1862fb836dcde88f1cc31235447f` |
| Common profile | `4292eb477baffafaeff24441ab36936580608f70d2c8672d94d596fc772686b3` |

The default loader checks exact bytes, companion agreement and the profile hash
recipe. Reports carry version/SHA/profile identity. Old profiles cannot supply
current V. Historical JSON files remain unchanged for provenance.

**Every public DSR route, including the injected-plugin interface, returns
V/DSR=null, `certifiable=false`, `runtime_consumable=false`.** Plugins never
execute. Full N and two registered reference families have not arrived. Passing
mechanical registry checks does not enable them. Only `dsr_v0.formula` and
`daily_sr` allow pure numerical unit assertions with external V.

Public `wf_manifest_check` and `run_walk_forward` require pinned conventions and
manifest identity. Runtime folds stop before adapters while bindings remain
pending. Private `_..._unbound` engines are offline mechanics test seams. Train
slicing is shared with the reference producer; train-only fitting, label maturity
and embargo guards remain. The 77-fold calendar and 21-session gap come from JSON.

## Ledger integrity

The bound constructor validates actual seed bytes: eight rows / 47 observed
attempts, SHA `76ece03d62628a2ca2f0cb089103deaa26584ae9522fdde101df782a738a8f0b`.
They remain an incomplete lower bound: `cumulative_n=null`, `n_complete=false`.
Failed/NaN/rejected attempts persist. Real retries use new IDs; transport retries
are idempotent. All declared references count in the same N before performance.

Each transaction checks a separately retained witness: ledger ID, DB path,
genesis SHA, sequence, tip, logical snapshot SHA, local count and N high-water
marks. Truncation, old snapshots and replacement refuse before reads or appends.
Bound constructors reject caller-written genesis; bound CLI rejects `--genesis`
before creating a database.

First creation needs an operator-reviewed bootstrap receipt: `action`, exact
`target`, `genesis_sha256`, `ledger_id`, `authority_source.sha256`. Default bound
witness: `.evo881-project-tip.json` beside the DB; `--ledger-anchor` explicitly
locates it. Retain/back up the witness separately and share it across processes.
The tool checks receipt identity, not the authenticity of operator approval.
`harness_helpers.fixture_ledger` provides synthetic unit authority only.

`ledger.migrate(target, target_anchor=..., receipt=...)` needs fresh targets and
a receipt binding current witness state, source witness SHA, ledger ID, target
paths and authority SHA. It copies/fsyncs history and retires the old writer
without deleting evidence. Stale receipts refuse. Crashes between DB commit and
witness fsync, or during migration, fail closed and need independently reviewed
recovery. Rewriting both DB and witness is outside this local integrity boundary.

## Reference producer and registry

The real EVO-892 v1.0.0 definitions are pinned under `fixtures/evo892/`:
registry `83c9d47f…a3b2`, candidate `17c00800…fabc4`, meta `c6fa724a…bba4f4`.
Raw registered bytes remain unchanged. Platform comment `01a18ad3-1902-7e98-9148-ef585c05ce82`
created at `2026-10-30T03:20:52Z` is recorded separately; local sealing time does
not replace it. Non-author ordering review remains an external EVO-887 gate.

`reference_manifest_check` checks both raw definition SHA domains, exact platform
anchor, role and full membership. Candidate members are CREF-F1-L020/F3-L020;
meta-reference members are MREF-F2-L020/F4-L020. Their frozen definitions use the
existing H10 solo-probe rules and CANDIDATE_PROBE_V03 execution overrides. META_EVAL_V03
is an evaluation role for existing meta17 probe components, not a new meta policy.
The dispatch cannot accept another member, altered parameters or an evaluator callback.

`prepare_request(policy, fold, candidate_view, input_bindings)` checks the same
fold object and shared splitter callable before creating a restricted train/warmup
packet. Candidate folds use that same helper. All 77 train1260/warmup252 calendar
hashes match the registered projection. A copied fold object or another callable
refuses. The worker sees only those tuples, never a whole market/test view.

`run_isolated(root, packet)` launches the pinned entry with `-I -S`, no inherited
environment/extra FDs and no user site. Imports finish before the worker installs
an audit hook, then data reads begin. Only readonly `panel.json`, `benchmark.json`
and `profile.json` are allowed. Schemas/hashes are strict; profile includes the
exact registered fold projection for validation, not another runtime splitter.
Candidate/meta files, copied output schemas, caches, symlinks/hardlinks, writes,
network/process operations, dynamic imports and gap/test rows refuse. Static AST
proof checks the import graph, import-time effects and hook-before-read ordering.
This capability protects pinned trusted Python code; it is not an OS sandbox for
hostile native extensions or an operator rewriting code and receipts.

The entry emits four preparation jobs and access/view receipts, **no returns**.
It does not launch reference computation. Actual output evidence belongs to
EVO-886; adding/changing execution code requires source resealing and review.

`reference_runtime_check` validates separately hashed result sidecars, binding them
to fixed definition hashes. It checks actual producer/current-run separation,
allowed DAG edges, input/policy/source SHA, exact train dates, finite full-family
observations, scale, generation/sealing before S0 and after the static seal, and
independent anchor-review receipts. The P7 checker verifies supplied EVO-891 tail,
complete-history receipt, attempt/retry map and candidate/meta N order. It never
writes the unique ledger or turns the newly delivered N=75 draft/open gaps into
an accepted complete N. Receipt consistency does not authenticate self-issued
claims; acceptance of authority and history remains external.

| Proposition | Current delivery | Remaining dependency |
| --- | --- | --- |
| P1 closed rules/dispatch | Proven for pinned entry | Actual output evidence at P4 |
| P2 input views | Proven statically and by unit receipts | Actual runtime receipts |
| P3 access boundary | Proven for pinned preparation worker | Source changes require reseal |
| P4 output lineage/timing | Validator only | EVO-886 actual outputs/DAG/time |
| P5 role mapping | Proven against registered definitions | Actual runtime roles checked again |
| P6 shared splitter | Proven; 77 calendars and object identity checked | Actual runtime identity receipt |
| P7 N/retries/order | Validator only | EVO-891 accepted complete tail/attempt receipts |

`seal_static(sealed_at)` records current source hashes and an explicit UTC time.
The runtime checker requires that seal to precede every reference start, and
sidecars to precede current S0. `lineage_proof` enumerates P1–P7 and leaves actual
run/output fields null. The final seal/proof artifacts are in `evidence/evo892/`.
There are no fabricated actual run IDs or real return artifacts. Harness runtime
sentinels are explicitly SYNTHETIC_UNIT values, never authority/research inputs.

## Fees and valuation

`fees.fee_frontier` keeps its signature and original x1/x2 parameter bytes. Each
net order/side uses max(model including GST and half roundtrip friction, 10bp),
then multiplies the entire result by x2. Cash bid/ask P&L subtracts already-paid
baseline friction once.

`orders` accepts cumulative fills keyed by broker order ID × exchange local trade
date. Only DAY orders: partial fills reprice cumulatively and charge increments;
terminal/EOD cancellation ends the residual. A new ID starts new minima.
Restored TAF applies to all research dates. SEC/TAF order/date aggregation remains
unverified, including large QQQ orders. Actual fees stay null without verified
billing. A known effective new rate without its parameter receipt rejects new
risk and leaves affected cost/net null. This is a research budget, not billing.

QQQ analytical TR uses EVO-889 `D_used_for_TR`, event table SHA
`1ab413d1a1c4118ae58d21e476454502d613f1c88914a9076b90de8fa6247c87`.
Raw closes and exdate-close fractional reinvestment give conditional pre-tax,
zero-fee arithmetic; event qualifications remain visible. No qfq ratio is used.
VTI is fixed B2: unresolved dividend/paydate/price evidence yields null. SPY
never substitutes; it remains an archived/QA reference.

`integer_cash_valuation` separately reads integer inventory, known cash,
entitlements and payment availability. Unknown amount gives null receivable/NAV;
unknown paydate gives null credit amount/time. Known receivables are not spendable.
Ex-open entrants do not receive that dividend. No free fractional DRIP, automatic
purchase or account write occurs. Outputs remain non-consumable.

Data guards flag rather than repair missing/nontrading/duplicate bars, nonpositive
prices, calendar misalignment and parameterized jump/reversal pairs. Fixed SPY
inputs preserve 2011-07-04, 2012-04-06, 2012-05-28 and missing 2012-05-29 with
separate reasons. A trading-session variant tests independent jump detection.
Beta/IR remain null with incomplete evidence.

## Verification and CLI

```bash
PYTHONPATH=qlab:. python -m pytest qlab/tests/dynamic_factor qlab/tests/test_qlib_gen.py -q
ruff check qlab/qlab/dynamic_factor qlab/tests/dynamic_factor
ruff format --check qlab/qlab/dynamic_factor qlab/tests/dynamic_factor
PYTHONPATH=qlab:. python -m qlab.dynamic_factor.harness --workdir ./harness-run-a
PYTHONPATH=qlab:. python -m qlab.dynamic_factor.harness --workdir ./harness-run-b
```

Harness directories must be empty. Independent processes on the same interpreter
produce byte-identical reports. The original fixed ten cases remain, supplemented
by audit/v1 negatives and pure numerical assertions. Network, clock, RNG, model
calls and strategy backtests are absent. Historical 76/84 differs by the eight
optional `test_qlib_gen.py` tests, skipped without qlib. The current PR records the
new count; obsolete coupled-V positive tests were replaced by refusal, producer,
fee, valuation and integrity regressions.

`python -m qlab.dynamic_factor --help` lists JSON tools. Formal DSR/fold calls
require `--conventions`; persistent bound calls need a retained witness and
`--ledger`. `--ledger-bootstrap` reads an explicit first-creation receipt. CLI
exits 2 on refusal and never imports code named in JSON. `reference_runtime_check`
accepts a hash-keyed UTF-8 evidence map; it does not chase arbitrary file paths. Reports carry input and
source SHA/assumptions. `--out-dir` writes immutable content-addressed readouts.
