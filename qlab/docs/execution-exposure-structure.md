F-B-EQUIV-01: preserve the fixed legacy B segment

The execution entry keeps its existing exact-money structural validator.
Its subsequent B predicate now preserves the original `zero_exposure` body,
after the original numeric-only validator, including set construction,
subscription, short circuit, iteration and refusal order. It does not replace
host containers with ordinary dicts, call `.keys()` in place of iteration,
convert amounts or narrow acceptance to exact dict.

The fixed reference is `noncash_v3.py` from main
`f827776c7a4b3f270ad87367191b06314a7f3c28`, SHA256
`08301f9d7a5ad5bdcd2fcaae8422dec9896e18b59d197a9c183e81057e106744`.
Its bytes are retained as a new test fixture. `noncash_v3.py`, `state_v2.py`,
fee code, parameters and existing oracle/golden bytes are unchanged.

The structural test compares the actual execution function's argument AST
and complete B-body AST with this fixed source. Only the function name,
comments/docstring, source positions and explicitly separated first validator
are excluded. Business operations, constants, expressions and statement order
remain in the comparison. Four mutation checks exercise the structural gate.

The differential tests cover 130 explicit combinations of initial/ongoing,
B/unknown/child/undeclared inventory and hostile keys/iteration/items/state
access. They compare the B result and container-operation trace, then the
actual `check_cash_state` entry's acceptance, exception type, reason and first
stop, and assert retained state. Existing 54 variants and pending/refusal
priority tests remain. The two reviewer counterexamples and 296 observations
are retained with original script/observation bytes and SHA pins.

This is bounded differential coverage plus structural consistency, not proof
of arbitrary Python objects under every possible side effect. The two state
validators intentionally have distinct domains: execution accepts canonical
decimal strings; legacy remains exact int/float only. The review's four
huge-integer OverflowError versus recorded R2 differences remain explicitly
locked to the original observations. Neither prefix is changed by this fix.

Run from `qlab/` under the existing OS offline guard with native Python 3.9.6
and 3.12.13:

```sh
python -B -m pytest tests/dynamic_factor/test_execution_exposure_structure.py \
  tests/dynamic_factor/test_execution_exposure.py -q -p no:cacheprovider
```

The independent counterexample must still fail on old `50be0c0` while the
fixed entry agrees with the original main predicate. Frozen 34-actor receipt
replay, full native tests and unchanged fee/oracle checks accompany delivery.
No C13 binding split, static scope expansion, source resigning, runtime
permission or authority write is included.
