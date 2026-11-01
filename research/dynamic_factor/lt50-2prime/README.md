## LT50 preparation correction (2′)

Baseline: `6fa70f6c2f5d3599acb31e6063d78611c206fa7a`.
Authority: EVO-884 comment `01a1984f-ecb3-7b6b-b5c9-3bbc97f8bb53`.

The two production decisions below accept a nonempty, verified LT50 day for
reference input preparation. They do not grant new-tilt admission or generate
M, orders, transaction costs, cash, NAV, cross-fold state or reference returns.
BE-01, the B release restriction and the fixed registered catalog hash are
unchanged. This correction does not create a trial or consume a budget.

### Statement comparison

`qlab/qlab/dynamic_factor/reference_compile_v3.py`, `seal_scope`:

| Statement | Baseline | Correction |
| --- | --- | --- |
| Every training day must have a verified quantity state | `day["quantity_state"] == "VERIFIED_GE50"` | `day["quantity_state"] in {"VERIFIED_GE50", "VERIFIED_LT50"}` |
| Verified count equals the eligible list length | Implicit in the source derivation | `day["verified_count"] == len(day["eligible"])` |
| Nonempty eligible list | Implicit in GE50 | `bool(day["eligible"])` |
| Combine over all days | `all(... for day in days.values())` | Same `all`, with the three conditions above joined by `and` |
| Output eligibility for runtime/certification | Both `False` | Both `False`, unchanged |

`qlab/qlab/dynamic_factor/reference_v3_scope.py`, `validate_scope`:

| Statement in the rejection predicate | Baseline | Correction |
| --- | --- | --- |
| Unknown/unrecognized quantity state | `day["quantity_state"] != "VERIFIED_GE50"` | `day["quantity_state"] not in {"VERIFIED_GE50", "VERIFIED_LT50"}` |
| Quantity floor | `len(eligible) < 50` | `not eligible` |
| Count agreement | `day["verified_count"] != len(eligible)` | Unchanged |
| Any failing condition rejects | Three conditions joined by `or` | Unchanged |
| Refusal reason | `reference.quantity_unknown_or_insufficient_no_QQQ_substitution` | Unchanged |

QQQ substitution remains rejected by the preceding exact universe/state/eligible
derivation check (`reference.same_E_t_required`). The same QQQ benchmark input
can still be read for its existing benchmark role; it cannot replace E(t).

### Synthetic protocol and refusal coverage

The positive uses a genuinely derived one-day synthetic scope with 49 eligible
members. It then uses the existing counterfactual wire helper to expand the
scope across the frozen 1260 training and 252 warmup dates. This expansion tests
the compiler/isolated-worker protocol; it is not actual qualification evidence,
an adopted mask, a reference run or market performance.

The host panel reader runs 74,088 times (49 × 1512). The worker reads exactly
`benchmark`, `panel`, `profile`, once each, and prepares all four registered
members. It reports `complete=true`, `returns=null`, `sr=null`,
`runtime_consumable=false`, `certifiable=false`, with reason
`reference_runtime_evidence_pending_EVO886_EVO891`. `new_tilt_allowed=false`
and `required_M_valuation_cash_fees_still_required=true` remain unchanged.

| Negative class | Refusal reason / observation |
| --- | --- |
| UNKNOWN day | `reference.quantity_unknown_or_insufficient_no_QQQ_substitution`; host/worker reads 0 |
| Verified count disagrees with eligible list | Same quantity reason; host/worker reads 0 |
| Zero eligible members | Same quantity reason; host/worker reads 0 |
| QQQ substituted for eligible members | `reference.same_E_t_required`; host/worker reads 0 |
| Missing registered family member | `reference.member_not_registered_or_incomplete`; worker never reports preparation complete |
| Missing or nonfinite returns | `reference.runtime_B_release_and_actual_proofs_missing`; missing/null/NaN/Inf claims cannot pass the current v3 runtime evidence gate |
| Downstream promotes preparation `complete` to reference usability | Passing the actual preparation report to the public runtime checker yields `reference.v3_runtime_schema_or_old_V_forbidden` |

The missing/nonfinite cases do not claim an executed v3 finite-statistics path:
the existing gate refuses before trusting performance claims because B release,
actual runtime proofs and complete N are still missing. No mock, substitute
simulator or new v3 return validator bypasses this gate. The full suite also
retains the historical finite-return validator regressions.

### Reproduction

Run from a new clean clone of the delivered commit, with output outside it:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=qlab:. "$PYTHON" -B -m pytest qlab/tests -q --tb=short -rs -p no:cacheprovider
PYTHONPATH=qlab:. "$PYTHON" -B qlab/tests/dynamic_factor/lt50_harness.py --workdir "$EMPTY_OUTPUT_DIR"
ruff check --no-cache qlab/qlab/dynamic_factor qlab/tests/dynamic_factor
ruff format --check --no-cache qlab/qlab/dynamic_factor qlab/tests/dynamic_factor
git status --porcelain
```

The extended harness preserves the original fixed ten and every historical
revision case, and adds `lt50` with one positive and seven negative classes.
It has one root `dependencies` field. Canonical SHA-256 excludes that entire
field and hashes UTF-8 JSON with sorted keys, `ensure_ascii=False`, compact
separators and no trailing newline. Full SHA hashes the exact emitted bytes.
Both interpreter reports must have identical canonical bytes; interpreter
version is the only permitted full-output difference.

`seal.json` records the actual source/access-boundary reseal. Changing the
compiler and scope validator touches that boundary; this is a reseal, not an
“untouched” claim. No reference performance was generated before or after it.
`decision-comparison.json` contains verbatim statements and hashes for the
two changed decisions and the two protected, unchanged release restrictions.
