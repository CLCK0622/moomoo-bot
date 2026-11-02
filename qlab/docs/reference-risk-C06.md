# C06: one D2 implementation and continuous account boundary

`execution_risk.RiskBook` is the immutable close view used by candidate solo,
the four registered independent references, and actual META.
`execution_risk_history.RiskHistory` owns each book's ordered actual fills and
verified closes. It generates age, cooldown, peak, latch and pending necessary
exit evidence. It does not choose reference fills, price transactions, change
cash, calculate fees, infer entitlements or place an order.

The frozen shared D12 SHA is
`f7a0623da88a7e2874ef5e372750ad04a1edca9796acc0c3fee02616f766a496`.
The exact C06-CLOCK adopted protocol is included unchanged, SHA
`8cd32345adb5ebe16cb9020687091532c46f803f046d6c1527eeedee41407a5a`.
`adopted_clock_binding(*, expected_ruling_sha256)` checks the original bytes
before projecting the clock parameters. All constructors require the clock,
its host-expected digest and adopted SHA. Rehashing a draft, substituting an
entry age, removing the file or altering its bytes fails. There is no default.

## Host and C08 interface

`RiskHistory` requires `book_id`, `scope`, complete zero `genesis`, its expected
SHA, the existing B guard, and the three clock parameters above. Scope contains
exactly `kind`, `scope_id`, `member_id`, `fold_id`, `attempt_id`,
`execution_role`, `recipe_id`. Each independent training member/fold/attempt
has a separate identity and cannot migrate into another fold. A stitched book
starts only before fold 0; `advance_fold(fold_id, *, expected_snapshot_sha256)`
requires adjacent folds and the previous fold's last verified close. It retains
all account/risk state. `continue_forward(*, expected_snapshot_sha256)` carries
the terminal stitched book; it cannot construct a new forward genesis, extend
the registered calendar, or grant a real forward run permission.

`snapshot()` returns `EVO884.CloseRiskSnapshot/v1`; a C08 consumer can create
the same immutable `RiskBook` from its retained host-bound state, prior risk,
fees and exact clock binding. Its `required_m(signal, *, expected_book_id,
expected_close_session, expected_snapshot_sha256,
expected_original_state_sha256, expected_signal_sha256)` returns
`EVO884.RequiredM/v1`. Signal has exactly `book_id`, `signal_session`,
`execution_session`, `ranks`, `origin_context`. META context binds its original
selection-layer source SHA, signal close and permissions. Solo context is null;
solo references cannot read the current META pool.

The **original state SHA** covers every retained account field, including
generated `_risk_clock`. The **snapshot SHA** separately covers state, previous
risk, `fees_x2`, scope, date and clock. Fees stay outside the original state;
they are not silently added to a C08 initial-state declaration. Both snapshots
and M envelopes explicitly require `age_clock`, `cooldown_boundary`, and
`ruling_sha256`. Their closed 22/20-field root JSON Schemas are in
`fixtures/execution-risk/close-risk.schema.json` and `required-M.schema.json`.
Unknown states retain these keys with null values/reasons where unavailable.

M means **持仓股数（工作假设，待翰林院确认，见 CORE-READBACK M-01）**:
the nonnegative integer inventory after necessary actions; neither an upper
bound nor a signed order delta. Working pointers are D12
`/D1/projection/1`, `/D1/target/required_exit_cannot_be_undone`, and
`execution.py:490–498`. The schema records the pending contract confirmation.
`complete` describes the D2 risk calculation only. C03 still must verify the
whole necessary net plan with prices, fees, cash, ADV and turnover; this output
is not a filled/feasible execution or permission to consume market data.

Expected hashes are host capabilities bound to accepted original sources, not
wire claims that a caller can promote by rehashing. C09 supplies that reception
boundary. Unknown NAV, rights, origin or discontinuous clocks produce R2 and
null M before any numeric consumer. The pure module has no reader or worker
callback. Runtime and certification flags remain false.

## Actual daily transitions and recovery

`prepare_open(signal, *, expected_signal_sha256, expected_snapshot_sha256)`
locks one DAY intent; the method does not execute it. Regular signal positions
remain 5, 10, 15, ... on the original global clock. Account latch/max-age exits
can require the next available open. Logical required exits are retained;
each further actual order must be freshly issued. Closing the day expires the
active DAY order and never rolls it automatically to tomorrow.

`observe_close(date, accounting, fills, *, expected_accounting_sha256,
expected_fills_sha256)` consumes accepted C04/C09 actual declarations. The
accounting keys are exactly `asof`, `inventory`, `cash`, `nav`, `fees_x2`,
`rights`, `receivables`, `pending_orders`, `unknown_components`,
`initialization_count`. A fill has exactly `fill_id`, `order_id`,
`source_sha256`, `intent_sha256`, `intent_signal_session`, `execution_session`,
`symbol`, signed integer `quantity`, `origin`. Inventory changes must equal
the actual fills. C06 keeps declared cash/NAV/fees and never recomputes them
under an unapproved fill/settlement model. C05's actual QQQ startup closes can
feed this same daily boundary, with no second capital initialization.

First actual held close is age 1. Adds, partial reductions and fold labels do
not reset its entry. Partial max-age exits keep aging. Only the final verified
flat fill on day e sets the anchor: `max(0, 5 - (i-e))` at close i. Five pairs
are blocked; expiry alone adds no regular decision. QQQ retains its base
policy and has no satellite clock. Peak/latch use exact rational comparisons;
`drawdown` is an exact rational string (for example `3/20`), avoiding a mutable
Decimal context or a new monetary rounding choice. A triggered latch never
clears in that book, even across folds or recovery above the old peak.

All close declarations are captured in order before validation. Failure keeps
the previous state and logical intents, marks the receipt incomplete and keeps
the rejected declaration/reason. A verified correction must cover that same
next close; skipping the gap cannot resume the book. No old state/rights are
erased to manufacture a new zero origin.

`export_bytes()` contains complete original genesis, events, declarations,
source SHA and terminal receipt. `restore(raw, *, expected_sha256,
expected_book_id, expected_scope)` requires the external **current** byte SHA
and original creation scope, replays the whole history and compares every
output/rejection and final bytes. Rehashed terminal claims do not pass.
Persistence/current-receipt ownership belongs to C09; C06 creates no installed
database, authority chain or deployment root.

## Verification and remaining blocks

```
python -B -m pytest -p no:cacheprovider -v qlab/tests/dynamic_factor/test_execution_risk.py qlab/tests/dynamic_factor/test_execution_risk_history.py
```

A09 covers independent training/stitched reset rejection, all 77 fold labels,
same-book forward handoff, replay and retained account state. A13 covers
unknown/erased original state and zero-origin/B rejection. The adopted clock
tests cover 1/5/10/20, all five cooldown pairs, partial/unfilled exits, fresh
DAY issuance, the next original grid point, all four registered references,
missing/draft/mismatched adoption, and original-file drift.

These are synthetic account/fill declarations. There was no market strategy,
reference performance or forward execution. C03/C04/C07/C13 and actual C09
reception remain separately assigned. Pending EXEC-CLOSURE monetary, reference
fill, settlement, lifecycle-clock and phase rules are not implemented or
silently defaulted here; an accepted actual declaration is not a new model for
generating those values. Actual META pool chronology remains upstream.
