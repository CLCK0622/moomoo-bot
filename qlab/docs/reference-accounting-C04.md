# C04 shared execution account

`ExecutionAccount` consumes the existing `execution_projection.project` (D1),
`RiskBook` / `RiskHistory` (D2), frozen fee module and the common EXEC-CLOSURE
adoption. It does not select factors, calculate G/K, accept market sources,
install an authority root, execute broker orders or grant runtime permission.
C09 remains responsible for provenance/permission acceptance and orchestration;
C07/C13 remain separate blocks. Tests use private synthetic source facts.

The constructor requires a complete host-bound canonical x2 `RiskBook`, its
snapshot SHA, the formal execution binding, and an explicit `execution_mode`:
`accepted_actual` or `named_training_diagnostic`. The latter is allowed only in
an independent training book. No default or x1 risk book is accepted.

## Locked orders and facts

`lock_projection(inputs, *, risk_signal, expected_input_sha256,
expected_snapshot_sha256, expected_signal_sha256, selected_plan,
selection_receipt, expected_selection_sha256)` calls the sole D1. The final
selection receipt has exactly `book_id`, `close_session`, `execution_session`,
`input_sha256`, `snapshot_sha256`, `selected_plan`, `execution_role`,
`decision_source_sha256`. Its expected hash is a host capability from the
original selection/gate producer, not an authorization self-reported on wire.
Choosing M or P nets its holdings against the original inventory; P-M is not
posted. `RiskBook.order_intent` is shared with `RiskHistory.prepare_open`, so
fills use the same D2 intent hash and preserve its DAY boundary.

`lock_startup(startup_book, *, expected_source_sha256)` consumes C05's owned
already-produced quantity, only in named diagnostic mode. It checks the prior
state/session and the formal binding, reuses that quantity and price, and never
copies C05 cash or fees into the account. C05's `complete_account_state` and
`current_risk_state` remain null. A source-state mismatch refuses the bridge;
there is no rounding or fabricated reconciliation of C05 state.

`record_actual(facts, *, expected_fact_sha256)` accepts closed, hash-bound fill
facts: fill/order/book/intent IDs, symbol, execution session, signed integer
quantity, price, source SHA, execution/confirmation/cash-availability instants,
and origin. Times require timezone-bearing instants. Late confirmation is not
a substitute for the execution date. Identical duplicates are idempotent;
conflicts, excess quantities, unknown price/fees or cash availability refuse.
Already accepted actual facts survive a later rejection. All submitted batch
bytes remain in `declarations`, including statements not subsequently consumed.
A rejection makes formal cash and NAV unknown, preserving raw account/facts.

`model_open(evidence, *, expected_evidence_sha256, model_name)` permits only
`reference_full_fill_at_verified_open` in named training diagnostic mode.
Evidence has exactly session, prices, source SHA, price kind, asof and origins.
Prices must be the same verified raw opens used by D1 (or C05); each origin is
explicit and is checked against retained origin/D2 permissions. The entire
hypothetical batch is atomic. Its receipt always says `execution_verified=false`
and cannot enter the actual-fact path. Candidate and all four reference roles
use this same implementation and adoption SHA. Accounts are separate objects.

## Exact fees, cash and NAV

`execution_numbers` contains the unchanged C03 exact finite-decimal parser and
renderer. `execution_amounts` re-exports them for existing callers. Quantities
stay integer; monetary arithmetic uses exact rational values of canonical
finite decimal lexemes. Each actual buy rechecks the same frozen 2% cash / 98% investment limits using
accepted raw-open prices and all retained cash receivables, without changing
quantities. A new entitlement or slippage cannot bypass that check.
The original `execution.py`, `fees.py`, `fee_model.py`,
fee parameters, fee schedule and accepted oracle bytes remain unchanged.
`ExactOrderCosts` calls that same frozen engine with its existing float output
boundary and fixed Decimal context. A net order/day accumulates its actual
notional and quantity; only the change in its cumulative fee is posted on each
partial fill. D1's exploratory quotes never post fees.

x1 uses the frozen x1 parameter file on exactly those same net orders, partial
fills and order/day aggregation. It has no optimizer, risk state or extra
orders. `fees_since_open` and fee differences refer to this owned account's
lifetime; starting from a later accepted close does not reconstruct an unknown
prior x1 history. C07's full-path report must replay the complete account stream.
Delayed sale proceeds are receivables, not cash. Their x1 fee difference affects
cash only after accepted availability. Immediate sale cash is only the named
research model's N3 assumption. Actual facts require availability instants.

`record_cash_events(events, *, session, expected_event_sha256)` derives integer
entitlement from retained previous-close inventory before ex-open fills.
`settle_cash(event, *, expected_event_sha256, asof)` requires a source-bound
actual availability receipt with UTC-confirmable timing, known amount/pay date,
and the correct book/receivable. Issuer pay date alone never credits cash.
Unknown pay date retains the receivable and refuses formal accounting.
Analytical fractional TR and automatic DRIP are not cash inputs. QQQ retains
its existing pinned source-row mapping; this component does not expand source
acceptance. Closed lineage validation and the existing quarantine predicate
precede consumption. Unknown keys/structures fail closed. Original cash-event
and payment lineage stays in the owned journal after payment or sale.

`record_unknown_right` preserves unresolved corporate-action facts and follows
R2. It does not invent split, fractional disposal, FMV or noncash-rights rules.

`close_session(evidence, *, expected_evidence_sha256)` requires known raw-close
prices, complete rights/cash-event evidence and source-bound DAY outcomes for
all today's orders (including explicit verified zero/partial execution). It
posts no synthetic fills from a missing outcome. DAY residuals cancel without
automatic next-day intent. Known receivables enter NAV but not spendable cash.
The result contains the closed `EVO884.AccountClose/v1` receipt, its hash, and
an owned immutable `CashProof`. While an open awaits valuation, the account's
formal NAV is null and `complete=false`; previous raw state remains retained.

## C06 handoff and B boundary

Pass the returned accounting/fills and their hashes to
`RiskHistory.observe_close(..., cash_proof=...)`, then call
`account.bind_next_risk(history._book, expected_snapshot_sha256=...)` on the
owned host objects. Only C06 advances age/cooldown/peak/latch. The synthetic
regression exercises three C05 opens, daily C04 accounting, C06 advancement,
three holding closes, a regular sole-D1 plan and the same D2 intent, then exact
C06 replay. No duplicate quantity or risk algorithm is added.

C06 still has its 24-field snapshot and 22-field M root. `fees_x2` additionally
accepts canonical nonnegative decimal strings under EA.N1. Legacy numeric
inputs remain accepted. Old no-receivable callers retain their strict B gate.
The new C04/C06 adapter accepts only a state/book/date/guard/journal-bound typed
`CashProof` for already reconciled cash receivables. It first checks the complete
original state, then presents a temporary cash-classified view to the shared
noncash inventory predicates. This view omits proven cash receivables solely
for that noncash proof; it never changes the retained state, state SHA or NAV
value. D1 and accounting still consume the full cash receivable. Wire dicts,
booleans and foreign/drifted state fail. `state_v2.py` is restored byte-for-byte to main `f827776`: legacy execution,
noncash and continuity readers remain numeric-only, with their original R2
rejection code. Only the new `execution_state.necessary_execution_state_known`
validator accepts canonical decimal strings, and only C04/C06 invoke it.
`zero_exposure` still calls the original numeric-only validator first; its
remaining B predicates are extracted verbatim into one private shared helper.
The exact-money adapter validates the complete original state before invoking
those same predicates. No numeric placeholders, float conversion, monetary
rewrite or duplicated B policy are introduced. The static import whitelist
is byte-identical; initial proofs, noncash rights, blocked names, children and
inventory completeness retain their original restrictions.
C06 replay requires the host's matching owned cash proofs, never reconstructs
one from a wire receipt, and otherwise refuses. `close_receipts` and
`export_bytes` expose reconciliation evidence, not an installed checkpoint or
runtime-authority writer.

## Reproduction and remaining blocks

From `qlab/`, with OS networking denied and no installed qlab/external
PYTHONPATH, run both real Python 3.9.6 and 3.12.13:

```text
python -B -m pytest tests -q -p no:cacheprovider
python -B -m pytest tests/dynamic_factor/test_execution_accounting.py -q -p no:cacheprovider
python -B -m ruff check --no-cache <changed Python files>
python -B -m ruff format --check --no-cache <changed Python files>
```

`accounting_boundary_worker.py --case price|fee|B|model-forward|paydate|TR|rights`
executes real component rejection paths in a subprocess and observes existing
reader/worker boundary calls. These inputs are already host-bound synthetic
facts: zero calls here is not a claim that C09 worker integration is complete.
The pytest observations include actual reasons, retained facts/rights/receivables,
reader/worker counts and roles. A13/A14/A15/A16/A19 coverage belongs to this
component; whole execution-loop acceptance and runtime certification remain
with the later blocks and non-author review.
