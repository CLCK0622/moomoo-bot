# EVO-884 first-stage authority readers

Implementation base: `4cdfcbc0726abeadfff9e143b49281fab815bc43`.
Approved design: v3.1.1 plus T1 ruling v1.0.0. The copied schemas retain their
approved design-baseline constant `6fa70f6`; actual deployment identity is a
separate bound field. No deployment, installation, external anchor publication,
authority append, budget call or runtime-gate write is implemented here.

The one production trust-source adapter refuses until independently approved
original deployment and permission inputs exist. Private tests replace only
that adapter to exercise the real receivers; they do not prove installation,
complete real-world N, or runtime authorization.

The only formal entrypoints are:

```python
receive_arm_n(approval_bytes, projection_bytes, *, host_context,
              installed_snapshot, run_pin, arm_tag=MISSING)
bind_formal_n(*, host_context, request_metrics, installed_snapshot,
              entrypoint, run_pin, arm_tag=MISSING, candidate_ledger=None)
verify_installation_readonly(*, host_context, runtime_module_path,
              installation_receipt_bytes, published_anchor_bytes,
              acceptance_bytes)
```

Their closed roots are respectively `EVO884.NAcceptanceReceipt/v3`,
`EVO884.FormalNBinding/v3`, and `EVO884.InstalledAuthorityReceipt/v3.1`.
The N-03 root composes exactly twelve groups at `/details/installation_fields`;
V1–V6 are typed objects. Trusted validation and its summaries occupy
`/details/trusted_validation` and `/details/verified_summary`. The old nine-group,
boolean-v2 root has no production adapter or fallback. The test driver adapts
old argv/assertions only, never old receipt results into capabilities.

Host context, installed snapshot and operation pin are opaque registered objects.
An accepted JSON root alone cannot mint them. Pinning covers physical module,
chain, witness, complete reader/schema sources, approved source bytes and run/arm.
The worker's expected binding comes from the host bootstrap, separately from its
request. It checks code identities before importing the producer or reading data;
a changed host object after the child returns discards the result.

T1 requires exact approved original archive bytes, a nonblank reason and all
original hash/ancestor/checkpoint/witness checks. All 101 nulls remain unknown;
1313 remains a book/high-water diagnostic, never an own-arm formal bound.
New writes stay strict. An independently accepted own-arm reconciliation may
close relevant unknowns while retaining original null rows. The diagnostic
`arm_n.project` stays unchanged and deliberately incomplete.

Current loader and readback use the single shared
`authority_prefix.verify_anchor_prefix`, schema `EVO884.AnchorPrefixCheck/v1`.
Original LF prefix hashing is followed by full replay; a valid prefix alone
cannot authorize a bad suffix or stale witness. Installation remains a pending
callsite, with no installer. Current code has no v4 fallback. Historical archives,
explicit `historical_*` regression helpers and diagnostics remain available.

`tests/dynamic_factor/reception_v2_driver.py` runs the original 20 first-stage
specifications and 18 T1 specifications with real receivers/shared V5. For example:

```sh
python -B qlab/tests/dynamic_factor/reception_v2_driver.py \
  --case-id N-03-07 --contract-id EVO884.InstalledAuthorityReceipt/v3.1 \
  --contract-version 3 --contracts-dir qlab/qlab/dynamic_factor/reception_contracts \
  --baseline 4cdfcbc0726abeadfff9e143b49281fab815bc43 \
  --private-fixtures PRIVATE_EMPTY_DIRECTORY --report-json -
```

Set `PYTHONPATH=qlab` and install declared test dependencies beforehand. Tests
also exercise source FAIL S02/S05/S09, current/historical separation and actual
isolated subprocess binding refusal (reader calls 0, roles empty). Historical
proof material is preserved; its corrected design-verifier citation is
`verify.py:40` (not `:33`). Live authority/permission/deployment inputs remain
external prerequisites and are not synthesized by this implementation.

## Frozen D public diagnostics and C6

`EVO897-ARMTAG-D-SCOPE-v1.0.0` (`35b8b4fb…96b2`) preserves three omitted-label
public entries: `dsr_eval`, `pipeline.evaluate`, and `run_train_pipeline` in the
original frozen domain. `_n_snapshot` remains formal: missing identity refuses
before ledger reads, observations, writes or consumers; no virtual hash exists.

For a noncanonical archive only, the public diagnostic route uses
`historical_authority.historical_diagnostic_snapshot`. It reconstructs the
complete frozen D input record from verified rows and the explicit historical
v4 cut. The old field names `current_published_anchor` and `is_current_authority`
describe that historical cut, not a live installation. This record never enters
N01/N02/N03 or the current loader. Canonical project objects cannot use it.

The current `AuthorityLedger.snapshot` remains unchanged: a copied archive has
`current_published_anchor=null`, an explicitly historical anchor, and no current
authority. The opaque host view and formal adapters retain their existing
verification. This separates a frozen diagnostic input schema from a current
authority snapshot without dropping fields from the current object. Every
diagnostic input hash is computed from its complete actual preimage; no
constant hash, excluded input_sha256, default arm or old write is introduced.

`test_c6_public_compatibility.py` retains full baseline-98cd snapshots/reports,
uses the supplied original comparison function, and checks all three entries,
including training's frozen refusal. Only D's two source identity paths are
separated; raw reports/diffs and full input preimages remain available. Further
tests reject historical fallback on the canonical project, keep copied archives
out of formal N, and retain the helper's zero-operation refusal.

The fixed peer v2 comparison is retained as byte-preserved fixtures under
`fixtures/authority-stage1/f1-scope-v2`. The repository regression entry is
`qlab/tests/dynamic_factor/run_f1_scope_v2.py`. It requires an explicit final
40-character `--head`, clean source, actual Python 3.9.6 / 3.12.13 executables,
and private dependency/output directories. It verifies all five original
file identities, materializes them without editing their bytes, and passes
the full 98cd/main/final refs plus `--assert-all` to the original driver.
Thus its demonstration defaults cannot select the old failing head, a missing
assertion flag cannot turn collection into acceptance, and mislabeled Python
executables are rejected. Public equality, formal helper refusal and all ready
controls remain separate observations; no product authority path is added.
