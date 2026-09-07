## Batch 1 derived settlement and executor takeover audit

This is engineering evidence only. It is not an acceptance reading, a 50/20
claim, or an investment conclusion. No scan or decision round was run while
producing it, and no historical round/archive record was modified.

## Inputs and archive integrity

- Bearing rounds: `round_20260810.json`, `round_20260831.json`.
- Parallel-control evidence: `CONTROL_20260831.json` and
  `control_multi_book/round_20260831.json`, introduced together by `023293e`.
- Archive scans: `982d9f4` (09-02), `4a6e417` (09-03), `bd55c54` (09-04).
- All three archive content hashes and all scanner-state hashes validate. The
  first successful scanner activation is 2026-09-02. Required archive-key
  coverage is complete (`missing_count=0`). No `RESOLUTION` record exists.
- The 09-03 archive has 9 volume-difference occurrences on 2026-09-01. The
  09-04 archive repeats those 9 and adds 9 on 2026-09-02: 27 occurrences across
  refetch records, 18 unique `(symbol,date)` keys including SPY. The 08-31
  settlement actually consumes 24 occurrences / 16 unique keys (eight held
  symbols; SPY is not a settlement input). Existing RESOLUTION semantics remain
  unchanged: a difference on a consumed bar key blocks the reading even when
  the changed field is volume.

## Lower-bound settlement

Legacy artifacts `derived_settlement/SETTLEMENT_ed655bb09567c9a9.json` (v1) and
`derived_settlement/SETTLEMENT_6af59f5eeaa051f9.json` (v2) remain immutable and
verifiable. The 2026-09-07 wealth-continuity correction is the separate v3
artifact `derived_settlement/SETTLEMENT_688b385cfced1c56.json`, with complete
content SHA-256
`688b385cfced1c56a037d415b894b39738ea9fdea8a5e78c3b8bde44785c437f`.

- 2026-08-10, `seed11×pv1_baseline`: `filled`; NAV start 100,000; gross
  notional 49,000; turnover notional 49,000; entry cost 49; literal cash
  50,951. There are 15 daily NAV points in `[2026-08-10, 2026-08-31)`, ending
  at 101,206.4423275536 on 2026-08-28. The whole segment is explicitly labelled
  retrospectively archived before initial capture, not cross-checked, not
  acceptance-eligible. The other nine frozen-grid cells have no immutable
  decision record and remain listed as missing rather than reconstructed.
- 2026-08-31, `seed11×pv1_baseline`: `pending_archive_integrity`; no book/NAV
  reading is emitted. The pending record carries the complete consumed keys and
  all 24 relevant unresolved difference occurrences. The other nine bearing
  cells again have no immutable decision record.
- `n_trials_total` remains 10 for both rounds. No `no_rebalance` cash flatline
  or carry-forward value was invented.
- A pending or missing middle segment now breaks that cell's continuity. Every
  later recorded segment is `pending_prior_segment`, has no NAV/book, and has
  `is_performance_reading=false`; it cannot inherit an older filled book or
  restart at 100,000. A synthetic three-segment regression proves
  `filled → pending_archive_integrity → pending_prior_segment`; adding a valid
  test-only resolution in the sandbox rebuilds all three in order. No historical
  round is synthesized in either path.
- At every later segment, pre-trade wealth is now previous cash plus **all** old
  shares marked at the rebalance-day open. The same wealth funds new target
  notionals; turnover remains `sum(abs(new-old))` over the symbol union and its
  fee is deducted once. Missing open for an exit symbol returns
  `pending_archived_rebalance_bar`; it is never zeroed or replaced by the prior
  close. `rebalance_provenance` reconciles prior cash/close NAV, each old open
  mark, the boundary gap, new targets, turnover, fee, and post-trade cash.
- The former two-segment fixture exposes why the v2 expected values are no
  longer valid: first NAV still ends at `101,480`, but the next open values old
  holdings at `20,000`, so open wealth is `99,980` and the boundary gap is
  `-1,500`. Independent arithmetic gives turnover `4`, fee `0.004`, final NAV
  `103,979.196`, total fees `20.004`, and cumulative return `3.979196%` from the
  unchanged original base `100,000`.
- Positive, negative, and zero gap regressions verify that cumulative return and
  the exposed segment-return chain include the boundary gap exactly once. A
  zero-fee, 100%-invested continuous holding preserves its shares and has zero
  turnover across a positive gap. Separate hand-calculated cases pin mixed
  buy/sell turnover `17,996.4` and symbol entry/exit turnover `20,000`.
- `cumulative_returns()` still divides the final NAV by the first segment's
  pre-entry `nav_start`, not a later open or first closing mark. Later segment
  returns use the previous segment's terminal NAV as their return base, so their
  product equals final NAV/original base without dropping or double-counting the
  gap. A pending middle segment returns `cumulative_return=null`; a cell first
  observed after missing earlier grid records is labelled
  `incomplete_prehistory`, excluded from the authoritative series, and never
  becomes a performance reading.
- The real-data regression now fixes the 2026-08-10 segment itself: exactly 15
  points in `[2026-08-10, 2026-08-31)`, every date and NAV value, first/last
  values, `reading_kind`, filled status, and whole-segment provenance. It neither
  pins the current production pending status nor its exact blocker list. If a
  later segment is pending, it only asserts that no stale 08-10-only cumulative
  performance is emitted; if later evidence becomes valid, the same test
  requires the cumulative reading to advance while retaining the original base.
  The v3 exact-value fixture adopts the declared `math.fsum` result: compared
  with v2, only 08-18 changes from `101220.89426595987` to
  `101220.89426595985`, and 08-27 from `101607.73470220652` to
  `101607.73470220654` (one ULP each); raw bars and all other points are unchanged.

## Parallel-control promotion and takeover

Legacy artifact `derived_settlement/EQUIVALENCE_20260831_a605278a3e09eac0.json`
is unchanged. The repaired contract is materialized separately as
`derived_settlement/EQUIVALENCE_20260831_441359354a5eaa85.json`
(`reading_kind=equivalence_artifact`; never enters performance reporting).

- Decision capture: eligible under the existing rules. Same decision timestamp,
  same freeze anchor, freeze SHA is an ancestor of evidence commit `023293e`,
  the immutable report records one shared quote fetch and a zero-call injected
  control side, the overlap decision set is field-identical (8 vs 8), all 10
  frozen cells are present, records are unchanged, the bearing round survived,
  and `n_trials_total=10` (`n_evaluated` remains 1; this audit does not mutate
  the ledger).
- Seed interpretation is unchanged: 10 nominal cells contain two effective
  prompt-variant decision sets at `temperature=0`; this is not seed robustness.
- Derived book/NAV: the common history is settled first on both sides, so the
  target comparison exercises NAV compounding and two-sided
  `sum(abs(new_notional-old_notional))` turnover semantics. The sole overlap
  cell, `seed11×pv1_baseline`, is pending on both sides because of the unresolved
  archive differences. Pending equality is not a pass. The other nine control
  cells have no bearing peer and are individually marked non-comparable rather
  than passed.
- Result: `overlap_book_nav_equivalence_passed=false`, `may_take_over=false`,
  and `switch_authorized=false`. The bearing executor remains unchanged.

### Takeover evidence and authorization map

| Existing authorization text | Comparison object | Covered grid | Evidence | Remaining gap |
|---|---|---|---|---|
| `EXECUTOR_CHANGE_NOTE.md` §8.1: “决策集逐位相同” | Immutable decision fields on bearing/control records | The one overlap cell; the control record separately captures all 10 nominal cells | `decision_capture_promotion.rules`; currently eligible | Capturing 10 cells is not executor behavior equivalence; `n_trials_total=10`, `n_evaluated=1` stay unchanged |
| §8.1: derived settlement produces each side's book/NAV and compares them field by field | Two immutable target-round records rebuilt by the **same** derived implementation after common history | Only `seed11×pv1_baseline`; the other nine remain `passed=null`, `not_comparable_no_bearing_cell` | `takeover_contract.derived_reconstruction_equivalence`; currently blocked by pending archive integrity | Establishes reconstruction consistency only. It does not independently exercise single-book versus multi-book runtime behavior |
| `parallel_control.py`: `may_take_over` is a fact and the tool “不自动切换” | Persisted decision-time books from the two actual executors | The overlap cell, but both real books were `pending_entry_bar` | Original `CONTROL_20260831.json` and alert | No independent filled executor-behavior comparison exists |
| Actual `parallel_control.py:206-209` text: “对照通过 ⇒ 可在**下一轮**切换承载路径（裁定：不在对照当轮切，那一轮已同时背着恢复轮次与台账修复后首次登记两件事，再叠加切换将无法归因）。切换轮次回填进 `EXECUTOR_CHANGE_NOTE.md`。” | The separate decision-time `may_take_over` producer | None in the archived round: its required `book_status == filled` condition was false | Source inspection plus original pending control evidence | This producer received no new disclosure field in the settlement repair; its text itself does not require 吏部 acceptance |
| Current 吏部 constraint, separately imposed after the original producer text | Actual production call path selecting the bearing executor | None | Repository search finds `may_take_over` consumers only in tests/verification output; no production switch consumer | `switch_authorized=false`; separate written 吏部 acceptance and an explicit, reviewable switch action are still required |

`may_take_over` remains the existing calculation-qualification formula; this
repair does not invent a 10/10 comparison gate or turn the nine cells without a
bearing peer into passes. The original `parallel_control.py` producer is quoted
verbatim above rather than softened into an acceptance condition it never had;
it has no disclosure field added by this change and is currently unreachable
because the persisted book was not `filled`. The newer settlement artifact's
semantics are explicit: even if its qualification fact later becomes true, it is
not switch authorization. A volume `RESOLUTION` can only release the
archive-integrity input gate and cannot authorize executor takeover.

## Artifact and invocation contract

The v3 settlement separates calculation and invocation identities:

- **Calculation identity**: implementation version
  `llm_paper_derived_settlement/evo-489-v3`, logical source path
  `qlab/qlab/llm_paper/derived_settlement.py`, source SHA-256
  `aa4003e17a528682798edcee7b555ed145c2928239d8f00c7800d000c41b4210`,
  accumulation semantics `math.fsum(sorted-logical-key)/v1`, supported runtime
  contract `CPython>=3.9,<3.13`, and input-manifest SHA-256
  `830cd475f7f8554ae14149377554b00a4a881b444b4ac0c3956244667e0be5b3`.
  The manifest hashes every round record, archive, resolution, scanner state,
  and mandatory preregistration input. The manifest and calculation resolve the
  preregistration through the same `_resolve` path, but record the stable logical
  name `qlab/llm_paper_prereg.json`; absence is an error, never `null`.
  `unresolved_differences[].archive_file` is likewise relative to the report
  directory. Repo-root/`qlab/` CWD and relative/absolute out-dir spellings thus
  reach the same calculation identity. The v3 artifact's `content_sha256`
  protects every field except the hash field itself.
- **Calculation artifacts**: settlement SHA-256
  `688b385cfced1c56a037d415b894b39738ea9fdea8a5e78c3b8bde44785c437f`;
  equivalence SHA-256
  `c65f590292516a9a7469c65baaebf5c297bf9b5a2e4811896aa75297d4d5215e`.
  The equivalence schema is v2 and explicitly embeds the v3 settlement version,
  stable accumulation semantics, and supported-runtime contract.
- **Invocation identity**: v2 sidecars separately hash Git HEAD, normalized CLI
  arguments, and exact interpreter provenance. On implementation HEAD
  `dec47602ffa1c6e4d263dc89c9b0e50063e7623e`, the same unpinned command produced
  Python 3.9.6 sidecar
  `INVOCATION_688b385cfced1c56_6b210c8572479625.json` (full SHA-256
  `6b210c8572479625ef05b79caf415f4be60f8f17bc750c2b83d627cdec7ac777`)
  and Python 3.12.13 sidecar
  `INVOCATION_688b385cfced1c56_cce35b514ce89a12.json` (full SHA-256
  `cce35b514ce89a129698d531533d7595b643a89178f6c7e61924eb40c15bd7b8`).
  Both point to the exact same settlement and equivalence hashes; their sidecar
  difference is expected execution provenance, not calculation drift.
- The fully pinned command below is separately preserved for Python 3.9.6 from
  repo root as `INVOCATION_688b385cfced1c56_2b0b54d4b555fcd9.json` (full
  SHA-256 `2b0b54d4b555fcd995e923b4bd638d27088712ed32799cecbd6921c869356dd0`)
  and for Python 3.12.13 from `qlab/` as
  `INVOCATION_688b385cfced1c56_d199f8750ef1606b.json` (full SHA-256
  `d199f8750ef1606b89944c03be7350ec759ce6838d400554f65abdb9314b59e1`).
  Their normalized out-dir arguments intentionally differ; the calculation
  hashes do not.

Changing only HEAD therefore creates a different invocation trace but does not
change the calculation artifact. Changing the implementation source or a
declared input changes the calculation identity and artifact hash. Exact retries
with unchanged calculation inputs reuse the same file; exact retries with the
same HEAD and arguments also reuse the same invocation sidecar. Legacy v1 and
v2 settlement artifacts plus v1 invocation sidecars remain accepted by the
verifier under their original whole-file hash contracts and are not rewritten.

All expected calculation pins are checked against an in-memory result before
the output directory is created or any file is opened. Requested equivalence
records and the freeze anchor are likewise preflighted. Unsupported runtimes,
missing lock-file dependencies (which fail during import), missing prereg/input
records, and expected-pin mismatches therefore fail before artifact writes.

For equivalence evidence, `append_only_records_unchanged` now requires all of:
tracked files, no unstaged diff, no staged diff, and exact content equality to
the explicitly named `evidence_commit`. Regressions cover unstaged, staged-only,
clean-but-changed-after-evidence, and the distinguishing state where HEAD is the
older base while index/worktree exactly match the named later evidence commit.
Only the cached-diff guard rejects that last state. Paths outside repo root now
return false instead of raising. No reset or worktree cleanup is used.

## Operational boundary notes

- `ageing_clock` exists only when the archive scanner process is actually
  invoked. A scheduler/session failure produces no ageing diagnostic. Source
  trading-day countdown, observation-liveness diagnosis, and scheduler-failure
  monitoring remain three separate facts; this repair changes none of their
  policies and creates no monitor.
- Owner and exact `0600` checks apply only when the scanner loads the key from
  its configured file. If `ALPHAVANTAGE_API_KEY` is already inherited from the
  process environment, the file loader returns without applying file ownership
  or mode checks. This is a conditional guarantee, not permission to distribute
  or read credentials elsewhere.
- The archive scanner schedule was separately restored to active on 2026-09-07;
  its first 09-08 live result is not yet verified. This settlement-only delta
  does not modify that scheduler, scanner CLI, redaction path, credentials, or
  existing archive/round/SCAN records, and does not extend an older safety
  conclusion to future code/config changes.

## Reproduce

```bash
python3 qlab/tools/run_llm_paper_derived_settlement.py \
  --out-dir qlab/reports/llm_paper \
  --equivalence-round 20260831 \
  --evidence-commit 023293e88ea4c727bc9f706cb8c673d12f2cb26b \
  --expected-input-manifest-sha256 830cd475f7f8554ae14149377554b00a4a881b444b4ac0c3956244667e0be5b3 \
  --expected-implementation-version llm_paper_derived_settlement/evo-489-v3 \
  --expected-implementation-source-sha256 aa4003e17a528682798edcee7b555ed145c2928239d8f00c7800d000c41b4210 \
  --expected-settlement-content-sha256 688b385cfced1c56a037d415b894b39738ea9fdea8a5e78c3b8bde44785c437f
```

Run it with lock-file dependencies installed on CPython 3.9 through 3.12. From
`qlab/`, use `python3 tools/run_llm_paper_derived_settlement.py --out-dir
reports/llm_paper ...` with the same remaining arguments and pins. An absolute
out-dir is also accepted. All three spellings reproduce settlement `688b385c…`
and equivalence `c65f5902…`; only invocation provenance may differ.

The command is offline and append-only: it does not fetch quotes, run a round,
touch the trial ledger, rewrite a historical artifact, add a `RESOLUTION`, or
switch an executor. A mismatch in any declared calculation identity fails
before writes; deleting one required equivalence record or the preregistration
input also fails before writes. A clean environment missing locked dependencies
fails during import, likewise before any artifact path is opened.
