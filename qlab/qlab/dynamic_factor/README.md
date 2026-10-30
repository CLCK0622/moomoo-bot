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

`reference_manifest_check` requires a platform anchor and non-author review,
registration before first performance, exact raw manifest SHA agreement, current
profile and complete membership. Candidate/meta manifests are checked separately.
No real members are invented; positive examples use synthetic fixture members.
The EVO-892 registry delivered during this revision is not wired here; its real
bindings, seven lineage propositions and runtime-evidence checks are a separately
scheduled follow-up. This revision's static proof covers only the fixture entry.

```bash
PYTHONPATH=qlab:. python -m qlab.dynamic_factor.reference_producer --inputs-root DIR
```

The independent entry reads one JSON request from stdin. Only `panel.json`,
`benchmark.json`, `profile.json` under the root are readable, with pinned hashes,
strict schemas and complete train dates. Candidate/meta output paths, copied
output schemas, extra roles, symlinks/hardlinks and test rows refuse. No real
member rules or returns are generated. `static_proof()` supplies source hashes,
AST import graph, read whitelist and shared splitter SHA. This proves pinned
trusted source, not arbitrary Python isolation or statistical IID. Changing run
IDs, directories or seeds alone does not prove independent provenance.

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
exits 2 on refusal and never imports code named in JSON. Reports carry input and
source SHA/assumptions. `--out-dir` writes immutable content-addressed readouts.
