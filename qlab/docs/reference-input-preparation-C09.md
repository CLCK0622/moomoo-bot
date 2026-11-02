# C09: independent input-manifest preparation

`execution_receipts.input_envelope.prepare_input_envelope` prepares metadata
for four named input slots: `raw`, `rights`, `adv`, `cash`. The machine schema
is `execution_receipts/schemas/input-manifest.schema.json`. Each slot binds a
fixed filename, the original file SHA, a source-receipt SHA, requested sessions,
a declared consumer and symbols. It does not read those files or validate their
economic payloads. The slot names are new component interface fields, not an
extension of the old worker's three-file allowlist.

The host separately supplies the expected manifest, checked scope/profile,
book and run identities. The existing C01/C02 profile and checked scope
validators are reused. Requested sessions must stay in that scope's train /
warmup view; every declared symbol batch passes the existing B guard. The
consumer label is a declaration, not an authorization to consume the source.
Actual payload as-of timing, raw-price basis, ADV availability, integer cash,
rights and source ownership remain the formal receiver's responsibility.

Extra fields, caller M/P/returns, missing source-receipt identities, filename
aliases, changed bindings and out-of-view requests refuse preparation. A hash
only binds declared bytes; neither matching hashes nor caller PASS metadata
authenticate a source, permission, budget or actual read DAG. No authority
reader, budget interface, installation API, data callback or executor is called.

`EVO884.PreparedExecutionInputEnvelope/v1` always distinguishes the stages:

| Field | Meaning |
| --- | --- |
| `prepared` | Only metadata structure / expected identities / declared scope passed |
| `source_acceptance` | Always `not_checked` |
| `accounting_executed` | Always false |
| `evidence_accepted` / `complete` | Always false |
| `runtime_consumable` / `certifiable` | Always false |
| `reader_calls` / `executor_calls` | Always zero |
| `accessed_roles` / `worker_roles` | Always empty |

Successful preparation returns a defensive copy, not a worker or run receipt.
C09's formal source/P4/P7 reception and C10's authorized execution integration
remain explicit outstanding items. C10's candidate caller / unique D1+D2 DAG,
joint execution traces and final integration still depend on C13. The original
`reference_inputs`, `reference_guard`, `reference_boundary`, `reference_check`,
`reference_evidence`, `reference_v3_evidence`, `reference_producer_v3` and
`fold_split` bytes are unchanged. This component neither selects a new official
entry nor weakens their existing rejections or source bindings.
Replaying an old seal only proves that its old path has not changed: this new
component and schema are not covered by that seal. Their source identities must
be included in the later authorized integration, review and final reseal.

The missing-receipt, outside-window, injection and B-no-read fixture categories
reuse the preparation-only separation from draft `2fb50b4`; its unpublished
worker/entry and freeze-pending stub were not installed. The new control is
metadata-prepared only, never execution-accepted. No additional scaffold credit
is claimed beyond the existing C09/C10 quote.

Focused verification, from the repository's `qlab/` directory with each locked
interpreter, no installed qlab / external PYTHONPATH and OS network denial:

```sh
python -B -m pytest -p no:cacheprovider -v tests/dynamic_factor/test_execution_input_envelope.py
```

The four refusal classes plus a positive control run in real fresh `-B -I -S`
processes with empty environments. Numeric-file canaries must not be opened;
worker roles remain empty. These component checks do not establish full A01,
A05/A06, A18, A21/A22/A24, real source reception or 1260-day execution.
