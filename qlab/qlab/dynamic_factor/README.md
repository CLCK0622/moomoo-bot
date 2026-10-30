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

## Ledger integrity and fixed project authority

Formal `AttemptLedger.from_conventions` checks immutable convention/seed identity,
then opens only the fixed project JSONL/witness under
`research/dynamic_factor/authority/`. Caller `--ledger-anchor` or bootstrap input
cannot select another formal project witness. Missing project state is never
created by evaluation requests. First installation is a controlled copy of the
published authority and witness; a new path requires a reviewed migration and
project mapping change, not a retargeted bootstrap. No project state is installed
or appended by this PR's tests.

`AuthorityLedger` independently reads the exact EVO-891 B v2 canonical JSONL,
source SHA `a8f50e02644ec4a86460f8038b89edcbc1811352e5bf320dca592cef6abcb87e`.
It validates the separately retained witness and the published ancestor:
ledger ID `37a3871d39df8a641f64d39b335338c0f1d66bb1e20ed9b6c4cf456a508f02cc`,
sequence 20, tip `9e3220aa6aa6dcc7f2a03c4f1f917b2da40af78c90173156f6ca4e9efd8e9c0d`,
N high-water 75. Read and append recompute the full chain, retain the exact first
21 published rows and verify any supplied later external anchor as an ancestor.
The fixed published anchor cannot be overridden with a weaker one. Append is an
explicit writer API; normal evaluation is readonly. Appends preserve the prefix,
N/high-water never decrease, and stale/corrupt anchors refuse before mutation.
A crash between append/fsync and witness update fails closed for reviewed recovery.

`authority_ledger_check` reads a versioned JSONL/witness pair without installing
it. Its recorded N=75, sequence, tip and all computed state fields match the
unchanged upstream verifier byte for byte. The raw upstream Python tool is kept
as a SHA-pinned fixture and excluded from automatic lint/format changes.
Recorded N is not complete N: G1–G5/P02 remain external acceptance issues;
`complete_N=null`, `n_complete=false`, DSR/V remain null. P7 sidecar validation
also verifies actual JSONL descent and exact N snapshots, not just caller SHA text.

The old SQLite mechanism is an **offline unit seam**. Its historical seed remains
exact eight rows / 47 attempts, SHA
`76ece03d62628a2ca2f0cb089103deaa26584ae9522fdde101df782a738a8f0b`.
Only `_from_fixture_conventions`/`fixture_ledger` opt into synthetic bootstrap;
CLI cannot select that capability. Synthetic source high-water 500 cannot be
reset by editing a receipt target or giving a new witness path. Native SQLite
migration tests retain old evidence and never constitute project JSONL-to-SQLite
migration approval. No automatic history/schema conversion is performed.

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
writes the unique ledger or turns the accepted N=75 continuation anchor/open gaps into
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
run/output fields null. The earlier registration/R1 seal and proof remain archived in `evidence/evo892/`.
The effective seal is indexed by `evidence/current-seal-index.json` and stored
in `evidence/evo884-f3b-v1/`. Old source seals cannot authenticate changed code.
05:16 件是历史 `45eb817` 封存，已由 06:05:55 当前件替代。
The 06:05:55 seal in `evidence/evo884-handoff-v1/` matches historical HEAD
`6c63505f72135063162c1f55ecfaa03514f1fa32`. F3 changes the sealed `continuity.py`,
so the new seal supersedes that receipt for this commit's sources. Historical
files and platform attachments remain intact. The final handoff binds the exact
commit SHA after a fresh clone verifies the seal's 21 source hashes; no earlier
seal is claimed to match the F3 HEAD. The 07:09:57Z F3/T1 seal matches historical
`08c9d87ab4bef9abae6b5edabaf07c0adcb40052` and is superseded by the F3b seal.
Independent review is still required for the new sources.
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
VTI is fixed B2: the EVO-883 disposition refuses the entire frozen formal
interval pending an accepted closure/equivalence receipt. Self-asserted verified
flags cannot enable a suffix. SPY never substitutes; it remains archived/QA only.

`integer_cash_valuation` accepts explicitly versioned QQQ cash events from
`qqq_cash_input(ex_date, entitled_integer_shares)`, bound to mapping
`71953b09…1260` and ruling `641c03af…7c5e`. All 53 exchange-source amounts/paydates
are pinned; old analytical CSV bytes stay unchanged. For 2022-12-19 the corrected
input declares 0.65541 and archives vendor 1.31082 with distinct source hashes.
A caller retaining the wrong declared amount, wrong source or missing mapping
receives null receivable/NAV, never a silently repaired event. Entitlements are
explicit simulated inventory-writer inputs; ex-open entry receives no dividend.

All cash fields (including legacy `cash_credited_*`) are labelled
`simulation_pre_tax_integer`. Before supported payment availability, receivables
are not spendable. On/after the exchange paydate, credit additionally needs explicit
`simulated_payment_available`, amount/time and source SHA from the simulation
writer. Exchange paydate alone leaves availability unknown. Actual account
amount/time stay null; no probe, fractional DRIP or inventory change occurs.

`panel_input_check` binds the adopted eight-row disposition and records affected
symbol/date/dependency and null value. The formal manifest guard calls it for
`panel_inputs`; it neither replaces members nor certifies a 56-name universe.
The existing 252-session/min50 qualification still needs its original evidence.

New authoritative attempts must count recomputations/retries. Same parameter cells
alone refuse zero contribution. Exact same-attempt payload delivery is idempotent;
continuations additionally need the linked attempt/run and an already recorded
artifact/log SHA, no evaluated/new trials. Published P02 and open gaps are preserved,
never silently reclassified. The reader enforces the stricter rule after seq20.

`input_migration_check` validates a versioned input receipt against the retained
current witness, old tip/sequence/N, identical full JSONL chain, original frozen
QQQ CSV and new mapping identities. It rejects N rollback and old-snapshot replay.
It does not install/retire a project ledger or accept JSONL-to-SQLite conversion;
operational path changes/contribution mappings need separately accepted evidence.

`scope_proof.b2_isolation_proof` binds the minimum-scope ruling (`56d97ab7…` /
`730931cd…`) and source hashes. Its import whitelist, consumer-dominating guards,
reader sites and symbol/file/header whitelists exclude VTI/B2 from features,
QQQ labels, calibration, admission, reference inputs, holdings/cash and orders.
`scope_reader.read_strategy_inputs` permits the frozen 64 members plus QQQ,
explicit symbol headers, exact bound dates and byte SHA, no path/link aliases.
The isolated reference reader now requires a QQQ benchmark header and uses the
same pure B2 guard. This proves owned trusted interfaces and declared source
identities; it does not certify market-source truth or hostile external adapters.

An unavailable VTI entry is still required in `wf_manifest_check.b2_manifest`:
all 3191 dates, reason/missing fields, source SHA, affected scope exactly B2,
empty dependencies for all seven strategy roles and the current static proof
SHA. With that receipt, the independent B2 value stays null without blocking
primary data precheck. Main QQQ inputs must cover the original dates; no SPY,
suffix or complete-case deletion. `data_bindings_complete` and
`all_readouts_available` are separate. This never releases S2 or runtime gates.

`continuous_path_check` checks every original fold/date vector, causal input/output
state SHA, attempt/count receipts and monotone consumed/seen-result budget state.
It preserves all 77 records and known inventory/exit intentions. Invalid NAV/state
makes dependent future NAV, A/IR/interval null; skipped folds, capital restart,
state-link changes or budget refunds refuse. This is receipt consistency only,
not independent N/budget authority or permission to recover/recompute.

The actual fold mechanism stops adapter calls at its first failure, writes all
fold statuses to the ledger, and retains unexecuted blocked folds and budget
unknowns. New failures/retries retain their N entries; exact existing attempt-byte
delivery alone is idempotent. Formal pending paths also return all original folds.
S2 missing SR/N/V or legal admission is explicitly refused with pool and fallback
holdings null; it cannot become an empty pool holding QQQ. All V/DSR/runtime
certification stays unavailable. The nine new refusal cases are recorded in
`disposition_harness.py` (five) and `scope_harness.py` (four).

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
`--ledger`. `--ledger-bootstrap` is rejected by formal project evaluation; synthetic unit receipts are not accepted. CLI
exits 2 on refusal and never imports code named in JSON. `reference_runtime_check`
accepts a hash-keyed UTF-8 evidence map; it does not chase arbitrary file paths. Reports carry input and
source SHA/assumptions. `--out-dir` writes immutable content-addressed readouts.

## Review corrections F1/F2 and current witness

The current external witness is EVO-893 ledger v4, seq182 / recorded N280,
tip `c9082ec0f045796754e12506cc468a09ac88a36873aee8cacbe5cf5d0769f851`.
The seq20/N75 archive remains a legal ancestor, never the current formal floor.
Formal construction and P7 reject older snapshots. The logical project path stays
fixed; no shared ledger installation or writer run is performed. The EVO-883
9301feb3 ruling accepts continuation structure, not complete N or S2 qualification.
The current sequence/count/tip are loaded from the controlled versioned
`evo893/EVO891-B-ledger-v4.tip.json` input, separately from the mutable project
tip. Formal reads and appends reload that input and verify its ancestor against
the retained chain. Authority updates replace accepted witness input bytes;
candidate requests cannot select a different witness or reset the project.

F1: `fixtures/frozen-fixtures.json` explicitly names and hashes committed inputs.
`fixture_inventory.frozen_fixture_hashes` verifies only that inventory and its own
manifest SHA; tool caches and untracked files cannot alter identity. New clean
clones are used for final validation. Neither caches nor generated bytecode are
committed as a workaround.

F2: `_legacy_fee_frontier` is retained only as an import-compatible refusal stub:
all cost/TAF/net metrics null, reason `fee.legacy_frontier_disabled`. Its date
switch arithmetic and text are removed. The execution fee helper also has no
numerical date-switch path. Public `fee_frontier` retains its signature and all
dates use restored research TAF; original x1/x2 parameter bytes remain unchanged.

The earlier 45eb817 output identities include the now-rejected F1 cache input;
use the subsequent clean-clone F1/F2 receipts for current reproduction. Historical
archives are preserved with their original commits, not upgraded to current proof.

F3: `continuous_path_check` copies submitted attempt, attempted, budget and N
declarations by frozen fold ID before validating any row or prerequisite.
`metadata_validation_status=pending` means an unchecked declaration, not an
accepted N/budget receipt; `consistent` means the local metadata checks passed.
Hard rejection changes only blocked status/reasons on unvisited rows. Missing
folds retain their null placeholders; later submitted declarations remain on
their original IDs. Rejection still stops validation, returns stay null, and
no A/IR/interval or runtime acceptance is produced. Harness regressions cover
early rejection, the audit's index-31 state-link mismatch, and a missing fold,
comparing all four metadata fields on every submitted row, including 32–76.

F3b: `metrics.submitted_declarations` preserves every input row in order before
shape, fold membership or grid validation. Each entry includes `input_index`,
`fold_id`, `attempt_id`, raw `attempted`/budget/N fields and a deep copy of the
entire `raw_declaration`. All entries remain `pending`, independent of the grid's
local validation status. Unknown IDs and malformed rows are retained too.
The separate frozen 77-row grid exposes `declaration_indices`; multiple entries
for one fold have null singular attempt/attempted/budget/N projections. Duplicate,
missing and extra folds are still rejected only after capturing the whole list;
no fragment returns or metrics are produced. Regressions cover the audit's
ORIGINAL/RETRY fold-0 declarations (N 280→281→282, fold 32 absent) and a retry
appended after all 77 original rows. The unmodified audit script's final assertion
requires the old overwrite defect, so its expected assertion failure after the
fix is archived separately from the passing ordered-declaration checks.

## B2 field provenance and snapshot switch

The separate `b2_input_readout` CLI reads the frozen EVO-891 r3 event/manifest
and audited aggregate receipts. Every event value records its source tier and
SHA: OpenD `get_rehab` supplies 49 backbone events; audited half-year totals
only constrain totals; the issuer public-page snapshot (terms verification
pending) supplies supplemental crosschecks and the two missing distributions.
These are offline source-receipt transcriptions, not freshly verified raw feeds.

`include_issuer_snapshot_fields: false` nulls every snapshot-only field,
including event split crosschecks and the 2013-12-20 / 2014-03-25 distributions.
OpenD fields, audited constraints, raw prices, all original dates and unaffected
daily B2 returns remain. Unknown distributions null their daily TR and dependent
cumulative index; the index never restarts after an unknown. Without prices,
the tool still returns field-level input receipts. Raw-price diagnostic requests
require the entire frozen calendar, raw-close basis and a source SHA.

This independent B2 tool has no imports into the seven strategy consumers.
Synthetic byte-replacement and snapshot-off probes compare actual owned interface
output SHA across all seven roles. Runtime DAG/source acceptance and formal B2
return qualification remain separate; no real reference/strategy run, account
arrival, suffix or SPY fallback is created by these diagnostics.
