C07 produces a historical training readout from one owned C04 account. It does
not run a strategy/reference, acquire prices, admit a source, authorize a worker,
or certify a forward account.

`TrainingReturns(account, *, expected_account_sha256, execution_binding)` must
be constructed before any accounting declarations. Its plan binds the original
E0 zero-inventory snapshot, member/fold/attempt, full train calendar, independent
C06 clock and the sole formal EXEC-CLOSURE adoption. There is no caller-selected
terminal date or injected strategy-return vector. `evaluate(benchmark, *,
expected_benchmark_sha256)` consumes only the owned C04 closes. The benchmark
has the closed `EVO884.BenchmarkDaily/v1` schema: `schema`, `dates`, `values`,
`basis=analytical_TR`, `symbol=QQQ`, `role=B1`, `source_sha256`; C09 must accept its source before binding
that object. Its source hash alone is not a permission attestation.

The shared `fold_split.train_dates` returns all 1260 training sessions through
`history_end`. `Conventions.fold_manifest().train_end` is the *label maturity*
cutoff, 21 sessions earlier; it is not the accounting terminal. The C06 training
state boundary now uses `history_end` too. No holding-age, cooldown, origin,
decision-grid, peak/latch rule or frozen date bytes change. Beyond that terminal
C06 still refuses a training book. This boundary correction must be reviewed
with C07; it is not silently inherited from the earlier C06 review.

Each daily ratio is recomputed from consecutive C04 canonical x2 NAVs, with
15000 as the first denominator. The first startup fee and cash drag are included.
Previous-NAV links, retained ratio, accumulated fees, book/closure identity,
known rights and the identical-order x1 column must reconcile. No missing date,
failed state, nonfinite return or constant active-return series is dropped or
patched. Failure keeps the original account and close count and returns null
strategy/active/statistical fields with a reason. Family completeness, V and N
remain the existing separate gates; this single-book readout does not certify
any of them.

At the fixed final raw close, a separate historical reference-settlement row
sells the retained integer holdings at those *same C04-owned close prices* and
quotes the unchanged x2/x1 engine on separate closing orders. Opening orders
are not netted against these closing orders. Only the terminal return bears
these charges. Known unpaid cash receivables retain every field and remain
nonspendable; unknown price/fee/right/NAV refuses the readout. x1 replays the
same integer closing orders, with no second optimizer. Repeated evaluation
reuses the identical terminal settlement; it cannot accumulate another charge.

This terminal settlement is the historical metric's owned accounting row. It
does not rewrite the original C04 mark-to-market closes, fabricate a broker
fill, reset/restore a continuing C06 risk book, attest cash availability, or
feed the historical terminal/x1 state back into a continuing D1/D2 account.
`terminal_settlement()` and `export_bytes()` expose this posted, idempotent
historical journal for reconciliation. It includes full integer sell orders,
gross proceeds, cash/NAV, cumulative fees, and all original unpaid receivables;
it is not a forward fee reserve with unliquidated positions. The readout explicitly
reports `execution_verified=false`, `spendable_account_cash_attested=false`,
`continuing_account_modified=false`, `runtime_consumable=false`, and
`certifiable=false`. Forward horizon liquidation reserves are a distinct rule
and are not enabled by this training-only interface.

The existing daily `pipeline.moments` supplies the active SR; annual IR is
sqrt(252) times daily SR and A is 252 times the active daily mean, separately
for canonical x2 and the identical-order x1 readout. Ratio statistics
keep their existing numeric interface per EA.N1. Monetary state, fees and the
terminal settlement use exact canonical decimal amounts. Fee formulas, floors,
parameters, accepted oracle bytes and both formal adoption pins remain intact.

Synthetic regression:

```text
python -B -m pytest tests/dynamic_factor/test_execution_returns.py -q -p no:cacheprovider
```

This exercises a complete synthetic 1260-day C05→C04→C06 journal, including an
original mapped QQQ cash entitlement retained unpaid at the terminal. It is
not a historical strategy/reference performance run or a C09 reader/worker
acceptance test. The C08 exact-money/CashProof connection is inherited from
its author’s separate parent commit; this change does not modify that path.
