# Reference execution v3.0.1

C01 defines the four members through `reference_definition_v301`:
`reference_definitions()` returns the closed, ordered family;
`member_definition(member_id, *, execution_role)` binds one member;
`validate_member_definition(packet)` rejects alterations and extra fields.
The packet schema is `EVO884.ReferenceMemberDefinition/v1`.

The existing 3.0.0 registry and definition manifests are read with their
existing byte SHA checks. Their four IDs, formulas, H10, L20, null seeds,
family profile identities and return roles are unchanged. The new envelope
binds these definitions to the three approved v3.0.1 artifacts in
`dynamic_factor/fixtures/execution-v3.0.1`. Each artifact is checked against
its full raw-byte SHA before use; no caller supplies a replacement profile.

For both MREF members the family profile remains `META_EVAL_V3`, while
execution uses `CANDIDATE_PROBE_V3` and role
`independent_meta_reference_probe_component`. The current META policy,
pool and orders are not an alternative execution role.

## Acceptance coverage

Run with the repository's locked Python environment, `PYTHONPATH=qlab`:

```
python -B -m pytest -p no:cacheprovider -v qlab/tests/dynamic_factor/test_reference_definition_v301.py
```

* A01 (definition portion): four exact IDs, rules, seeds, roles and approved
  shared-contract/profile identities; corrupt artifact bytes reject.
* A03: unknown members, wrong F2/F4 execution roles, altered formulas,
  horizon/lookback/seed/type, extra current-pool data or changed bindings reject.

This is definition preparation, not an execution, runtime receipt, N event,
or permission to run. `runtime_consumable` and `certifiable` remain false.
A01's full executed-family proof also needs C03/C06/C10 and later reception;
this block does not claim that proof or produce market returns.

## C02: fixed solo profile

`reference_profile_v301.solo_profile(definition)` returns the closed
`EVO884.ReferenceSoloProfile/v1` packet; consumers validate it using
`validate_solo_profile(packet)` before constructing a plan. The common
profile is preserved verbatim. The registered solo execution contract
overrides its current-META selection/gain rules at the execution boundary:
`tilt_fraction=0.20`, `DSR_admission=false`, `decay_pool_selection=false`,
`voluntary_gain_cost_gate=false`. These are explicit settings, not defaults
derived from a current pool. The common META quarter-cluster budget formula
does not apply to these solos. All other integer-share, cost, age, turnover,
startup, price-basis, B/E and isolation constraints remain shared.

`shared_planner` names `/D1` and `/D2` in the same frozen machine contract.
C03/C06 supply their single implementation; this block implements neither
quantity projection nor risk inheritance. The two raw artifact hashes in
the packet identify frozen inputs, while `profile_sha256` identifies the
member-specific resolved envelope; it is not a new frozen profile identity.

```
python -B -m pytest -p no:cacheprovider -v qlab/tests/dynamic_factor/test_reference_profile_v301.py
```

A01's profile portion checks all four members against the same constraints
and planner contract. A04 rejects theta 0.05, changed/missing overrides,
changed shared constraints, extra META pool data and recomputed-digest
forgeries. Plan execution and full A01 reception remain later blocks.
