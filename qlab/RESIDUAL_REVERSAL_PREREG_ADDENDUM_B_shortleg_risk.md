# EVO-162 C1 — Pre-registration ADDENDUM B: short-leg risk口径 reconciliation (户部, FROZEN)

**Frozen before any real-verdict result.** Committed to `agent/evo-162-residual-reversal`
with a git timestamp that precedes any resolved-universe list and any real result
(chronology: `e25d890` prereg → `92242b0` engine → `b0b80a6` universe addendum A →
**this addendum B** → future resolved-list + results; the only run so far is
`数据不足-无法评估`, not a verdict).

**Why this addendum exists.** 锦衣卫's EVO-10 review (on `b0b80a6`) returned a
**conditional PASS**: the short leg is a dollar+beta-neutral, diversified, borrowable-cash
hedged structure with a **bounded, quantifiable** book-level max loss — it does NOT fall
into EVO-10's infinite/undefined-risk exclusions, and it **may run in the SIMULATE
backtest** (no forced fallback to long-only / defined-risk). The review flagged three items
where the frozen §6 text overstates what the SIMULATE code actually enforces; 户部
reconciles them here so the prereg matches the implementation before any result is claimed.
This addendum **operationalizes / honestly relabels** already-frozen §6 lines; it does not
add a new risk to the strategy.

---

## B1 — single-sector net cap: **MONITOR-ONLY** (was "enforced as a hard cap")

**Decision.** §6's line "single-sector net cap |long−short| ≤ 10% gross per GICS sector …
enforced as a hard cap" is changed to **monitor-only**: each run **computes and discloses
the realized maximum single-sector net exposure** (|long weight − short weight| per sector,
in gross units); a run whose realized max **> 10% gross is FLAGGED in the report** (per-run,
never silently dropped). It is a **disclosed diagnostic, not an enforced sizing constraint**.

**Rationale (why monitor-only is the correct口径, not merely the convenient one):**
1. **Preserves the frozen 3f/4f distinction.** The 3-factor **primary** is deliberately
   market/size/value-neutral but **not** sector-neutral; sector-neutralization is the
   *separate* §12 **4-factor family cell** (industry demean). Forcing a hard sector cap into
   the primary would partially sector-neutralize it and blur it against its own robustness
   cell — a construction contamination, not a fix.
2. **The risk is already bounded by the frozen stack.** Sector-tilt risk is capped by
   single-name **≤ 2.5% gross** (structural: equal-weight decile, ≥ 20 names/leg) +
   dollar-neutral + beta-neutral (|β^MKT| ≤ 0.05) + **2.0× gross hard cap** + **10% ann. vol
   target** + **8%/5-day drawdown → 0.5× breaker**. The vol target caps *total* book risk
   regardless of the tilt's source — a large sector tilt raises realized vol and mechanically
   triggers deleveraging. So a hard ≤10% sector cap is largely **redundant with the vol
   target** for the RISK purpose EVO-10 cares about.
3. **Avoids a post-hoc optimizer / tuned knob.** Enforcing a net-sector cap requires a
   constraint-satisfaction step (trim/reweight the breaching sector) that departs from the
   frozen equal-weight decile construction and risks becoming a tuned mechanism (clause #4
   discipline). Monitor-only keeps the frozen construction pure and lets the data speak.

**Sector source for the diagnostic (data-boundary honest).** The disclosure metric uses a
**static current-GICS sector map as reference metadata**, used **only** for this risk
diagnostic — **never** for the signal, sizing, or verdict (the signal & execution stay
OpenD-only; a sector label is metadata like a ticker name). If no reliable static sector map
is available to 营缮, disclose "single-sector net exposure **unmeasured** under OpenD-only"
and rely on the bounding stack (reason 2) + point to the §12 4f cell as the sector-neutral
robustness check. **Do not silently drop the item either way** (锦衣卫 prerequisite #1).

## B2 — +25% single-name short stop: **LIVE-EXECUTION OVERLAY, NOT active in SIMULATE**

§6's "per-name short stop +25% adverse" is honestly relabeled: the primary口径 **SIMULATE
weekly backtest holds to the next weekly rebalance with NO intraday stop**. This is a
**conservative** simplification — no stop means the book eats the full adverse move, so it
**does not underestimate** risk. The +25% stop is a **live-execution overlay** and is **NOT
exercised this round**. **Every result MUST state:** "main口径 backtest = weekly-hold, no
intraday +25% stop exercised; the +25% stop is a live-execution overlay not active in this
SIMULATE run." The +25% stop **cannot be claimed as an active tail limit** in the SIMULATE
verdict (锦衣卫 prerequisite #2).

## B3 — gap risk: filed as a **live-transition requirement** (out of scope this SIMULATE round)

If the strategy ever leaves SIMULATE / quote-only, the +25% stop must be modeled as
**"fills at the next open after trigger"** (NOT a guaranteed +25% exit — overnight/gap-through
on M&A/earnings can pierce it), and that transition **triggers a fresh 锦衣卫 red-line
review**. The gap loss is **bounded now** (single-name ≤ 2.5% gross ⇒ even a +100% overnight
gap ≈ 2.5% NAV single-name loss). Recorded for the record; **no action this SIMULATE round**
(锦衣卫 prerequisite #3).

## B4 — items confirmed unchanged (for the record)

- **Single-name ≤ 5% gross cap:** left as-is (informational). Equal-weight decile with
  ≥ 20 names/leg makes single-name exposure structurally ≤ 2.5% gross, so the 5% cap is a
  never-binding redundant guardrail — 锦衣卫-accepted, no change.
- **2.0× gross hard cap, 10% vol target, 8%/5-day breaker, dollar+beta neutrality, ≥20
  names/leg → thin_book→数据不足, borrow 0.5%/yr + financing 6.8%/yr + no rebate, quote-only
  SIMULATE with no TrdEnv.REAL / no order path / no credential surface:** all confirmed by
  锦衣卫 as coded and binding; unchanged.

## B5 — freeze & handoff

- Committed **before** any resolved-universe list and any real result; `residual_provenance.json`
  risk block updated in the same commit.
- **Handoff (工部 / 营缮):** implement the **single-sector net-exposure diagnostic** (B1:
  compute + disclose realized max per run, flag >10%, using the static-GICS map as a
  reporting-only input; else disclose "unmeasured") and the **honest §6 relabeling** of the
  +25% stop in `residual_evaluate`'s report (B2), folded into the in-flight universe-resolution
  work. 都水 runs. Any deviation stops and is reported.
- **Scope guard (锦衣卫 boundary):** this review + reconciliation covers SIMULATE / quote-only
  only. The instant the short leg leaves SIMULATE or adds any live credential / order path,
  the review is void and a fresh 锦衣卫 review is required.
