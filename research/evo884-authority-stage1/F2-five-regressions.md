B21R F2 repairs the original five specimens, without changing a production
receiver, the approved contract, or any historical source fixture. The original
38 IDs and approved descriptions remain. A-03 has two explicit branches: a
schema-valid measured sequence mismatch and the original self-consistent old L2.
There are now 59 CLI branches under the same 38 IDs (previously 58).

Run each original CLI with Python 3.9.6 and 3.12.13, `-B`, in the offline
validation environment. These are five separate argv, with actual absolute paths
and outputs retained in the delivery's `*-{case}.command.json` and `{case}.json`:

```sh
python -B qlab/tests/dynamic_factor/reception_v2_driver.py --case-id A-02 --baseline 4cdfcbc0726abeadfff9e143b49281fab815bc43 --private-fixtures PRIVATE --report-json A-02.json
python -B qlab/tests/dynamic_factor/reception_v2_driver.py --case-id A-03 --baseline 4cdfcbc0726abeadfff9e143b49281fab815bc43 --private-fixtures PRIVATE --report-json A-03.json
python -B qlab/tests/dynamic_factor/reception_v2_driver.py --case-id A-04 --baseline 4cdfcbc0726abeadfff9e143b49281fab815bc43 --private-fixtures PRIVATE --report-json A-04.json
python -B qlab/tests/dynamic_factor/reception_v2_driver.py --case-id A-06 --baseline 4cdfcbc0726abeadfff9e143b49281fab815bc43 --private-fixtures PRIVATE --report-json A-06.json
python -B qlab/tests/dynamic_factor/reception_v2_driver.py --case-id T1-05 --baseline 4cdfcbc0726abeadfff9e143b49281fab815bc43 --private-fixtures PRIVATE --report-json T1-05.json
```

The fixture adapter's private source is a test assumption, not an actual
deployment or a production trust adapter. All five run through
`test_stage1_specifications.py::test_stage1_specification` as well.

| Original ID | Bearing object and assertions (`qlab/tests/dynamic_factor/authority_rework_specimens.py`) |
| --- | --- |
| A-02 | `typed_anchor_case`: change `V2.measured.revision`; the closed schema passes, operation binding is valid, actual `validate_receipt=1` and `validate_anchor=1`, exact refusal `receipt.anchor_observation_mismatch`. Original approved publication/revision remain unchanged. |
| A-03 | `typed_anchor_case`: change `V4.measured.anchor_sequence` and `observed_prefix_sequence` to 182; same semantic stop as A-02. `old_l2_case`: original seq182/N280 prefix passes the shared V5 and full-chain structural replay; current trusted release remains seq1372; replacing actual publication bytes refuses `receipt.trusted_source_failed:publication` after schema, before validator dispatch. |
| A-04 | `physical_pair_case`: edit the actual chain, recompute all links and a locally matching witness, write both private physical objects. Candidate receipt is unchanged. Refuses `ledger.observed_object_drift` after schema, before any data reader; receiver leaves attacked bytes unchanged. |
| A-06 | `physical_pair_case`: actual wrong-ledger branch has a strictly larger sequence and high water, with recomputed matching witness. Both physical objects change; receipt stays unchanged. Same physical-binding refusal as A-04. |
| T1-05 | `original_prefix_case`: exact independent-review prefix/witness bytes, original seq1148/N756, all witness state fields match locally. Full adopted archive first replays to 1313. The short input refuses `ledger.approved_archive_bytes_mismatch`; no installation. SHA identity is independently pinned in assertions and the fixture manifest. |

All host negatives measure `read_inputs=read_strategy_inputs=run_isolated=0`;
their worker is **not started**. This is separate from a worker rejection.

`test_authority_worker.py::test_bound_worker_real_subprocess_precedes_every_data_reader`
now observes native `-I -S` child calls for every original wrong binding, plus a
self-resigned wrong witness. Negative child exit=2, `bind_stdin=1`,
`prepare=read_inputs=read_strategy_inputs=0`, complete=false, reader=0, roles=[];
the clean control actually prepares/reads once, complete=true, three roles,
and returns no numerical performance. The child protocol exit=2 is reported
separately from pytest/CLI exit=0.

Exact line numbers, actual outputs and both interpreter results accompany the
delivery; this document does not claim unexecuted validation as passed.
