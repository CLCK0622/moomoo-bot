# EVO-162 C1 — Pre-registration ADDENDUM C: §A2 ADR/foreign mechanical exclusion rule (户部, FROZEN)

**Frozen before any resolved-universe list and any real result.** Committed to
`agent/evo-162-residual-reversal` with a git timestamp that precedes any
`RESIDUAL_UNIVERSE_RESOLVED.txt` commit and any real-results commit (chronology:
`…→ce80f4c(resolver)→45bfd75(ADR list)→ffb4247(B1/B2/B3)→this addendum C→future
resolved-list + results`).

**Why this addendum exists.** 都水's host run surfaced a **systematic §A2口径 gap**: the
operative stage-0 pre-screen key is **`MARKET_VAL`** (verified — US `get_stock_filter`
`TURNOVER`/`VOLUME`/`AVG_VOLUME` all return "filter field not supported", so ADDENDUM A's
**(ii) fallback** is in force). Ranking by market cap pulls **mega-cap FOREIGN OTC ADRs**
(Nestlé, Roche, LVMH, Tencent, Siemens, Toyota affiliates, ICBC, BYD…) into the top-296.
My frozen 145-name curated list (`45bfd75`) caught the well-known **sponsored/exchange**
ADRs but **systematically missed the 5-letter `-Y` unsponsored-OTC-ADR long tail** — **87
of 296 (29%)** are foreign ADRs, leaving only **209 clean** US common (< 250). Fixing 87
(+ refill waves) changes the frozen §A2 universe by ~30%, so — per 首辅 hard-constraint #1
(universe author = 户部) and the three-way-verification integrity — the **口径 author must
be 户部**, not a 都水 heuristic reclassification. 都水 correctly stopped, froze nothing, and
attached full evidence. This addendum is that 户部 ruling.

**Decision: path (b) — a 户部-endorsed DETERMINISTIC mechanical rule** (superior to a manual
per-wave fold: reproducible, auto-handles refill, auditable — the same reason the universe
resolver itself chose (b) over a hand list). 都水 is the deterministic **executor + full
per-name trace**; the **rule and the reviewed hit-list are 户部口径**. 都察院 audits the rule
+ 都水's classification log.

---

## C1. The mechanical exclusion rule (户部-endorsed, deterministic)

A stage-0 survivor is **EXCLUDED** as ADR / foreign-primary if it matches **R0 ∪ R1 ∪ R2 ∪
R3** AND is not on the C2 KEEP carve-out:

- **R0 — curated list:** the ticker is in `RESIDUAL_ADR_EXCLUDE.txt` (145 sponsored/exchange
  ADRs **+ the 87 `-Y`/name-token hits appended in this commit**, 户部-reviewed).
- **R1 — name token:** the OpenD `get_stock_basicinfo` `name` (or `name_en`) contains, case-
  insensitive, any of: `ADR`, `ADS`, `AMERICAN DEPOSITARY`, `DEPOSITARY`, `UNSPON`,
  `UNSPONSORED`, `SPON ADR`, `SPONSORED ADR`.
- **R2 — OTC foreign-ticker convention:** the base ticker (strip `US.` prefix; keep the raw
  symbol) is a **5-character alphabetic symbol whose 5th letter is `Y`** (unsponsored-ADR
  convention) **or `F`** (foreign-ordinary-share OTC convention). `-Y` is the empirically
  dominant tail (86/87 here); `-F` is included for refill-wave completeness (same SEC/OTC
  convention).
- **R3 — dotted foreign class:** a foreign issuer's non-common / preferred line (e.g.,
  `PBR.A` = Petrobras preferred ADR) — caught by R0/R1 (name contains the issuer + preferred/
  ADR) and matched on the base issuer.

**Mandatory per-name verification (the false-positive backstop):** every R1/R2/R3 hit is
verified via OpenD `get_stock_basicinfo`; a hit whose name resolves to a **US-domiciled /
US-primary** issuer is **KEPT** (logged as a carve-out), never dropped. So even a rare
`-Y`/`-F` US ticker cannot be silently excluded — the name-verification + C2 carve-out
guarantee zero US-common mis-exclusion. (Empirically, the 209 clean set contained **no**
`-Y`/`-F` name; the rule's precision on this 296 is exact.)

## C2. KEEP carve-out (override — NEVER exclude even if a rule matches)

Explicit US-primary common that must survive any rule match (belt-and-suspenders — none of
these are 5-letter `-Y`/`-F`, so R2 does not touch them, but pinned for auditability):
`CB, AON, SLB, CRH, LIN, MELI, BRK.A, BRK.B, ACN, MDT, ETN, JCI, AER, FERG, FLUT, YUMC`
— re-domiciled / tax-inverted but **US-primary ordinary common, US-session price formation,
US operating exposure** → treated as US common. **Rule:** if a name-verified issuer is
US-domiciled / US-primary, KEEP it regardless of ticker shape. (都水 confirmed the 209 clean
scan flagged only `CB/AON/SLB/CRH` on a foreign-form scan — all correctly kept.)

## C3. 户部 review of 都水's 87-hit list — ENDORSED

I reviewed 都水's 87-hit classification (verified each via `get_stock_basicinfo`) and
spot-checked the identities: `NSRGY`=Nestlé, `RHHBY`=Roche, `LVMUY`=LVMH, `TCEHY`=Tencent,
`BYDDY`=BYD, `SIEGY`=Siemens, `DTEGY`=Deutsche Telekom, `BNPQY`=BNP, `AXAHY`=AXA,
`ZURVY`=Zurich, `IDCBY`=ICBC, `MITSY`=Mitsubishi, `KDDIY`=KDDI, `IBDRY`=Iberdrola,
`ISNPY`=Intesa Sanpaolo, `PROSY`=Prosus, `NABZY`=NAB, `MQBKY`=Macquarie, `ANZGY`=ANZ,
`PBR.A`=Petrobras pref — **all foreign issuers, classification correct**. Discriminating
check: `IDEXY`(IDEX ASA, Norway) is excluded while US IDEX Corp trades as `IEX` (3-letter,
kept); `WFAFY`(Wesfarmers, Australia) is excluded while US Wells Fargo trades as `WFC`
(kept) — the `-Y` convention cleanly separates them. **户部 endorses the 87 as foreign; they
are appended to `RESIDUAL_ADR_EXCLUDE.txt` in this commit.**

## C4. Process (都水 executor; 户部 author) & disclosure (mandatory)

1. Apply R0∪R1∪R2∪R3 to the stage-0 survivors; **verify each hit via `get_stock_basicinfo`**;
   log `{ticker, matched_rule, name, classification: foreign_excluded | us_keep}`.
2. Exclude confirmed-foreign hits; **refill from rank 297+ and re-apply the rule; iterate**
   until 296 clean US-common candidates are assembled.
3. Commit the full classification log (`RESIDUAL_UNIVERSE_ADR_CLASSIFICATION.json`) + the
   refill trace **alongside** `RESIDUAL_UNIVERSE_RESOLVED.txt`, **strictly before any results
   commit**. This log — not a hand list — is the 都察院-auditable artifact of the rule's output.
4. **Disclose in the resolve/run log (for 都察院):** operative pre-screen key = `MARKET_VAL`
   ((ii) fallback) and its selection effect — the superset is **market-cap-pre-screened**, the
   final 250 is **60-day-dollar-volume-ranked**; the MARKET_VAL fallback is what surfaced the
   ADR contamination (high market cap, low US liquidity). Also disclose: total excluded by the
   rule, refill depth, and any residual unidentified foreign name (bounded, cannot turn a fail
   into a pass — same discipline as survivorship, per ADDENDUM A / the §A2 residual clause).

## C5. Author identity & guards

- **口径 author = 户部** (this addendum + the reviewed list appended to the exclude file); 都水
  is a deterministic executor + full trace. This preserves the three-way-verification premise
  that 都察院 reviews **户部口径**, not a 都水 reclassification.
- If, after the rule + refill, clean US-common candidates are still < 250, the universe is that
  smaller count **labelled `数据不足`, never padded** (工部 notes 1402 ≥$10B survivors exist, so a
  full 250 is expected — but the honesty rule stands regardless).
- **Non-blocking safety net unchanged:** any well-known ADR the rule somehow misses, add to
  `RESIDUAL_ADR_EXCLUDE.txt` before the results commit (still before results; chronology intact).
- Any deviation from C1–C4 stops and is reported. This addendum is SIMULATE / quote-only scope,
  consistent with the frozen data boundary.
