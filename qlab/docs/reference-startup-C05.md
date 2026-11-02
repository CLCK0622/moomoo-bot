# C05: independent training-book genesis and three-session startup

`qlab.dynamic_factor.execution_startup.StartupBook` consumes C01's exact
member definition and C02's fixed solo profile. Its identity includes the
member, frozen fold, actual attempt, definition/profile digests and the
approved v3.0.1 shared contract. Separate members, folds and attempts cannot
restore one another's book. These identities do not allocate or consume N.

The observed initial state is required in full: all frozen-universe symbols
and QQQ have integer zero inventory; cash, NAV and initial peak are E0=15000;
fees are zero, the initial latch is false, initialization_count is integer 1,
and age/origin/rights/receivables/pending orders/unknown components are empty.
Its asof belongs to the reference session immediately before the first frozen
train open. Nonzero or unknown state is rejected, never cleared to manufacture
a fresh book. The original genesis remains in every snapshot/export.

`prepare_next_open()` locks the intent using the owned prior-close NAV and
inventory, before an execution-price reader is called. It calls the existing
`execution.lock_startup_intent`; `execute_open(timestamp, reader)` calls the
same `execution.initial_build_turnover_check` used by the existing candidate
startup. Only QQQ is passed to the scoped reader. This preserves the frozen
0.40 × preceding canonical x2 NAV budget, integer decrement feasibility,
0.20 one-way cap, actual frozen fee quote, cash reserve and invested limit.
It does not implement or reuse this decrement loop as regular D1 projection.

Only the three frozen opens O0/O1/O2 can consume startup intents. Missing a
close blocks the next intent; a delayed open, repeated execution, caller target
or new startup after O2 is rejected before a reader. An unfilled startup keeps
cash and does not extend the phase. Source read errors and missing/invalid raw
prices halt the book with the unfilled intent and last known state retained.

`close_session(timestamp, raw_qqq_close, valuation)` computes a startup close
from owned cash/integer inventory and explicit known rights/receivable values.
The prior close, including E0 on day one, is the return denominator; the first
day's fee and initial cash drag are retained. It never accepts a caller NAV,
return or terminal inventory. The valuation components are required inputs,
not inferred zeros. This hook consumes already reconciled values from C04;
it does not determine entitlements, settlement, payments or fractional TR.

The `account_state` here is the startup component's cash/inventory/NAV, not a
complete execution-account declaration. Full general accounting, positions'
age/origin and risk transitions are C04/C06. `complete_account_state` and
`current_risk_state` remain null with nonempty reasons; the verified initial
risk seed is kept in `genesis`. C06 must generate the current peak/latch rather
than carrying the initial false flag as though it were a current observation.
The first regular signal/open dates are exposed on the original global clock;
this component does not produce a regular plan or execute one.

`export_bytes()` contains canonical original genesis, context and events,
not a trusted terminal snapshot. Its owner persists these bytes and an
independently accepted current SHA. `restore(raw, expected_sha256=..., ...)`
checks that receipt, replays the existing startup arithmetic, and requires all
event outputs to match byte-for-byte. An older prefix cannot replace the
current book under the accepted SHA. No N ledger, file store or installation
is opened by this module. C09 owns source reception and the current receipt;
an arbitrary caller SHA is not a production trust adapter.

## Executable specifications

All tests below use explicitly synthetic fixed prices and private data. They
do not run a registered reference/strategy, inspect real fold performance,
write authority state or claim runtime permission.

```sh
python -B -m pytest -p no:cacheprovider -v qlab/tests/dynamic_factor/test_execution_startup.py -k A07
python -B -m pytest -p no:cacheprovider -v qlab/tests/dynamic_factor/test_execution_startup.py -k A08
python -B -m pytest -p no:cacheprovider -v qlab/tests/dynamic_factor/test_execution_startup.py -k A13
python -B -m pytest -p no:cacheprovider -v qlab/tests/dynamic_factor/test_execution_startup.py
```

* A07: all four members, actual startup arithmetic over three opens, integer
  quantities and fees, cash reserve/turnover, first-day NAV/return from E0,
  warmup excluded, and a byte-persisted replay between days.
* A08: no satellite target injection, delayed or repeated opens, implicit
  execution before a locked intent, or fourth startup/topup. Reader counts
  are zero at these refusal points; all allowed numeric reads are QQQ only.
* A13's C05 portion: nonzero B inventory, incomplete inventory, old rights,
  receivables, pending orders, unknown ancestry/components or altered initial
  state refuse without modifying the declaration. The general B-first reader
  and cross-fold continuity parts remain C08/C06.
* Additional hard gates: missing valuation cannot be zero; unknown price/read
  failure retains intent and halts; member/fold/attempt reuse and stale-byte
  rollback reject; event output tampering rejects even after recomputing a
  caller digest. No externally supplied final cash/NAV is used to restore.

`startup_complete` names only this three-session component. Every snapshot
still has `runtime_consumable=false` and `certifiable=false`. Shared D1/D2,
general accounting, source reception, N/budget slots, independent review and
the final reseal remain their separately assigned blocks.
