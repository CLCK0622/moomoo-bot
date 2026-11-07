B01 reception and per-call classification

Base: a98e61362193d0549a711c6127ed4aca6d39c139. B01 only. B02 is not implemented.

The production _read_trusted_release adapter rejects trust_binding_missing. The original permission line must supply independent originals, expected identities, real reception/run time evidence and permissions. No request/path/environment override or N authority_host substitution exists. Private adapter injection tests exercise mechanism only, never real A or runtime acceptance.

receive_release_context(policy=..., a_raw=None) derives the metadata A from R/P, adoption, publication, eight original acceptance receipts, v21 CSV/CMI, the annotation and host acceptance/time bindings. Each consumer rechecks originals. Restoring an existing A compares its exact bytes; no consumer/time/PID re-signing. Bindings are data, not authority. ReleaseContext cannot be constructed from wire or pickle.

A schema is EVO884.BReleaseAcceptance/v1. Its status remains seal_pending, runtime_consumable=false, certifiable=false. No real production A is formed. The original S artifacts are immutable.

The original v3 policy common-profile hash differs from the D12 v3.0.1 profile in R. These remain separately bound, never equated.

noncash_v3 gains only one precise import and the two same-object exports. Original functions and zero_exposure remain byte-identical. scope_proof adds the exact b_release_context edge plus its separately inspected module imports.

## Dushui call sites

The two 16-call tables were approved in Gongbu comment
01a1b78f-16a1-7a28-83c1-f8107aef3a92. Classification is determined by the
guard/request's formal BR1 schema or release fields, never by the presence of a
context or expected bytes. Formal branches pass the original owner's context
and expected bytes; diagnostic branches retain None/None. Context comes only
from the owning object or explicit trusted-host parameters, never request JSON.
Formal requests without context must refuse B.release_context_required.
This table does not implement B02.

| File:line | Caller -> callee | Classification |
|---|---|---|
| `qlab/qlab/dynamic_factor/valuation.py:186` | `integer_cash_valuation -> assert_consumer_symbols` | Formal if release_requested; original diagnostic None/None |
| `qlab/qlab/dynamic_factor/valuation.py:192` | `integer_cash_valuation -> assert_consumer_symbols` | Formal if release_requested; original diagnostic None/None |
| `qlab/qlab/dynamic_factor/k5.py:214` | `k5_dependency_check -> checked_guard` | Formal if release_requested; original diagnostic None/None |
| `qlab/qlab/dynamic_factor/k5.py:215` | `k5_dependency_check -> no_dependency_receipt` | Formal if release_requested; original diagnostic None/None |
| `qlab/qlab/dynamic_factor/k5.py:227` | `k5_dependency_check -> acquisition_check` | Formal if release_requested; original diagnostic None/None |
| `qlab/qlab/dynamic_factor/reference_noncash.py:56` | `origin -> checked_guard` | Formal if release_requested; original diagnostic None/None |
| `qlab/qlab/dynamic_factor/reference_noncash.py:118` | `numeric_read -> assert_consumer_symbols` | Formal if release_requested; original diagnostic None/None |
| `qlab/qlab/dynamic_factor/reference_noncash.py:125` | `numeric_read -> economic_read_receipt` | Formal if release_requested; original diagnostic None/None |
| `qlab/qlab/dynamic_factor/reference_noncash.py:212` | `validate_packet -> checked_guard` | Formal if release_requested; original diagnostic None/None |
| `qlab/qlab/dynamic_factor/reference_compile_v3.py:19` | `seal_scope -> checked_guard` | Formal if release_requested; original diagnostic None/None |
| `qlab/qlab/dynamic_factor/reference_compile_v3.py:87` | `compile_panel -> checked_guard` | Formal if release_requested; original diagnostic None/None |
| `qlab/qlab/dynamic_factor/reference_compile_v3.py:100` | `compile_panel -> assert_consumer_symbols` | Formal if release_requested; original diagnostic None/None |
| `qlab/qlab/dynamic_factor/reference_compile_v3.py:113` | `compile_inputs -> checked_guard` | Formal if release_requested; original diagnostic None/None |
| `qlab/qlab/dynamic_factor/reference_compile_v3.py:114` | `compile_inputs -> assert_consumer_symbols` | Formal if release_requested; original diagnostic None/None |
| `qlab/qlab/dynamic_factor/reference_day_inputs.py:135` | `read -> assert_consumer_symbols` | Formal if release_requested; original diagnostic None/None |
| `qlab/qlab/dynamic_factor/execution_receipts/input_envelope.py:122` | `_prepare -> assert_consumer_symbols` | Formal if release_requested; original diagnostic None/None |

## Yingshan original classification

Use the attached unchanged eight-call-classification-DRAFT.csv/json from EVO881-B-on-R-df91ea1.zip (96eaa404d7f4bf96a43a4c623fc7885130fc4e8ad42aec55355e6a5e2ed61df1). All 16 call-site source SHA values match this base. Four explicit checker/checked bridge sites are formal; RiskBook.__init__:302 and RiskHistory.__init__:79 remain EXISTING_DIAGNOSTIC_ONLY, including in B02. Ten remaining sites propagate context only for guard/request-classified formal calls, retaining original diagnostic None/None otherwise.

execution.py is excluded. Any additional original-file requirement must be reported before edits. B02 starts only after B01 acceptance.

## Closeout observations and unresolved crossover rule

The existing execution_cash.CashProof.release_requested returns true when context
or expected bytes are supplied, even with a diagnostic guard. Its current
release_guard then invokes the common checker and refuses scope_mismatch.
The refusal prevents promotion, but the classification itself contradicts the
guard-only rule. No product change to the peer's eight files is included here.
Interface v1.0.2 section 4 preserves diagnostic scope but does not explicitly
choose whether surplus context/expected bytes must be ignored or rejected.
That choice and ownership of the bridge correction require upstream clarification;
the diagnostic-with-context test records the present safety outcome only.

The added b_release_context.py replay grant is an exact full-SHA entry in
REPLAY_FIXED_FILES. The audit hook and all other grants are unchanged.
The old receipt success assertions run against the fixed f827776 Git object;
absence of that object fails. A separate unchanged-script replay asserts all
306 current-source calls refuse before readers or child workers. Fixture
manifest and the three original file identities remain untouched.
