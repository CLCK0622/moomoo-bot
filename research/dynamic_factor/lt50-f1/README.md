## LT50 scope quantity repair (B18 F1)

Parent: `d25fa780394de8bcbc5f1bd3bbb7586107bddeff`, PR #19.
The earlier `../lt50-2prime/seal.json` remains the historical source snapshot for
that parent. This directory seals the repaired source boundary.

Before either the host panel callback or the worker's `read_inputs`, the shared
`reference_v3_scope.validate_scope` recomputes L from `VERIFIED_USABLE` facts and
U = L + the number of `UNKNOWN` facts. The existing rule is GE50 for L >= 50,
LT50 for U < 50, otherwise UNKNOWN. UNKNOWN and empty eligibility reject.
Declared counts must be integers and equal the recomputed values; the declared
state and boolean `new_tilt_allowed` must also agree. LT50 requires exactly
`False`. A numeric permission claim, including `5e-324`, rejects before reads.
This input contract has no numeric planner increment; no new planner, M/cash/NAV
simulation or actual trading behavior is introduced by checking the permission.

Every quantity rejection retains the original reason code followed by JSON with
the date, reported fields and independently recomputed fields. For example,
49 usable plus 1 UNKNOWN recomputes U=50/UNKNOWN, even when all caller-owned
digests have been re-signed and the declaration says LT50.

The three audit counterexamples and three variants are exercised through the
real host/isolated-worker boundary. Additional tests reject fractional summary
types, mismatched upper bounds and a numeric zero passed as a boolean permission.
The original LT50 positive and seven negative classes remain; their reason-code
assertion now permits the diagnostic suffix. Legal 1/49/50-member scopes and
mixed GE50/LT50 windows remain preparation-only controls.

`seal.json` records current lineage/source hashes, unchanged import graph and
three-role read whitelist, and byte-identical protected B-release and fixed
catalog restriction statements. No catalog, directory, B membership or static
whitelist is expanded. This is an author source seal, not independent acceptance
or proof of historical runtime timing. Runtime/certification remain false.

Use a clean clone with an OS offline guard and output outside the checkout:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=qlab:. "$PYTHON" -B -m pytest qlab/tests -q -rs --tb=short -p no:cacheprovider
PYTHONPATH=qlab:. "$PYTHON" -B qlab/tests/dynamic_factor/lt50_harness.py --workdir "$EMPTY_OUTPUT_DIR"
ruff check --no-cache qlab/qlab/dynamic_factor qlab/tests/dynamic_factor
ruff format --check --no-cache qlab/qlab/dynamic_factor qlab/tests/dynamic_factor
```
