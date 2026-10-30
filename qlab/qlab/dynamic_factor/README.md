# EVO-884 dynamic-factor tools

Offline deterministic mechanisms for EVO-881. No broker, account, credential,
scheduler, live data, or order-sending integration. Tests use labelled synthetic
unit inputs, not strategy backtests. The old paper executor and shared research
ledger remain untouched.

## Authority and limits

The default adapter binds EVO-883 **v0.2**, raw SHA256
`b873b30b754695bef82ff37b95fc7628b0cc45ad7eb76e9cb091f9164cfc0a17`,
and the unmodified `prereg-v1-draft2.json` companion. The loader verifies both raw
identities, their shared fields and the common profile SHA
`e2ed67fc4ec9ed709c4a77ac5a72165da7dc3843e8030e5fa57aee0164058d30`.
It retains immutable bytes and returns dictionary copies. Reports carry convention
version/SHA/status, companion SHA and common profile SHA. v0.2 is a revised design
draft, so **every bound report remains `certifiable: false`**.

The normal ledger imports the exact eight source rows / **47 observed attempts**
from `e51f8023bd0c0b6cf45c5badbc9db2c45a3a14e9`:
`research/gate/state/trial_ledger.jsonl`, SHA256
`76ece03d62628a2ca2f0cb089103deaa26584ae9522fdde101df782a738a8f0b`.
This is an incomplete lower bound: `cumulative_n: null`, `n_complete: false`.
No real complete-N reconciliation or comparable reference families have arrived.
Default research admission, meta generation and formal DSR therefore refuse with
null values. Verified raw execution/total-return/cross-anchor evidence is also
required; qfq price ratios or an AAPL calendar receipt do not supply that evidence.
No reference backtests are automatically created to fill gaps.

The v0.1 raw artifact and adapter remain only for historical regression and pure
formula checks. Explicitly binding v0.1 still refuses V/admission with
`prereg_pending_v0.2`. The generic injected-plugin seam is a trusted engine-test
extension; it is not an alternative EVO-883 certification route.

## Run and verify

Tested with Python 3.12.13, pytest 9.1.1 and Ruff 0.14.3. Tools/harness use the
standard library. From the repository root:

```bash
PYTHONPATH=qlab:. python -m pytest qlab/tests/dynamic_factor -q
PYTHONPATH=qlab:. python -m pytest qlab/tests/dynamic_factor qlab/tests/test_qlib_gen.py -q
ruff check qlab/qlab/dynamic_factor qlab/tests/dynamic_factor
ruff format --check qlab/qlab/dynamic_factor qlab/tests/dynamic_factor
PYTHONPATH=qlab:. python -m qlab.dynamic_factor.harness --workdir ./harness-run-1
PYTHONPATH=qlab:. python -m qlab.dynamic_factor.harness --workdir ./harness-run-2
```

The original 76-vs-84 report used the six dynamic-factor test files at `527de0e`:
76 tests there, plus the 8 tests in `test_qlib_gen.py`, gives 84. Without `qlib`,
that optional module is skipped. Subsequent stub and v0.2 tests increase the
current count; consult the current PR validation output, not the old total.

Harness directories must be empty. On the same interpreter, the two JSON reports
are byte-identical. The original nine fixed case IDs plus
`data.benchmark_calendar_gap` remain; four additional v0.2 revision cases cover
the DAG, staged startup, NAV gain units and affine qfq refusal. Network is blocked;
there are no clock, RNG, model-call or live-data inputs. Toy complete ledgers and
reference registries are explicitly labelled **synthetic unit only**; they are
never imported as research authority.

## S0 -> S4 and true folds

`run_walk_forward(..., conventions=policy)` checks the pinned 77-fold manifest.
Labels and the 20-session template path must mature inside the original train;
next-open entry gives a 21-session template offset. The separate train/test gap
is also 21 sessions, read from JSON. No full-history receipt, test label or reused
model can pass the existing fold guards.

For v0.2 each new trusted fitter implements:

- `probe(train_labels, train_features, proposal, probe_profile)` returning daily
  active `returns`, daily cross-sectional `scores`, exact `fit_dates`, and
  `train_sha256`. Train features cover the full 1260 sessions; labels stop at the
  purged eligible signal endpoint. The profile disables DSR admission, decay
  selection and voluntary gain gating for the fixed 16 solo probes.
- `calibration_rows(train_labels, train_features, proposals)` returning every
  common mature date and its stock/QQQ H10 labels plus all 16 rank values. The
  engine builds and seals the equal-date calibration table in S1, before S2.
- `fit_meta(train_labels, train_features, proposals, pool, calibration)` returning train
  diagnostic `returns` and a `FitReceipt` whose model predicts feature-only test
  rows. The receipt must match labels' exact dates, train SHA and all proposal SHA
  before the meta diagnostic can be sealed.

`manifest.research_context_by_fold[fold_id]` pins the full train calendar, dataset,
x2 fee and common profile hashes, explicit carried `retired_ids`, plus a trusted price-basis receipt bound to that
dataset. `manifest.reference_registry` is loaded separately with
`pipeline.read_pinned(path, expected_raw_sha)`. `self_report_n` is explicit.
Adapters are trusted Python code; this is a data-flow contract, not an OS sandbox.

The actual orchestration is in `pipeline.run_train_pipeline`:

1. S0 pins all 16 candidate roles, the future meta policy role, input/profile hashes
   and the external registry identity before performance.
2. S1 registers all candidate attempts before invoking probes. Failures/NaN and
   duplicated proposals stay in N; all 16 finite observations are required.
3. S2 uses the candidate-only sample V and its candidate reference floor, then
   daily DSR at the candidate N/hash snapshot. Positive-mean/DSR-qualified recipes
   are ordered by mean then ID, with the frozen correlation/pool-size rule. Missing
   prerequisites yield null, never a fabricated empty pool. A fully evaluated
   legitimate empty pool can proceed through the fixed base-only meta policy.
4. S3 registers exactly one meta attempt after the unique pool is sealed.
5. S4 reuses the original 16 SRs without duplicate N and adds the meta SR. It uses
   the separate meta reference floor and the later N/hash snapshot. Failure cannot
   trigger another pool, another meta attempt or an earlier DSR rescore.

External references require their complete predeclared memberships and every
trial's source run/return SHA, daily active basis, exact train calendar, profile,
dataset and x2 cost identities. Current-run/derived copies, v0.1 profiles, annual
or mixed scales, missing trials and winner subsets are refused. Source provenance
does not prove IID. Stage successes and failures are immutable ledger records;
a consumed run/fold cannot evaluate again.

`dsr_eval` v0.2 reads those sealed layer records. Request `layer: candidate` with
`run_id`, `fold_id` and optional `candidate_id`, or `layer: meta`. Scalar V/SR
cannot bypass the stages. The OOS readout requires every prescribed fold receipt,
aligned return dates, complete N and data guards; its V is the maximum frozen
train meta V across all folds, never a new V estimated from OOS controls. Neither
train DSR nor this predeclared max rule proves market performance or coverage.

DSR expressions, gamma, threshold, sample standard deviation, population skew,
ordinary kurtosis and daily/annual factors come from the pinned JSON. The pure
`dsr_v0.formula()` accepts an external V for unit arithmetic. It does not certify a
research path. Unknown numerical outputs are null, never zero.

## Startup and voluntary gains

`execution.lock_startup_intent` seals a budget at the previous reference close.
O0 starts with $15000 and zero inventory. Each probe/meta uses its own identified
train scope; stitched test/forward uses one continuing scope across folds. A scope
cannot be reset under a new start ID. Open calculations require the exact persisted
intent, adjacent reference-session dates, carried cash/inventory and valid prices.

`initial_build_turnover_check` uses only QQQ at opens 0, 1 and 2. It caps buying at
40% of previous-close canonical x2 NAV (E0 at O0), applies the normal tau <=20%,
integer floor, bound fees, no borrowing, 2% post-fee cash and 98% invested target.
It decrements quantity until feasible; missing prices/fees refuse, never create a
zero-cost fill. After O2 it retains unfilled cash with no extension. First regular
signal is position 5 close / 6 open, then the global five-session clock.

`calibrate_gain` consumes only verified mature H10 labels: common dates with at
least 50 stocks and all ten buckets for all 16 recipes. It averages stocks within
each date/bucket, then dates equally. No bucket interpolation or missing-as-zero.
Forecast weights use frozen active/half coefficients and current pool identities.

`voluntary_trade_gate` takes the unique final feasible holdings plans M and P,
original inventory/cash, raw open prices, frozen calibration/ranks/pool and a
trusted feasibility receipt bound to those exact plans. Required exits cannot be
undone. It nets each complete plan from original inventory once, quotes x2 fees
including QQQ, and computes:

```text
delta_w_i = (q_P_i - q_M_i) * raw_open_price_i / pretrade_canonical_NAV
G_H10 = sum_stock(delta_w_s * alpha_s) + mu_Q * sum_non_cash(delta_w_i)
K = max(0, C2(P) - C2(M)) / pretrade_canonical_NAV
accept optional P iff all inputs are verified/finite and G_H10 > K
```

Quantities already include tilt; no second theta or horizon multiplier is applied.
The gate checks its calibration and pool against sealed S1/S2 records. It seals
one plan per `account_scope`/`signal_close`, preventing a second subset search; an
identical delivery retry returns the immutable prior report. Missing old/new
forecasts reject optional changes and retain verified M, with
null gain metrics. Rejection selects M once; no second optional subset search.
The pure unit counterexample 1% alpha ×20% NAV exposure versus 0.3% incremental
NAV cost gives 0.2%-0.3% = -0.1% and rejects.

## Ledger, data, fees and CLI

`AttemptLedger.from_conventions(path, policy)` is append-only SQLite. Begin before
work; all outcomes survive restart. Same ID/same delivery is idempotent; a real
retry uses a new ID. Self-report high-water marks never decrease. Declared proposals
count even if registration is interrupted. The future meta role pinned at S0 does
not count as an attempted meta until S3; reusing probe SRs in S4 does not count twice.
Immutable stage/intent records are metadata. Logical hashes cover complete genesis
and events. Corruption never becomes a new empty history. Existing v0.1 DB genesis
is immutable; this version refuses a mismatch rather than silently rebasing it.
A real reconciliation/migration needs a separately reviewed append-only procedure.

`wf_manifest_check` preserves the existing data gates: own-span missing sessions,
nontrading/duplicate bars, nonpositive/unknown prices, alignment and configured
jump/reversal detection. It flags, never repairs/fills/shifts. The SPY fixture uses
2011-07-04, 2012-04-06, 2012-05-28 and missing 2012-05-29, with distinct
`data.jump_reversal`, `data.nontrading_bar`, `data.calendar_gap` codes. A trading-day
bad-price variant verifies independent jump detection. Beta/IR remain unavailable.
The AAPL-derived reference calendar remains an explicit unverified exchange
calendar assumption.

**`fee_frontier` arithmetic is unchanged.** Both raw EVO-882 parameter files and
the existing effective-date TAF switch remain intact. Reports explicitly say
“费用政策待 EVO-883 下一版”. The new complete-plan quote uses those same bound
bytes and the existing per-order mapping; it does not pre-implement the next
fee-policy choices or claim account fee applicability.

```bash
PYTHONPATH=qlab:. python -m qlab.dynamic_factor dsr_eval \
  --input request.json --ledger ./dynamic-factor-v02.sqlite \
  --conventions qlab/qlab/dynamic_factor/fixtures/conventions-v0.2.json
```

DSR CLI input wraps the selector under `metrics`. Other CLI tools accept their
request directly: `prereg_check`, `wf_manifest_check`, `fee_frontier`,
`pool_admission_check`, `startup_intent`, `initial_build_turnover_check`,
`voluntary_trade_gate`, `shadow_readout`, `decay_check`. Startup intent, state and voluntary-gain
checks require a ledger. `--conventions-sha256` pins raw bytes; default uses the
frozen provenance record. CLI never imports code named in JSON, emits JSON with
input/source/file hashes and assumptions, exits 2 on refusal, and optionally
writes immutable content-addressed reports using `--out-dir`.
