EVO-898 consumes the scoped v10 acceptance as a versioned v1 input overlay.
It does not release the historical run or certify any complete cash event.

The two entry bindings are unchanged bytes in `fixtures/evo898/`:

| Input | SHA256 |
| --- | --- |
| `EVO883-v10-engineering-disposition-draft-v1.json` | `0f9811006c529051f2941bdc69fc916be8209e5e822acbd23464abd2109fbdd1` |
| `EVO883-EVO893-v10-final-acceptance-v1.json` | `43e14aebacc3cb4a0f775e1b4d35ebd45bc536aa260470e0b673bf7cf7784f0d` |

`event_quarantine.sources()` hashes both before consumption. The external
acceptance authorizes its scoped rules; the draft's pending fields stay intact.
All 40 event records retain their exact source evidence, action and separate
vendor/declared amounts. The 15 unmatched relations remain relations and never
become invented payments. Existing B/Barnes33, inferred Randgold6 and
COR/CoreSite33 constraints are retained. No automatic retagging, date shifting,
deduplication, multiplier repair, zero filling or cash insertion occurs.

`quarantine_check()` accepts `dependency_nodes`, an explicit dependency graph:

```python
{"dependency_nodes": [
    {"id": "anchor", "field": "raw_close", "parents": [],
     "date": "2013-10-29", "event_keys": ["B|2023-08-30"], "value": 100},
    {"id": "later-cash", "field": "cash", "parents": ["anchor"],
     "date": "2026-07-09", "value": 100}
]}
```

Edges identify actual adjustment-anchor, lookback/ADV, full label entitlement
interval, calibration/ranking and carried state dependencies. They are not
limited to event-day or ten direct windows. Node order and date order may
differ. Missing parents, cycles and unbound event identities refuse. Values and
lineage are projected per node; submitted values remain separate evidence.
All verbatim output fields in the five propagation rules, and explicit names
for their history/interval/state requirements, have null formal readouts and
per-field reasons. UNKNOWN eligibility freezes optional new risk; it does not
create an empty valid pool. This module does not compute replacement values.

There is no accepted independent reconciliation checkpoint in these bindings.
For B/COR, unknown adjustment ancestry invalidates the declared span, including
prior anchors. Passing a later date or a self-asserted checkpoint cannot clear
the state. Future closure needs separately accepted evidence and reader policy;
this input does not impose a new second-source/per-event exchange-original gate.

The existing `panel_input_check`, `wf_manifest_check`, `run_walk_forward`,
`integer_cash_valuation` and `continuous_path_check` entry points consume the
overlay. Manifest/row `dependency_nodes` and `panel_inputs` carry lineage.
Explicit `panel_symbols` must equal the frozen 64 in order; the returned strict
eligible count remains null. The cash boundary retains declared inventory and
known cash as evidence while affected verified inventory, total available cash,
receivable and NAV stay null. Removing submitted cash rows cannot recover a
B/COR holding. After sale, the writer must carry the consumed event ancestry in
the next state graph. A stateless request is not evidence about omitted history.
Continuous receipts retain all 77 folds and every submitted declaration,
attempt/budget/N identity; no skipped fold, capital reset or automatic resumption.
The walk-forward boundary refuses before any adapter or ledger execution.

`s1_input_receipt()` adopts only the accepted same-vendor NONE `raw_open` scope
for BRK.B, 2013-10-29 through 2026-07-09. `read_s1_raw_open()` additionally
requires original CSV bytes with SHA256
`68ade2686e49d444a973c4533048531223c88b158fff56a32e676c6888557842`,
checks its four page bindings and 3,191 distinct dates, and returns only
symbol/date/raw_open. The byte-identical CSV was copied from the existing
review cache after hash verification, with no market request. Merely repeating
its hash alongside a caller's number is not numeric adoption. Source
independence, volume units, other securities, cash, TR and execution remain
unverified. No accepted source or frozen file is rewritten.

Validation from repository root:

```sh
PYTHONPATH=qlab:. python -m pytest qlab/tests -q -k 'not test_live_fred_covers_2022_rate_shock'
PYTHONPATH=qlab:. python -m qlab.dynamic_factor.quarantine_harness --output harness.json
ruff check --isolated --select E4,E7,E9,F <changed-python-files>
ruff format --check <changed-python-files>
```

The harness runs the seven machine examples plus five recovery/continuity
negatives. Its report includes full event evidence and every field projection.
Canonical comparison removes only root `dependencies`, then serializes UTF-8
with sorted keys, compact separators, `ensure_ascii=False`, no trailing newline.
`test_event_quarantine.py` also checks each event against every field, malformed
graphs, binding/CSV tampering, real manifest/cash/fold entry points, inventory
after sale, original grid/declaration retention and the S1 positive reader.

The repository contains one FRED live smoke test. Exclude it under this task's
no-acquisition boundary; the final evidence runner marks it skipped and blocks
network connections. Optional Qlib absence is reported separately. Initial
unrestricted suite invocations accidentally ran that live test once under each
interpreter; those two responses were not archived and are not adopted inputs.
The delivery evidence records this exception rather than claiming zero total
external requests for the task. Do not refetch them.

SIMULATE-only: no market/model/OpenD calls, authority ledger writes, production
changes or real orders. `runtime_consumable=false`, `certifiable=false` remain.
