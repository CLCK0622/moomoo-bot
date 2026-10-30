EVO-897 implements the offline E0 interface for `LLMCLI-v0.1.2`. Its base is
`eb016acc0a1153837aa885c16c38a2b123036023` (PR #11); this work belongs to a
separate branch and draft PR. This PR delivers items 1 and 3. Item 2's real
`dsr_eval`/ledger wiring is deferred until F3b incremental independent review
and an explicit item-2 release on EVO-897. This base contains `08c9d87` and F3b
`1946996152c44ca1540bf8b2fffcea61333f1247`. F3b and PR #11 replay passed Gongbu's
clean-clone review; incremental non-author acceptance remains separate. None
of those upstream files are changed here.
All new observations are synthetic. There is no
model launcher, broker, OpenD, price fetcher, authority writer or production
configuration in this package. `runtime_consumable`, `runtime_authorized` and
`certifiable` stay false. P0, S0 and L0 require their separate grants.

## Bound source bytes

`fixtures/` preserves the main document, canonical profile, external acceptance
v1 receipt, v3 ruling, machine acceptance receipt, reviewer archive, original
20-file source archive, prompt, schema, gate table and engineering specification.
`contract.bindings()` rechecks all seven assigned hashes and prompt/schema hashes
at each operation, plus the machine receipt's ruling/main/profile/archive links.
The receipt is an external input; the profile bytes
are unchanged, including its historical pending-design flags. This package does
not turn those flags into runtime permission.

| Input | SHA256 |
| --- | --- |
| Main document | `e9e089b17e15b86d7bd96e0e8f69cced47759c181b1d2e3bb220743225c71b2c` |
| Canonical profile | `1736b460538b2b18142877e1729ed839ba83a4f99282c2461de07f2711277e8d` |
| External acceptance v1 | `72859801e8c47c4ebd0553854e8ed3d7e518be5bd21aaaa97c1e6866c9e4f279` |
| Ruling v3 | `c05b8419d8c2d10f6e911e847dd9548af62624171cadde36dd20ba12a53c79de` |
| Machine acceptance | `577e649f4a039d6e14ab9dea047732d460ee7ef0a301ae2ec86aaaa59d432813` |
| Reviewer archive | `d7488c24facc8f128dd0847fab4a802720297f106666f7e923cec5f0e42cc843` |
| Author 20-file archive | `ac9565743c1b3c5449d014995df48e5442fda5184a3ba43d53ab28b21f2b780d` |

## Interface and decision gates

`snapshot.build_decision()` builds a content-addressed, causal 65-asset model
input with the assigned field set, 252 aligned observations, explicit source
hashes/cutoffs, TR and corporate-action inputs, eligibility, reconciled x2
inventory/cash, age/cooldown state, required M and fee bindings. Unknown
eligibility, future input, incomplete history or unreconciled submission refuses.
Only `SYNTHETIC_E0` state is accepted here; a real source adapter is not installed.
TR/source values supplied by a fixture are not an attestation of market quality.

`contract.validate_output()` accepts one JSON object with no duplicate keys,
nonfinite values, extra fields or repairs. READY must rank exactly the eligible
50–64 names and supply the frozen 65-item target/forecast order. Share floats,
booleans, strings, shorts, duplicate/omitted symbols and panel outsiders refuse.
IDs/profile must echo the bound input. ABSTAIN uses empty arrays and a non-OK
reason. Parsing never proves actual provider identity.

`adapter.adapt()` uses one copied execution object for every repetition. The
object binds original x2 cash/inventory, the unique required M, risk/age state,
actual reference open/prices, fees, ADV, eligibility, calendar and actions. It:

1. Constructs M and validates the frozen required-action vector; mandatory exits
   include risk/integrity/eligibility, age 20, and the frozen age/rank rules.
2. Retains young holdings, occupies slots by age then frozen rank, applies
   cooldown and equal 4% slot targets with at most five names/20%, then computes
   the QQQ base. There is no cheaper-name substitution or reset of holding ages.
3. Cancels **satellite BUY increments**, including additions to existing stock,
   at actual raw open strictly below USD 20. Existing stock is not sold by this
   price rule. QQQ is exempt; missing/nonfinite/nonpositive price refuses.
4. Only reduces buys in fixed priority order to satisfy integer cash including
   fees, 2% available-cash floor, 0.20 turnover and 1% ADV. Mandatory gross
   reductions use the frozen 0.50 cap. Released budget is not reallocated.
5. Prices both full net plans after cancellation/reduction using `FeeBook`
   x2, restored TAF and each-order floor-before-multiplier policy. It uses
   `G=sum((P-M)*open/E*forecast)` and `K=max(0,C2(P)-C2(M))/E`, strictly `G>K`.
   A required null forecast rejects P. Rejection returns independently valid M;
   ABSTAIN can still carry independently verifiable protective M.
   No quantity changes after approval, second subset search or fabricated fill.

`initialization_plan()` separately implements the fixed three-session QQQ-only
startup, including 40% buy notional, 0.20 turnover, full fees, cash/98% investment
and ADV constraints. Model output cannot replace this initialization path.

## Logs, R1 and termination

`Archive` writes raw bytes as exclusive content-addressed files, fsyncs them,
and transactionally appends their manifests to SQLite with a verified hash chain.
It validates physical containment under a host-owned root before mkdir/DB and
on subsequent operations; symlinks, hardlinks, controlled lines and foreign
files refuse. Its default root is `.llm-direct-offline/` in this checkout. The
harness explicitly binds a different private host for each independent case.
Hashes detect corruption and support the issue attachment's external anchor;
they are not signatures against an owner who can rewrite the whole archive.

`Runtime.freeze()` fixes configuration and aggregation before generation.
`record_generation()` durably retains every supplied raw response, input,
prompt/schema, visible context/events, redacted stderr, model/binary metadata
and synthetic authority pre-reservation receipt. Failed, late, unknown and
invalid responses remain evidence. Normalized visible-event metadata must bind
the raw response hash and provider request/model; the full context must bind
the actual prompt, schema and input bytes. CLI/provider extraction and authentic
subscription/pre-reservation attestation remain P0 integration work, not claims
made by these synthetic fixtures. No request is dispatched by this API.

`seal_group()` requires a pre-open manifest. `replay()` never asks a model again:
it captures one private copy of the execution snapshot for the entire group,
requires 30 entry or five monitoring outputs, retains each attempt validation,
then checks original
Jaccard/weight/base/cash metrics and **zero pair differences** in approval bit,
65 whole-share holdings and sorted economic net orders. Pure request IDs/audit
times/output hashes are excluded from economic comparison. Raw and final entry
targets both need at least three names and 12–20% satellites; monitoring risk
reductions can be empty. Until actual open input exists the result is pending.
`freeze_entry_sessions()`/`entry_summary()` require the preassigned ten-session
schedule bound to the first ten entries of its supplied calendar and all ten
groups/300 generations; one successful group is not entry
qualification. No diagnostic computes or displays investment return series.

Snapshot unavailability, binding/visibility failure or an R1 failure terminates
the version. `lifecycle.py` stores the tombstone and original clock in a
**host-scoped registry outside individual archive directories**. Reopening or
choosing a different directory cannot revive that version; an archive/config/
clock change needs new registration. No fallback or in-place version restart is
provided. A new version must receive new profile/config registration, applicable
authority and, when market-outcome evaluated, its own configuration trial.
Required protective handling remains separate; termination does not prove exit.

## Shadow ledger mapping

`intent.envelope()` reads the archived successful comparison, uses only index 1
and produces `llm_direct.forward_reference/v1`. The deterministic parent digest
uses version, canonical x2, decision/input, prompt/model binding, canonical raw
output and final plan. Per-order IDs bind parent/symbol/side/date/DAY. Retry
timestamps never enter business identity; replay returns the original creation
timestamp. The full decision-bundle hash includes the common execution snapshot,
original inventory, M/P and comparison. Quantity is the **positive difference**
from original confirmed inventory; protective is true only for required SELL.

The strict kernel remains `ShadowLedger` with its original four intent fields
and six order fields; provenance stays in the outer envelope/archive. NOOP has
no fabricated order. `register_synthetic()` is an explicit offline test seam
requiring this arm/version, reference prices, an isolated offline ledger and
the exact envelope in its live source archive; a modified or unanchored
envelope refuses before ledger access.
The envelope declares distinct versioned x2/x1 namespaces; actual x2/x1 ledgers
remain in separate physical directories/DBs. Both get the same parent/order
IDs and quantities. x1 never controls or reoptimizes x2. Receipts, partials,
unknown submission, missing marks, dividend receivables and available cash keep
the original accounting kernel's null/reconciliation/idempotency semantics.
Actual forward-reference execution is still disabled.

## N wiring and reference books

`dynamic_factor.arm_n` now owns the shared read-only implementation;
`llm_direct.arm_n` preserves its original API through re-exports. Actual
`statistics.dsr_eval()`, `pipeline._n_snapshot()` and both ledger classes'
`arm_readout()` consume this projection from one verified snapshot. The legacy
`dsr_v0.evaluate()` route delegates to the same public gate. No reader writes a
self-reported N. The actual DSR/readout/pipeline paths are exercised by all three
N negative classes in the synthetic harness, rather than testing only project().
Every event and read request needs an explicit recognized arm tag. A
configuration is prompt version × model snapshot × parameters × ruleset. It
must be reserved before any outcome; its first market-outcome evaluation counts
one, and repeated evaluations do not add configurations. Every actual request,
including repair/retry/failure, remains a separate request sensitivity event.
Both rows are always reported together; other-arm trials contribute to neither.
Unknown internal counts stay null, not zero. A document-only change is not an
invented trial. A change after observing outcomes is a new configuration.

Historical records without explicit arm/config/outcome reconciliation **refuse**
formal projection. Original recorded N/high water/tip are retained separately as
global historical evidence. No tag is guessed from a run name and no high water
is lowered. This work does not migrate or write the authoritative ledger. Even
tagged fixtures report only observed counts: complete N and runtime DSR/V remain
null, with explicit missing-history reasons. No independent-return V or
cross-arm comparison/correction is inferred from stability replicas.

`reference.signal()` preserves the assigned MOM20/REV20 alpha, clip, mu_Q and
ticker tie break, taking only the caller's causal market/own-state input.
`ReferenceBook.freeze()` fixes all three roles, algorithms, profile, producer SHA
and calendar before D0. Daily source/ledger/return-source bytes are hashed and
sealed in order, with separate books/run identities. Replacement, skip, rewrite
and backfill refuse; missing day is not silently filled. These synthetic source
books do not constitute forward returns, independent V, IID evidence or source
authorization. `milestone.decide()` only routes already supplied interval
inputs under the
frozen day63/126 rules: QQQ upper bound <=0 stops first; crossing zero extends
once regardless of missing/low diagnostic DSR; config changes invalidate.
Statistical estimation and real sampling stay outside this engineering run.

## Reproduce

From repository root, Python 3.9.6 or 3.12.13 (harness uses standard library):

```sh
PYTHONPATH=qlab:. PYTHONDONTWRITEBYTECODE=1 python3 -B -m qlab.llm_direct.harness --workdir ./repro-e0 > harness-e0.json
PYTHONPATH=qlab:. PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest qlab/tests/llm_direct qlab/tests/shadow15k qlab/tests/dynamic_factor qlab/tests/test_qlib_gen.py -q -p no:cacheprovider
python3 -m ruff check --isolated --no-cache --exclude fixtures qlab/qlab/llm_direct qlab/tests/llm_direct qlab/qlab/dynamic_factor qlab/tests/dynamic_factor/test_arm_n.py
```

Use a fresh workdir for each harness run. Networking is denied and counted.
Compare complete JSON SHA256 per interpreter. Cross-version canonical SHA
removes **only root `dependencies`**, then serializes UTF-8 sorted keys, compact
comma/colon separators, `ensure_ascii=False`, no final newline. Source hashes,
input hashes, all outcomes and numeric strings stay in that comparison. Historical
EVO-884/EVO-885 evidence files remain unchanged; their old source seals describe
their historical commits. This PR's new evidence is attached to EVO-897.
