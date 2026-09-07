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

Legacy artifact `derived_settlement/SETTLEMENT_ed655bb09567c9a9.json` remains an
immutable, verifiable v1 record. The repaired calculation is the separate v2
artifact `derived_settlement/SETTLEMENT_6af59f5eeaa051f9.json`, with complete
content SHA-256
`6af59f5eeaa051f924beca9794e8eeaadf807f66d55373d25e0f8a1b3809b89b`.

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
- `cumulative_returns()` now divides the last NAV by the first segment's
  pre-entry `nav_start`, not the last segment start or first closing mark. A
  hand-calculated two-segment regression proves NAV `100,000 → 101,480 →
  105,538.904`, total entry cost `20.296`, and cumulative return `5.538904%`.
  Segment provenance is aggregated across the whole sequence. A pending middle
  segment returns `cumulative_return=null`; a cell first observed after missing
  earlier grid records is labelled `incomplete_prehistory`, excluded from the
  authoritative series, and never becomes a performance reading.
- The real-data regression now fixes the 2026-08-10 segment itself: exactly 15
  points in `[2026-08-10, 2026-08-31)`, every date and NAV value, first/last
  values, `reading_kind`, filled status, and whole-segment provenance. It does
  not assert the last point of the entire evolving series, so later valid
  segments may be appended without weakening the first-segment evidence.

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
| Existing note permits a later-round switch only after the evidence is accepted | Actual production call path selecting the bearing executor | None | Repository search finds `may_take_over` consumers only in tests/verification output; no production switch consumer | `switch_authorized=false`; a separate written 吏部 acceptance and an explicit, reviewable switch action are still required |

`may_take_over` remains the existing calculation-qualification formula; this
repair does not invent a 10/10 comparison gate or turn the nine cells without a
bearing peer into passes. Its semantics are now explicit: even if it later
becomes true, it is not switch authorization. A volume `RESOLUTION` can only
release the archive-integrity input gate and cannot authorize executor takeover.

## Artifact and invocation contract

The v2 settlement separates two identities:

- **Calculation identity**: implementation version
  `llm_paper_derived_settlement/evo-489-v2`, implementation source SHA-256
  `66a84e01a1ad668988c5fdf5e0d03e4b8e32f0f2048b8fa38e3fc7230896acaa`,
  and input-manifest SHA-256
  `830cd475f7f8554ae14149377554b00a4a881b444b4ac0c3956244667e0be5b3`.
  The manifest hashes every round record, archive, resolution, scanner state,
  and preregistration input. The calculation artifact's `content_sha256`
  protects every field except the hash field itself.
- **Invocation identity**: the separately hashed sidecar
  `derived_settlement/INVOCATION_6af59f5eeaa051f9_b44b92f662257d56.json`
  records Git HEAD `39ff9ca6880073b9e703a4d14ec5f4b6dbaa01eb` and normalized CLI arguments.
  Its own SHA-256 is
  `b44b92f662257d5601673df904df9569a8e14ab81c95490e2a4e320ca932f776`
  and protects the entire sidecar except its hash field.
  The preceding unpinned discovery invocation is separately preserved as
  `INVOCATION_6af59f5eeaa051f9_a3cc643b2a7b97d6.json`; it points to the same
  calculation artifact but has different normalized arguments, so its own hash
  is intentionally different.

Changing only HEAD therefore creates a different invocation trace but does not
change the calculation artifact. Changing the implementation source or a
declared input changes the calculation identity and artifact hash. Exact retries
with unchanged calculation inputs reuse the same file; exact retries with the
same HEAD and arguments also reuse the same invocation sidecar. Legacy v1
artifacts remain accepted by the verifier under their original whole-file hash
contract and are not rewritten.

For equivalence evidence, `append_only_records_unchanged` now requires all of:
tracked files, no unstaged diff, no staged diff, and exact content equality to
the explicitly named `evidence_commit`. Regressions cover unstaged, staged-only,
and clean-but-changed-after-evidence cases; no reset or worktree cleanup is used.

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

## Reproduce

```bash
python3 qlab/tools/run_llm_paper_derived_settlement.py \
  --out-dir qlab/reports/llm_paper \
  --equivalence-round 20260831 \
  --evidence-commit 023293e88ea4c727bc9f706cb8c673d12f2cb26b \
  --expected-input-manifest-sha256 830cd475f7f8554ae14149377554b00a4a881b444b4ac0c3956244667e0be5b3 \
  --expected-implementation-version llm_paper_derived_settlement/evo-489-v2 \
  --expected-implementation-source-sha256 66a84e01a1ad668988c5fdf5e0d03e4b8e32f0f2048b8fa38e3fc7230896acaa \
  --expected-settlement-content-sha256 6af59f5eeaa051f924beca9794e8eeaadf807f66d55373d25e0f8a1b3809b89b
```

The command is offline and append-only: it does not fetch quotes, run a round,
touch the trial ledger, rewrite a historical artifact, add a `RESOLUTION`, or
switch an executor. A mismatch in any declared calculation identity fails.
