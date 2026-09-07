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

Artifact: `derived_settlement/SETTLEMENT_ed655bb09567c9a9.json`
(`reading_kind=lower_bound`, source implementation `e359bcd`).

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

## Parallel-control promotion and takeover

Artifact: `derived_settlement/EQUIVALENCE_20260831_a605278a3e09eac0.json`
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
- Result: `overlap_book_nav_equivalence_passed=false`, `may_take_over=false`.
  The bearing executor remains unchanged.

## Reproduce

```bash
python3 qlab/tools/run_llm_paper_derived_settlement.py \
  --out-dir qlab/reports/llm_paper \
  --equivalence-round 20260831
```

The command is offline and append-only: it does not fetch quotes, run a round,
or touch the trial ledger.
