# C08: checked day inputs and the shared C06 M

`reference_day_inputs.BookScopedInputs` binds the unchanged checked reference
scope/profile, book identity, full original account declaration, original zero
origin receipt and the host-expected state SHA. The current declaration is
retained without dropping fields, inventory, rights or history clocks.

The optional host-only constructor keyword `cash_proof` accepts the owned
C04 `execution_cash.CashProof` capability. C08 calls the shared
`execution_cash.check_cash_state` directly and passes the identical capability
to `RiskBook`; it has no money parser, receipt adapter or cash classifier.
C04/C06 canonical decimal-string cash and NAV are retained byte for byte,
without a float projection. A retained cash receivable requires its original
C04 close proof, bound to the complete monetary state, B guard and book.
Missing, wire-dictionary, boolean, stale or other-book proofs refuse before M
or a numeric callback. Noncash rights and unknown state still refuse. Legacy
`state_v2.necessary_state_known` and its existing consumers are unchanged.
This capability does not certify actual source reception or open a runtime
gate. An original zero-origin receipt remains a separate declaration.

`read(date, consumer, symbols, reader, *, ...)` requires all the following host
inputs, with no defaults: `risk_scope`, `close_session`, `prior_risk`,
`fees_x2`, `clock_binding`, `expected_prior_risk_sha256`,
`expected_clock_binding_sha256`, `expected_ruling_sha256`,
`expected_snapshot_sha256`, `signal`, `expected_signal_sha256`.
They are the public C06 constructor and `required_m` parameters. There is no
serialized M, quantity callback, alternative risk engine or result adapter.

The whole requested symbol batch passes the original B guard before C06 or
any numeric callback. Then the original role scope is checked: score/label/
calibration use E(t), and holdings/order/valuation can retain a clean original
holding that left E(t), plus QQQ. UNKNOWN/empty scopes and altered three-state
claims still use the existing refusal predicate. GE50/LT50 permissions are
reported unchanged; C08 does not generate a new tilt or select an order.

C08 directly constructs `execution_risk.RiskBook` with its own checked B,
full bound state and book ID, and the verbatim risk parameters above. The risk
member, recipe and execution role must match the frozen reference definition.
Signal execution day T must equal the requested day; C06 separately checks
the preceding close s, adjacent calendar, host-expected snapshot, original
state, prior risk, signal and adopted clock. The original state SHA and risk
envelope SHA are distinct; x2 fees remain outside the original state. No
binding is repaired, silently defaulted or inferred from a wire hash.

Only `RiskBook.required_m` generates M. Its complete 22-key receipt, reasons
and M are passed through without rewriting. Hanlin's
`EVO883-M01-contract-ruling-v1.0.0.json` confirms existing contract semantics:
M is the planned final holding after necessary actions, never a filled sale,
quantity cap or signed order delta. It adds no rule or design charge. C06's
schema description update remains with its original author; C08 neither
rewrites that receipt nor performs quantity arithmetic. A failed C06
calculation returns no numeric values,
`required_M=null`, zero reader calls and empty accessed roles. The source
declaration is retained. A missing required keyword cannot select an older
unguarded read path.

`EVO884.ReferenceInputRead/v1` binds actor/book, T/s, profile/scope, original
state/risk scope/snapshot hashes, the complete C06 receipt and actual per-role
numeric read receipt/call count. `inputs_complete` refers only to this requested
input batch and M. It is not a complete day's accounting or a feasible/fill
plan. `accounting_required=true`, `accounting_executed=false`, `complete=false`,
`runtime_consumable=false`, `certifiable=false` remain explicit even when M
and the requested numeric inputs are available; no worker is started.

For LT50 the same real C06 required exits still apply. Original inventory,
QQQ, cash, NAV, fees, prices and rights remain necessary for C04/C07; M does
not execute a sale or erase a holding. UNKNOWN does not become an empty pool,
fake LT50, zero state, QQQ substitute or removed calendar row.

C09 still must verify the actual source ownership/current snapshot, zero
origin, bound reader and permissions. A legacy-format zero-origin receipt and
the richer C05/C06 genesis are separate original declarations; this module
does not project or rewrite either to manufacture provenance. Synthetic host
hashes/receipts in tests demonstrate mechanics only. C03/C04/C07/C09/C10 remain
separately assigned, and no runtime or budget gate is opened here.

Focused regression command (use each locked interpreter with OS external
network denial, bytecode/cache disabled):

```sh
python -B -m pytest -p no:cacheprovider -v qlab/tests/dynamic_factor/test_reference_day_inputs.py
```

A10 covers unchanged GE50/LT50 and four profiles, real same-source M, original
inventory retention and LT50 required exits. A11 covers missing M inputs,
actual C06 null/refusal and invalid numerical inputs. A12 retains all original
three-state forgeries/UNKNOWN/empty refusals. A13 covers six consumers' whole
batch B-first with both M and reader counts zero, R2/state erasure, member/day/
history drift, and actual RiskHistory snapshot/M equality. Full accounting and
real reception are not claimed by this component regression.

`tests/dynamic_factor/test_reference_day_cash.py` adds the C04 integration:
actual synthetic-fact `ExecutionAccount.close_session` issues the proof,
`RiskHistory.observe_close` advances the same account, and C08 consumes the
same snapshot and complete 22-key M receipt. It also checks exact decimal
retention, noncanonical-money refusal, proof substitution/drift and all six
consumers' B-first ordering. These are component fixtures, not a real strategy
or reference-performance run.
