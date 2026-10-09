# EVO-162 C1 — Pre-registration ADDENDUM A: universe freeze口径 (户部, FROZEN)

**Frozen before any resolved-universe list and before any real-verdict result.**
Committed to `agent/evo-162-residual-reversal` with a git timestamp that precedes any
`RESIDUAL_UNIVERSE_RESOLVED.txt` commit and any real-results commit (the only run so far
is `数据不足-无法评估`, not a verdict — chronology intact: `e25d890` prereg → `92242b0`
engine → **this addendum** → future resolved-list + results).

**Why this addendum exists.** The frozen prereg §2 said "top-250 by 60-day dollar volume
from all US common stocks with ≥156wk history." Under the OpenD **≤300-symbol historical-K
quota**, daily bars for the full multi-thousand-name candidate pool cannot be pulled to
rank by dollar volume — a zero-quota **pre-screen** must first compress candidates to the
quota. That pre-screen key is a **selection-effect / survivorship judgment** (工部 correctly
routed it back: `resolve_universe.py` only ranks local parquet; 都水 verified US `TURNOVER`
is not a `get_stock_filter` field). Operationalizing "US common stock" (dual-class, ADR,
non-common, large-cap floor, borrow substitution) is likewise 户部口径. This addendum
freezes all of it. It **operationalizes** prereg §2's already-frozen qualitative criteria
("US large-cap common stock, ranked by 60d dollar volume, borrowable"); it does not relax
any gate. **Path chosen: (b) deterministic code pre-screen** — more auditable / reproducible
/ anti-cherry-pick than a hand-typed seed list. 户部 freezes the RULE here; 营缮 encodes it
into `resolve_universe`; 都水 runs it once on the OpenD host.

---

## A1. Two-stage screen (resolves prereg §2 vs 首辅 hard-constraint #1)

**Stage-0 — zero-quota pre-screen** (`get_stock_filter`, US market; consumes NO historical-K
quota). Apply, in order:
1. **Security type = US-domiciled common stock.** Exclude ADRs / foreign ordinaries (e.g.
   TSM, LYG, RACE), ETFs, ETNs, closed-end funds, preferreds, warrants, units, and
   pre-merger SPACs. Rationale: the 3-factor model (SPY/IWM/IVE/IVW) spans **US domestic**
   market/size/value only; an ADR's "residual" is contaminated by FX + home-market factors
   the model does not span, which breaks the neutralization. Operationalize via moomoo's
   security-type / market fields; a name whose type cannot be confirmed common+US is
   excluded (conservative).
2. **Large-cap floor: market cap ≥ US$10B** at the freeze snapshot. Operationalizes prereg
   §2's "large-cap"; the cited edge (Blitz et al.; de Groot/Huij/Zhou) survives costs only
   in large caps — a floor is robustness, not a new hurdle. ($10B = conventional large-cap
   boundary, a-priori round number, not fitted.)
3. **Rank the survivors by a dollar-volume proxy, by this frozen priority:**
   - **(i) preferred — snapshot dollar-volume** = latest close × a zero-quota filterable
     recent share-volume field (`VOLUME` or an `AVG_*` volume field), if `get_stock_filter`
     exposes one. Closest to the prereg-literal dollar-volume ranking.
   - **(ii) fallback — `MARKET_VAL`** if no zero-quota volume/amount field is filterable
     (都水's finding: `TURNOVER`/dollar-volume is not a US filter field). Market cap then
     proxies dollar volume for the pre-screen only.
   营缮 confirms field availability mechanically and uses the highest-priority available key;
   the resolved-list commit records WHICH key was used.
4. Take the **top 296** of that ranking = candidate superset (see A3).

**Stage-1 — quota fetch + prereg-literal ranking.** `fetch_daily_parquet(superset ∪
{SPY,IWM,IVE,IVW})` (≤300, quote-only SIMULATE) → compute the **prereg-literal 60-trading-day
average dollar volume** `mean(close×volume)` over the last 60 bars on the **real daily bars**
→ rank the superset by it → apply A2 de-duplication + borrow substitution → take **top 250**
= `RESIDUAL_UNIVERSE_RESOLVED.txt`. The FINAL selector is the prereg-literal 60d dollar
volume; Stage-0 is only the quota-forced pre-filter.

**Selection-effect record (honest survivorship disclosure — mandatory in the resolved commit):**
log the Stage-0 key used, the superset size (296), the 60d-dollar-volume and pre-screen-key
value of the **296th** name (the cut threshold), and the count of names excluded at each step.
Any name ranked outside the Stage-0 top-296 that *would* have entered the 60d-dollar-volume
top-250 is **unobservable under the quota** — a bounded selection effect, disclosed, and (per
prereg §2/§13) it **cannot turn a fail into a pass**. When the pre-screen key is snapshot
dollar-volume (i), the effect is tight (snapshot vs 60d-average dollar volume); under the
MARKET_VAL fallback (ii) it is looser but still bounded to ">$10B-cap but ranked 297+".

## A2. "US common stock" operationalization (FROZEN)

- **Dual-class / multiple listings of one issuer** (GOOGL/GOOG, and any others such as
  FOX/FOXA, UA/UAA, BRK.A/BRK.B): keep **only the single class with the higher 60-day dollar
  volume** per issuer; drop the rest (two classes of one firm have near-identical residuals →
  same decile → issuer over-concentration + double-counting). Tie within 5% → keep the
  **alphabetically-first ticker** (deterministic). So GOOGL vs GOOG is resolved **by the data**
  (higher 60d dollar volume), not by a hand pick.
- **Non-common** (ADR/foreign, ETF/ETN/CEF, preferred, warrant, unit, pre-merger SPAC):
  excluded at Stage-0 rule 1.
- **REITs:** KEPT (they are US common equity, liquid, borrowable). Noted limitation: REIT
  residuals load partly on a rate factor absent from the 3-factor model; this is disclosed,
  not corrected (a rate factor is reserved for a future fresh registration).
- **Market-cap floor:** ≥ US$10B (A1 rule 2).
- **Borrowability substitution:** after the 60d ranking, walk the list top-down; a name that
  is not moomoo share-borrowable (or hard-to-borrow beyond the frozen 0.5%/yr GC assumption)
  is **skipped and replaced by the next-ranked survivor**; every substitution is logged in the
  resolved commit. This is the ONLY admissible substitution and it happens **before** results.

## A3. Candidate superset size & selection-effect acceptance (FROZEN)

- **Superset = 296** = 300 (quota hard cap) − 4 factor ETFs (SPY, IWM, IVE, IVW). Reserving
  the ETFs is mandatory (they are the factor regressors).
- **Headroom:** 296 pulled → 250 kept leaves 46 slots for A2 dual-class/borrow drops; ample
  for liquid large-caps (dual-class + HTB are rare among them). If, after A2, fewer than 250
  clean tradable names survive, the universe is **that smaller count, labelled honestly**
  (a data/borrow shortfall, never padded) — a run on <250 is still labelled per the breadth
  rule (deciles need breadth; a thin book is `数据不足`, not a verdict).
- **户部 accepts and records** the Stage-0 pre-screen selection effect (A1) as the minimal,
  quota-forced, fully-disclosed compromise. A point-in-time survivorship-clean universe needs
  an external membership feed (out of scope this round); its absence is disclosed with every
  result and bounds the claim, never inflates it.

## A4. Freeze & handoff (FROZEN)

- This addendum is committed **before** any resolved-universe list and any real result;
  `residual_provenance.json` is updated to the concrete two-stage口径 in the same commit.
- **Path (b) handoff:** 营缮 encodes A1–A2 into `resolve_universe` as a deterministic Stage-0
  `get_stock_filter` pre-screen (priority (i) snapshot dollar-volume, fallback (ii) MARKET_VAL)
  + Stage-1 60d-dollar-volume rank + A2 de-dup/borrow substitution, emitting
  `RESIDUAL_UNIVERSE_RESOLVED.txt` + the selection-effect log; 都水 runs it once on the OpenD
  host, commits the resolved list (before results), then `run_residual` for the real verdict.
- Any deviation from A1–A4 stops and is reported (no silent retune). Control returns to 工部
  for 工部-internal orchestration (营缮 + 都水) and final wrap-up to 吏部 三方核验.
