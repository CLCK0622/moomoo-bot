# Execution receipt compatibility repair

F-LEGACY-01 restores `noncash_v3.py` to the exact main `f827776` bytes. Existing
`zero_origin` and consumer receipts bind its entire module through `code_sha`;
extracting a helper changes that identity even if its predicates are identical.
The original frozen 34-actor input is replayed directly, without resigning it.

The execution-only `execution_exposure.verify_execution_exposure` separately
implements the B inventory, rights and pending-order checks. Its caller
`execution_cash.check_cash_state` first validates the full scoped exact-money
state and owned CashProof, then supplies a temporary cash-classified view.
Original state, amounts, receivables and their identities are retained. No money
is converted to float. Numeric-domain tests compare acceptance and exact refusal
codes against the original legacy `zero_exposure`, including multiple-error order.
The new module is outside the existing static scope proof; that proof and its
whitelists are unchanged. This is not C13 integration or source certification.

S-CASH-01 puts CashProof type/identity inspection inside RiskHistory's existing
refusal/declaration path. Invalid dict/bool inputs now produce a recorded
`ValueError` refusal, as missing/stale proof already did, instead of leaking an
unrecorded AttributeError. The prior state/date remain; completeness is false.
An explicit invalid-type event marker permits replay without serializing an
arbitrary host object. Valid proof receipts retain the existing SHA field.

Focused regression: `python -B -m pytest tests/dynamic_factor/test_execution_exposure.py -p no:cacheprovider`.
The frozen reviewer subprocess uses its original `--expect-legacy-compatible`
assertion. EA.N1 fees, golden bytes, legacy state validation and runtime gates
are unchanged. Source admission and final non-author review remain separate.
