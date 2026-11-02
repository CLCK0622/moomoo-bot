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
