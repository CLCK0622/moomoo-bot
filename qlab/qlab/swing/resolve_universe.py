"""EVO-162 C1 universe resolver — deterministic two-stage screen (frozen ADDENDUM A).

Implements ``RESIDUAL_REVERSAL_PREREG_ADDENDUM_A_universe.md`` (户部, commit ``b0b80a6``,
frozen before any resolved-universe list / real result) verbatim — no口径 changed. Only
this file is new/edited; the EVO-149/130/23 judgment stack and the residual engine are
untouched. The prereg-literal 60-day dollar-volume ranking idiom is preserved as the FINAL
selector; Stage-0 is only the quota-forced pre-filter.

Two stages (A1):

* **Stage-0 — zero-quota pre-screen** (``get_stock_filter``, US market; NO historical-K
  quota). In order: (1) security type = US common stock (drop ETF/ETN/CEF, preferred,
  warrant, unit, pre-merger SPAC; **REIT kept**; unconfirmable ⇒ dropped, conservative);
  (2) market cap ≥ US$10B; (3) rank by a dollar-volume proxy — **priority (i) snapshot
  dollar-volume** if ``get_stock_filter`` exposes a volume field, **(ii) fallback
  ``MARKET_VAL``** otherwise (都水's host finding — US volume fields are unfilterable) — the
  actual key used is recorded; (4) **ADDENDUM C mechanical ADR/foreign classifier** on the
  ranked survivors (moomoo has no ADR flag, so ADRs class as STOCK): a survivor is EXCLUDED
  if it matches R0 (curated ``RESIDUAL_ADR_EXCLUDE.txt``) ∪ R1 (name token ADR/depositary) ∪
  R2 (5-letter ``-Y``/``-F`` OTC convention) ∪ R3 (dotted foreign class on a curated base)
  AND is not on the C2 KEEP carve-out (name-verified US-primary); confirmed-foreign hits are
  dropped and **refilled from rank 297+, re-scanned, iterated until the top-296 are clean US
  common**; the full ``{ticker,matched_rule,name,classification}`` log + refill trace is the
  都察院-auditable ``RESIDUAL_UNIVERSE_ADR_CLASSIFICATION.json`` (都水 commits it, before results).
* **Stage-1 — quota fetch + prereg-literal ranking** (``fetch_daily_parquet(superset ∪
  {SPY,IWM,IVE,IVW})`` then this resolver over the real daily bars): compute the
  **prereg-literal 60-trading-day average dollar volume** ``mean(close × volume)`` → rank →
  A2 dual-class de-duplication (keep the single class with higher 60d $-vol per issuer; tie
  ≤5% ⇒ alphabetically-first ticker) → borrowability top-down substitution → take **top 250**.

**Selection-effect log (mandatory in the resolved commit, A1):** the Stage-0 key used, the
296-name superset, the pre-screen-key value AND 60d $-vol of the 296th name (the cut
threshold), and the per-step exclusion counts. Any name outside the Stage-0 top-296 that
*would* have entered the 60d top-250 is unobservable under the quota — a bounded, disclosed
selection effect that (per prereg §2/§13) **cannot turn a fail into a pass**.

**Stage-0 needs an OpenD gateway (host-only).** The gateway calls are isolated in
:class:`OpenDStockFilterProvider`; every deterministic decision (type/cap/rank/cut, dedup,
borrow substitution, <250 honest labelling) lives in pure functions unit-tested with mocks.
Per ADDENDUM A4 / the 工部 handoff, this file does NOT commit ``RESIDUAL_UNIVERSE_RESOLVED.txt``
— that is 都水's host-side product, committed before any results commit; here we ship code + tests.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import pandas as pd

from .residual_signals import FACTOR_ETFS

MIN_HISTORY_WEEKS = 156
TRADING_DAYS_PER_WEEK = 5
ADVOL_DAYS = 60
SUPERSET_SIZE = 296                 # A3: 300 quota hard cap − 4 factor ETFs
MARKET_CAP_FLOOR = 1.0e10           # A1 rule 2: US$10B large-cap floor (a-priori round number)
TARGET_N = 250                      # prereg §2 frozen universe size
DUAL_CLASS_TIE_PCT = 0.05           # A2: tie within 5% ⇒ alphabetically-first ticker

# Stage-0 rule 1: moomoo security types kept vs excluded. REITs are SecurityType.STOCK on
# moomoo (US common equity) ⇒ naturally kept. Anything not a plain common STOCK is dropped.
COMMON_STOCK_SEC_TYPES = {"STOCK"}
EXCLUDED_SEC_TYPES = {"ETF", "ETN", "CEF", "PREFERRED", "WARRANT", "UNIT", "SPAC", "ADR",
                      "IDX", "BOND", "DRVT", "FUND", "TRUST_FUND"}

# ADR caveat (empirically verified against a live OpenD gateway, 2026-07-11): moomoo classifies
# US-listed ADRs as ``SecurityType.STOCK`` with ``stock_child_type='N/A'`` and empty
# ``stock_owner`` — there is NO field that flags an ADR / foreign-domiciled name. So §A2's ADR
# exclusion CANNOT be automated from moomoo type fields; it needs a curated exclude list. We seed
# it with the ADDENDUM-A-named examples and let 都水 extend it on the host via ``--exclude-file``.
# Residual ADR contamination (a big ADR ranked into the top-296 that no list caught) is a bounded,
# disclosed selection effect — like survivorship, it cannot turn a fail into a pass (§A1/§A3).
ADDENDUM_A_NAMED_ADRS = ("TSM", "LYG", "RACE")

# Stage-0 rule 3(i): candidate zero-quota share-volume fields, probed at runtime against the
# SDK's StockField enum (NOT hardcoded as the only path). First present one wins; if none is
# available the resolver falls back to MARKET_VAL (rule 3(ii)). 都水 confirms against the
# live gateway and the resolved log records which key was actually used.
PRESCREEN_VOLUME_FIELD_CANDIDATES = ("VOLUME", "AVG_VOLUME_5D", "AVG_VOLUME_10D",
                                     "AVG_VOLUME_30D", "AVG_VOL_5D", "AVG_VOL_10D")


# --------------------------------------------------------------------------- #
# A2 — issuer key + dual-class de-duplication (pure)
# --------------------------------------------------------------------------- #
_CLASS_TOKEN_RE = re.compile(r"\b(class|cl|series|ser)\s+[a-z0-9]\b", re.I)
_LEGAL_SUFFIX_RE = re.compile(
    r"\b(incorporated|inc|corporation|corp|company|co|limited|ltd|plc|llc|lp|holdings?|"
    r"group|trust|sa|nv|ag)\b", re.I)


def issuer_key(name: str | None, code: str) -> str:
    """Deterministic issuer identity for dual-class grouping.

    Primary: the normalized company name (share it ⇒ same issuer), stripping class/series
    designations and legal suffixes — so 'Alphabet Inc. Class A' (GOOGL) and 'Alphabet Inc.
    Class C' (GOOG) collapse to the same key. Fallback (no name): the ticker base (drop a
    ``.A``/``.B`` class suffix), so BRK.A/BRK.B still group.
    """
    if name and name.strip():
        s = name.lower()
        s = re.sub(r"[.,&/\-'’]", " ", s)
        s = _CLASS_TOKEN_RE.sub(" ", s)
        s = _LEGAL_SUFFIX_RE.sub(" ", s)
        s = re.sub(r"\s+", " ", s).strip()
        if s:
            return s
    c = code.upper()
    return c.split(".")[0] if "." in c else c


def dedup_dual_class(ranked: list[dict], *, tie_pct: float = DUAL_CLASS_TIE_PCT) -> tuple[list[dict], list[dict]]:
    """Keep one class per issuer — the higher 60d dollar volume; tie ≤ ``tie_pct`` ⇒
    alphabetically-first ticker. ``ranked`` items carry ``code``, ``dollar_volume``,
    ``issuer``. Returns ``(kept_in_original_rank_order, drops)``.
    """
    groups: dict[str, list[dict]] = {}
    for r in ranked:
        groups.setdefault(r["issuer"], []).append(r)

    winners: dict[str, str] = {}
    drops: list[dict] = []
    for issuer, members in groups.items():
        if len(members) == 1:
            winners[issuer] = members[0]["code"]
            continue
        ms = sorted(members, key=lambda r: (-r["dollar_volume"], r["code"]))
        top_dv = ms[0]["dollar_volume"]
        tied = [m for m in ms if top_dv > 0 and (top_dv - m["dollar_volume"]) / top_dv <= tie_pct]
        winner = min(tied, key=lambda r: r["code"]) if len(tied) > 1 else ms[0]
        winners[issuer] = winner["code"]
        for m in members:
            if m["code"] != winner["code"]:
                drops.append({"dropped": m["code"], "kept": winner["code"], "issuer": issuer,
                              "dropped_dvol": m["dollar_volume"], "kept_dvol": winner["dollar_volume"],
                              "tie_within_pct": bool(top_dv > 0
                                                     and (top_dv - m["dollar_volume"]) / top_dv <= tie_pct)})
    kept_codes = set(winners.values())
    kept_ordered = [r for r in ranked if r["code"] in kept_codes]
    return kept_ordered, drops


# --------------------------------------------------------------------------- #
# Stage-0 — pre-screen selection (pure; operates on provider records)
# --------------------------------------------------------------------------- #
def choose_prescreen_key(available_fields, *, priority=PRESCREEN_VOLUME_FIELD_CANDIDATES
                         ) -> tuple[str, str]:
    """Pick the Stage-0 ranking key by A1 rule-3 priority.

    Returns ``("snapshot_dollar_volume", <vol_field>)`` if any priority volume field is
    available (rule 3(i)), else ``("market_val", "MARKET_VAL")`` (rule 3(ii)).
    """
    avail = {str(f).upper() for f in (available_fields or [])}
    for f in priority:
        if f.upper() in avail:
            return "snapshot_dollar_volume", f.upper()
    return "market_val", "MARKET_VAL"


def _is_common_us(rec: dict) -> tuple[bool, str]:
    """(keep?, drop_reason). Conservative: only confirmed US common STOCK is kept. ADR/foreign
    curated exclusion is NOT done here — it is the addendum-C classifier's R0 (so R0 hits appear
    in the classification log), applied on the ranked survivors."""
    market = str(rec.get("market", "US")).upper()
    if market not in ("US", "US."):
        return False, "non_us_market"
    if rec.get("is_common") is False:
        return False, "flagged_non_common"          # provider-flagged ADR/foreign
    sec_type = str(rec.get("sec_type", "")).upper()
    if sec_type in EXCLUDED_SEC_TYPES:
        return False, "excluded_sec_type"
    if sec_type and sec_type not in COMMON_STOCK_SEC_TYPES:
        return False, "unconfirmed_common"           # unknown type ⇒ excluded (conservative)
    return True, ""


def _prescreen_value(rec: dict, mode: str) -> float | None:
    if mode == "snapshot_dollar_volume":
        cp, vol = rec.get("cur_price"), rec.get("volume")
        if cp is None or vol is None:
            return None
        try:
            v = float(cp) * float(vol)
        except (TypeError, ValueError):
            return None
        return v if v > 0 else None
    mv = rec.get("market_val")
    try:
        v = float(mv)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


# --------------------------------------------------------------------------- #
# ADDENDUM C — mechanical ADR / foreign-primary classifier + refill (frozen 9f34ae5)
# --------------------------------------------------------------------------- #
# 都水's host run found the MARKET_VAL fallback (A1 rule 3(ii)) pulls mega-cap FOREIGN OTC ADRs
# into the top-296 (Nestlé, Roche, LVMH, Tencent…): 87/296 (29%) were foreign, the static list
# alone caught only the sponsored/exchange ADRs and missed the 5-letter `-Y` unsponsored tail.
# 户部 froze addendum C: a deterministic rule R0∪R1∪R2∪R3 with a mandatory get_stock_basicinfo
# name-verification + C2 KEEP carve-out (zero US-common mis-exclusion), applied on the ranked
# survivors with refill-from-297+ iteration until the top-296 are all clean US common.

# R1 name token (户部/都水-calibrated regex): ADR/ADS/unsponsored/sponsored-ADR/depositary
_ADR_NAME_RE = re.compile(r"(ADR|ADS|UNSPON|SPON ADR|DEPOSITAR)", re.I)

# C2 KEEP carve-out (§C2): US-primary ordinary common (re-domiciled / tax-inverted) that must
# survive ANY rule match — none are 5-letter -Y/-F so R2 never touches them, pinned for audit.
ADR_KEEP_CARVEOUT = frozenset({"CB", "AON", "SLB", "CRH", "LIN", "MELI", "BRK.A", "BRK.B", "ACN",
                               "MDT", "ETN", "JCI", "AER", "FERG", "FLUT", "YUMC"})


def _adr_match_rule(code: str, name: str | None, curated_adr: set[str]) -> str | None:
    """Which addendum-C rule (if any) flags ``code`` as an ADR/foreign candidate — R0∪R1∪R2∪R3."""
    c = code.upper()
    base = c.split(".")[0]
    if c in curated_adr:
        return "R0"                                  # curated list (户部-reviewed, incl. 87 -Y tail)
    if _ADR_NAME_RE.search(name or ""):
        return "R1"                                  # name token (ADR / depositary / unsponsored)
    if len(base) == 5 and base.isalpha() and base[-1] in ("Y", "F"):
        return "R2"                                  # 5-letter OTC convention: -Y ADR / -F foreign
    if "." in c and base in curated_adr:
        return "R3"                                  # dotted foreign class matched on base issuer
    return None


def _adr_verdict(code: str, name: str | None, curated_adr: set[str],
                 keep_codes: set[str]) -> tuple[bool, str | None, str]:
    """(excluded?, matched_rule, classification). C2 carve-out is the false-positive backstop:
    a rule hit that name-verifies as US-primary is KEPT, never dropped (zero US-common loss)."""
    rule = _adr_match_rule(code, name, curated_adr)
    if rule is None:
        return False, None, "us_common"
    if code.upper() in keep_codes:
        return False, rule, "us_keep"                # §C2 KEEP carve-out (name-verified US-primary)
    return True, rule, "foreign_excluded"


def adr_classify_and_refill(survivors: list[dict], *, curated_adr: set[str], keep_codes: set[str],
                            superset_size: int) -> tuple[list[str], dict, list, int]:
    """Assemble ``superset_size`` CLEAN US-common candidates from ranked ``survivors`` (§C4).

    Classify the top ``superset_size``; drop confirmed-foreign; refill from rank 297+ and re-apply
    the rule; iterate until a wave adds no new exclusions (converged) or the pool is exhausted.
    Returns ``(clean_codes_in_rank_order, classification, refill_waves, scan_depth)``. Never pads —
    an exhausted pool yields < ``superset_size`` clean names (honest, labelled upstream).
    """
    curated_adr = {c.upper() for c in curated_adr}
    keep_codes = {c.upper() for c in keep_codes}
    classification: dict[str, dict] = {}

    def _classify(rec) -> bool:
        code = str(rec["code"]).upper()
        name = rec.get("name") or ""
        excluded, rule, cls = _adr_verdict(code, name, curated_adr, keep_codes)
        classification[code] = {"ticker": code, "matched_rule": rule, "name": name,
                                "classification": cls}
        return excluded

    superset, waves, nxt = [], [], 0
    while nxt < len(survivors) and len(superset) < superset_size:
        superset.append(survivors[nxt])
        nxt += 1
    wave = 0
    while True:
        newly_excluded, kept = [], []
        for rec in superset:
            code = str(rec["code"]).upper()
            excluded = (classification[code]["classification"] == "foreign_excluded"
                        if code in classification else _classify(rec))
            (newly_excluded if excluded else kept).append(rec)
        waves.append({"wave": wave, "scanned": len(superset),
                      "excluded": [str(r["code"]).upper() for r in newly_excluded],
                      "n_excluded": len(newly_excluded), "clean_kept": len(kept)})
        superset = kept
        if not newly_excluded:
            break
        while nxt < len(survivors) and len(superset) < superset_size:
            superset.append(survivors[nxt])
            nxt += 1
        wave += 1
        if wave > len(survivors) + 2:                # safety: cannot exceed pool size
            break
    clean_codes = [str(r["code"]).upper() for r in superset]
    return clean_codes, classification, waves, nxt


def stage0_select(records: list[dict], *, prescreen_mode: str, prescreen_key: str,
                  market_cap_floor: float = MARKET_CAP_FLOOR, superset_size: int = SUPERSET_SIZE,
                  curated_adr: set[str] | None = None,
                  keep_carveout: set[str] = ADR_KEEP_CARVEOUT) -> dict:
    """Deterministic Stage-0: type + cap filter → rank by pre-screen key → **addendum-C ADR
    classify + refill** → top ``superset_size`` CLEAN US-common candidates.

    ``records`` are raw provider rows (``{code, name, sec_type, market, market_val, cur_price,
    volume, is_common?}``). ``curated_adr`` is the R0 list (from ``RESIDUAL_ADR_EXCLUDE.txt``).
    Returns the clean superset, the cut threshold, per-step exclusion counts, the full ADR
    classification log + refill trace, and an ``issuer_by_code`` map for Stage-1 de-dup.
    """
    curated_adr = {c.upper() for c in (curated_adr or set())}
    factor_set = {s.upper() for s in FACTOR_ETFS}
    excluded = {"factor_etf": [], "non_us_market": [], "flagged_non_common": [],
                "excluded_sec_type": [], "unconfirmed_common": [], "below_cap": [],
                "no_prescreen_value": []}
    survivors = []
    for rec in records:
        code = str(rec.get("code", "")).upper()
        if code in factor_set:                       # 4 factor ETFs are regressors, never candidates
            excluded["factor_etf"].append(code)
            continue
        keep, reason = _is_common_us(rec)
        if not keep:
            excluded[reason].append(code)
            continue
        try:
            mv = float(rec.get("market_val"))
        except (TypeError, ValueError):
            mv = None
        if mv is None or mv < market_cap_floor:
            excluded["below_cap"].append(code)
            continue
        pv = _prescreen_value(rec, prescreen_mode)
        if pv is None:
            excluded["no_prescreen_value"].append(code)
            continue
        survivors.append({"code": code, "name": rec.get("name"), "market_val": mv,
                          "prescreen_value": pv})

    survivors.sort(key=lambda r: (-r["prescreen_value"], r["code"]))

    # ADDENDUM C: mechanical ADR/foreign classify + refill on the ranked survivors
    clean_codes, adr_class, refill_waves, scan_depth = adr_classify_and_refill(
        survivors, curated_adr=curated_adr, keep_codes=keep_carveout, superset_size=superset_size)
    by_code = {r["code"]: r for r in survivors}
    superset_full = [by_code[c] for c in clean_codes]
    cut_value = superset_full[-1]["prescreen_value"] if len(clean_codes) >= superset_size else None

    adr_excluded = [r for r in adr_class.values() if r["classification"] == "foreign_excluded"]
    by_rule: dict[str, int] = {}
    for r in adr_excluded:
        by_rule[r["matched_rule"]] = by_rule.get(r["matched_rule"], 0) + 1
    carveouts = [r["ticker"] for r in adr_class.values() if r["classification"] == "us_keep"]

    return {
        "prescreen_mode": prescreen_mode, "prescreen_key": prescreen_key,
        "market_cap_floor": market_cap_floor, "superset_size_target": superset_size,
        "n_input": len(records), "n_survivors_prefilter": len(survivors),
        "superset": clean_codes, "superset_count": len(clean_codes),
        "cut_prescreen_value_296th": cut_value,
        "superset_full": superset_full,
        "issuer_by_code": {c: issuer_key(by_code[c].get("name"), c) for c in clean_codes},
        "excluded_counts": {k: len(v) for k, v in excluded.items()},
        "excluded_codes": excluded,
        "pool_sufficient_for_superset": len(clean_codes) >= superset_size,
        # addendum-C ADR classifier outputs (the 都察院-auditable artifact)
        "adr_classification": adr_class,
        "adr_excluded_count": len(adr_excluded),
        "adr_excluded_by_rule": by_rule,
        "adr_keep_carveouts": carveouts,
        "adr_refill_waves": refill_waves,
        "adr_refill_depth": len(refill_waves),
        "adr_scan_depth": scan_depth,
    }


# --------------------------------------------------------------------------- #
# Stage-1 — prereg-literal 60d $-vol rank + de-dup + borrow substitution (pure)
# --------------------------------------------------------------------------- #
def stage1_resolve(dollar_vol_by_code: dict, *, issuer_by_code: dict | None = None,
                   borrowable: set[str] | None = None, top_n: int = TARGET_N,
                   stage0_log: dict | None = None) -> dict:
    """Rank the superset by real 60d dollar volume, de-dup dual classes, apply borrow
    substitution, take top ``top_n``. Never pads: fewer than ``top_n`` clean names ⇒ the
    universe is that smaller count, labelled honestly.
    """
    issuer_by_code = issuer_by_code or {}
    ranked = [{"code": c.upper(), "dollar_volume": float(dv),
               "issuer": issuer_by_code.get(c.upper()) or issuer_key(None, c)}
              for c, dv in dollar_vol_by_code.items() if dv is not None and float(dv) > 0]
    ranked.sort(key=lambda r: (-r["dollar_volume"], r["code"]))

    deduped, dedup_drops = dedup_dual_class(ranked, tie_pct=DUAL_CLASS_TIE_PCT)

    substitutions = []
    if borrowable is not None:
        borrowable = {s.upper() for s in borrowable}
        borrow_ok, dropped = [], []
        for r in deduped:
            if r["code"] in borrowable:
                borrow_ok.append(r)
            else:
                dropped.append(r["code"])
        if dropped:
            substitutions.append({"dropped_non_borrowable": dropped,
                                  "note": "walked top-down; each non-borrowable slot filled by the "
                                          "next-ranked borrowable survivor (pre-results, logged)"})
        final_ranked = borrow_ok
    else:
        final_ranked = deduped

    selected = [r["code"] for r in final_ranked[:top_n]]
    clean_count = len(final_ranked)
    cut_60d = final_ranked[top_n - 1]["dollar_volume"] if clean_count >= top_n else None

    sel = {
        "target_n": top_n, "selected": selected, "selected_count": len(selected),
        "n_ranked": len(ranked), "n_after_dedup": len(deduped),
        "n_after_borrow": clean_count,
        "clean_names_below_target": bool(clean_count < top_n),
        "padded": False,                              # NEVER padded (A3)
        "cut_60d_dollar_volume_250th": cut_60d,
        "dual_class_drops": dedup_drops,
        "borrow_substitutions": substitutions,
        "borrow_filter_applied": borrowable is not None,
        "ranking_60d": final_ranked,
    }
    if clean_count < top_n:
        sel["shortfall_note"] = (
            f"only {clean_count} clean borrowable names after A2 de-dup/borrow "
            f"(< target {top_n}); the universe is that smaller count, labelled honestly and "
            f"NOT padded (A3). Deciles need breadth — a thin book is 数据不足, not a verdict.")

    # merge the Stage-0 selection-effect record + the 60d $-vol of the 296th cut name
    if stage0_log is not None:
        cut_code = (stage0_log.get("superset") or [None])[-1] if stage0_log.get("superset") else None
        sel["selection_effect"] = {
            "stage0_prescreen_key": stage0_log.get("prescreen_key"),
            "stage0_prescreen_mode": stage0_log.get("prescreen_mode"),
            "superset_size": stage0_log.get("superset_count"),
            "cut_296th_code": cut_code,
            "cut_296th_prescreen_value": stage0_log.get("cut_prescreen_value_296th"),
            "cut_296th_60d_dollar_volume": (dollar_vol_by_code.get(cut_code)
                                            if cut_code is not None else None),
            "stage0_excluded_counts": stage0_log.get("excluded_counts"),
            "stage1_dual_class_dropped": len(dedup_drops),
            "stage1_non_borrowable_dropped": sum(len(s.get("dropped_non_borrowable", []))
                                                 for s in substitutions),
            "disclosure": ("names ranked outside the Stage-0 top-296 that would have entered the "
                           "60d-dollar-volume top-250 are unobservable under the ≤300 quota — a "
                           "bounded, disclosed selection effect that cannot turn a fail into a pass "
                           "(prereg §2/§13)."),
        }
    return sel


# --------------------------------------------------------------------------- #
# Stage-1 driver over local parquet (host, after the quota fetch)
# --------------------------------------------------------------------------- #
def _dollar_volume_and_history(path: Path, advol_days: int) -> tuple[float, int] | None:
    """Return ``(mean(close×volume) over last advol_days bars, n_bars)`` or ``None``."""
    try:
        df = pd.read_parquet(path)
    except Exception:  # noqa: BLE001
        return None
    df = df.rename(columns={c: c.lower() for c in df.columns})
    if "close" not in df.columns or "volume" not in df.columns or "date" not in df.columns:
        return None
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df = df[(df["close"] > 0) & (df["volume"] >= 0)].sort_values("date")
    n = int(len(df))
    if n == 0:
        return None
    tail = df.tail(advol_days)
    return float((tail["close"] * tail["volume"]).mean()), n


def dollar_volumes_from_parquet(data_dirs, codes, *, advol_days: int = ADVOL_DAYS,
                                min_history_weeks: int = MIN_HISTORY_WEEKS
                                ) -> tuple[dict, list, list]:
    """Compute 60d $-vol for each ``code`` from local bars. Returns
    ``(dollar_vol_by_code, too_short, unreadable)``; short-history / unreadable names are
    dropped and reported (never silently kept)."""
    min_bars = min_history_weeks * TRADING_DAYS_PER_WEEK
    dv, too_short, unreadable = {}, [], []
    for code in codes:
        found = None
        for d in data_dirs:
            p = Path(d) / f"{code}_1d.parquet"
            if p.exists():
                found = p
                break
        if found is None:
            unreadable.append(code)
            continue
        res = _dollar_volume_and_history(found, advol_days)
        if res is None:
            unreadable.append(code)
            continue
        advol, n_bars = res
        if n_bars < min_bars:
            too_short.append({"symbol": code, "n_bars": n_bars, "weeks": round(n_bars / 5, 1)})
            continue
        dv[code.upper()] = advol
    return dv, too_short, unreadable


# --------------------------------------------------------------------------- #
# Stage-0 gateway provider (host-only; isolated so the rest is testable)
# --------------------------------------------------------------------------- #
class OpenDStockFilterProvider:
    """Thin, defensive ``get_stock_filter`` / ``get_stock_basicinfo`` wrapper (US market).

    Isolates ALL gateway I/O so :func:`stage0_select` stays pure and unit-tested. Field names
    are PROBED against the live SDK enum, never hardcoded as the only path — 都水 runs this on
    the OpenD host and the resolved log records the key actually used. Raises
    :class:`OpenDUnavailable` (from :mod:`qlab.events.datafetch.opend_daily`) if the SDK /
    gateway is absent, so a no-gateway environment reports a clear blocker instead of failing
    obscurely.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 11111, page: int = 200,
                 pause: float = 3.0):
        # pause ≥3s between get_stock_filter pages: 都水 hit the 10-calls/30s rate limit
        # ("high frequency"/"TimeOut") when paging ~7 pages × multiple refill waves.
        self.host, self.port, self.page, self.pause = host, port, page, pause

    def _sdk(self):
        try:
            import moomoo  # noqa: F401
        except Exception as exc:  # noqa: BLE001
            from ..events.datafetch.opend_daily import OpenDUnavailable
            raise OpenDUnavailable(
                "moomoo SDK not importable — Stage-0 get_stock_filter needs a host with the "
                f"moomoo-api package and a reachable OpenD gateway. Underlying error: {exc!r}") from exc
        return moomoo

    def available_volume_field(self, priority=PRESCREEN_VOLUME_FIELD_CANDIDATES) -> str | None:
        m = self._sdk()
        names = {n.upper() for n in dir(m.StockField)}
        for f in priority:
            if f.upper() in names:
                return f.upper()
        return None

    @staticmethod
    def _simple_filter(m, stock_field, *, filter_min=None, is_no_filter=False, descending=False):
        """Build a moomoo ``SimpleFilter`` via attribute assignment (its ``__init__`` is empty).

        ``sort`` uses the SDK's descending enum, probed defensively (``DESCEND``, else the
        first non-``NONE`` sort key) so a version that renames it does not crash.
        """
        sf = m.SimpleFilter()
        sf.stock_field = stock_field
        sf.is_no_filter = is_no_filter
        if filter_min is not None:
            sf.filter_min = filter_min
        if descending:
            sd = m.SortDir
            sf.sort = (getattr(sd, "DESCEND", None) or getattr(sd, "DOWN", None)
                       or getattr(sd, "FALL", None) or getattr(sd, "DESC", None))
        return sf

    def screen(self, *, market_cap_floor: float, prescreen_mode: str,
               prescreen_key: str) -> list[dict]:
        """Page US large-caps via ``get_stock_filter``; enrich type/name via
        ``get_stock_basicinfo(US, STOCK)``. Returns raw records for :func:`stage0_select`.

        Raises on any gateway/API error (connection refused, field not usable for US, …) so
        the caller can probe→fallback or surface a clear host-side blocker — never a crash.
        """
        m = self._sdk()
        ctx = m.OpenQuoteContext(host=self.host, port=self.port)
        try:
            # common-stock type set + names (SecurityType.STOCK excludes ETF/IDX/BOND/DRVT/… at
            # the type level; moomoo has no separate ADR/preferred type, so those confirm via the
            # curated exclude list + the conservative "unconfirmed ⇒ drop" rule downstream).
            common_names: dict[str, str] = {}
            try:
                ret, basic = ctx.get_stock_basicinfo(m.Market.US, m.SecurityType.STOCK)
                if ret == m.RET_OK and basic is not None and len(basic):
                    for _, row in basic.iterrows():
                        # normalize the same way as the filter codes (strip the "US." prefix)
                        code = str(row["code"]).upper().replace("US.", "")
                        common_names[code] = str(row.get("name", ""))
            except Exception:  # noqa: BLE001 — enrichment only; absence ⇒ conservative later
                common_names = {}

            filters = [self._simple_filter(m, m.StockField.MARKET_VAL,
                                           filter_min=market_cap_floor, descending=True)]
            # retrieve cur_price / volume so snapshot $-vol can be computed (no-filter passthrough)
            extra = ["CUR_PRICE"]
            if prescreen_mode == "snapshot_dollar_volume":
                extra.append(prescreen_key)
            for fld in extra:
                if fld and hasattr(m.StockField, fld):
                    filters.append(self._simple_filter(m, getattr(m.StockField, fld), is_no_filter=True))

            records, begin, page_no = [], 0, 0
            while True:
                if page_no > 0 and self.pause > 0:
                    time.sleep(self.pause)           # rate-limit backoff (10 calls / 30s cap)
                page_no += 1
                ret, data = ctx.get_stock_filter(m.Market.US, filter_list=filters,
                                                 begin=begin, num=self.page)
                if ret != m.RET_OK:
                    raise RuntimeError(f"get_stock_filter(US) failed: {data}")
                # success shape is a 3-tuple; parse by TYPE (list=items, bool=last_page) so a
                # version that reorders (list, bool, count) vs (last_page, count, list) still works.
                if not (isinstance(data, tuple) and len(data) == 3):
                    raise RuntimeError(f"get_stock_filter(US) unexpected return: {data!r}")
                items = next((e for e in data if isinstance(e, list)), [])
                last_page = next((e for e in data if isinstance(e, bool)), True)
                for it in items:
                    code = str(getattr(it, "stock_code", "")).upper().replace("US.", "")
                    records.append({
                        "code": code,
                        "name": common_names.get(code, getattr(it, "stock_name", "")),
                        "sec_type": "STOCK" if code in common_names else "UNKNOWN",
                        "is_common": (code in common_names) if common_names else None,
                        "market": "US",
                        "market_val": getattr(it, "market_val", None),
                        "cur_price": getattr(it, "cur_price", None),
                        "volume": getattr(it, prescreen_key.lower(), getattr(it, "volume", None)),
                    })
                begin += self.page
                if last_page or not items:
                    break
            return records
        finally:
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass


def run_stage0(provider: OpenDStockFilterProvider, *, market_cap_floor: float = MARKET_CAP_FLOOR,
               superset_size: int = SUPERSET_SIZE, curated_adr: set[str] | None = None) -> dict:
    """Probe the pre-screen key with **runtime fallback**, screen, and apply :func:`stage0_select`.

    A1 rule 3: try priority (i) snapshot dollar-volume with the highest-priority volume field
    the SDK exposes; if that screen fails at *runtime* (field not usable for US — 都水's
    ``TURNOVER`` finding), fall back to (ii) ``MARKET_VAL``. The key actually used and the
    attempt trail are recorded in the log. A failure of BOTH attempts (e.g. gateway down)
    propagates to the caller as a blocker. ``curated_adr`` seeds the addendum-C R0 list.
    """
    vol_field = provider.available_volume_field()
    attempts: list[tuple[str, str]] = []
    if vol_field:
        attempts.append(choose_prescreen_key([vol_field]))     # (i) snapshot $-vol
    attempts.append(("market_val", "MARKET_VAL"))              # (ii) fallback
    tried, last_exc = [], None
    for mode, key in attempts:
        try:
            records = provider.screen(market_cap_floor=market_cap_floor,
                                      prescreen_mode=mode, prescreen_key=key)
        except Exception as exc:  # noqa: BLE001 — runtime field/gateway failure ⇒ try fallback
            tried.append({"mode": mode, "key": key, "error": str(exc)})
            last_exc = exc
            continue
        log = stage0_select(records, prescreen_mode=mode, prescreen_key=key,
                            market_cap_floor=market_cap_floor, superset_size=superset_size,
                            curated_adr=curated_adr)
        log["prescreen_probe"] = {"available_volume_field": vol_field,
                                  "attempts": [{"mode": mo, "key": k} for mo, k in attempts],
                                  "failed_attempts": tried, "used": {"mode": mode, "key": key}}
        return log
    raise (last_exc or RuntimeError("stage-0 screen produced no result"))


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str))


def _load_exclude(args) -> tuple[set[str], list[str]]:
    """Curated non-common (ADR/foreign) exclusion set: ADDENDUM-A-named seed + --exclude + file."""
    exclude = set(ADDENDUM_A_NAMED_ADRS)
    if args.exclude:
        exclude |= {s.strip().upper() for s in args.exclude.split(",") if s.strip()}
    if getattr(args, "exclude_file", None) and Path(args.exclude_file).exists():
        exclude |= {ln.strip().upper() for ln in Path(args.exclude_file).read_text().splitlines()
                    if ln.strip() and not ln.strip().startswith("#")}
    return exclude, sorted(exclude)


def _cmd_stage0(args) -> int:
    curated_adr, curated_sorted = _load_exclude(args)
    provider = OpenDStockFilterProvider(host=args.host, port=args.port, pause=args.pause)
    try:
        log = run_stage0(provider, market_cap_floor=args.market_cap_floor,
                         superset_size=args.superset, curated_adr=curated_adr)
    except Exception as exc:  # noqa: BLE001 — SDK missing OR gateway/API failure ⇒ clear blocker
        print("[resolve_universe stage0] BLOCKER: Stage-0 pre-screen could not run on this host.")
        print(f"  {type(exc).__name__}: {exc}")
        print("  Stage-0 needs a reachable OpenD gateway with US market-data entitlement; run on "
              "都水's host. This step is quote-only and consumes NO historical-K quota.")
        return 2

    used_key = (log.get("prescreen_probe") or {}).get("used", {}).get("key", log["prescreen_key"])
    log["curated_adr_list_size"] = len(curated_sorted)
    # §C4 disclosure (都察院-auditable): operative pre-screen key + selection effect + rule tally.
    log["adr_disclosure"] = {
        "operative_prescreen_key": used_key,
        "selection_effect": (
            f"superset pre-screened by {used_key} (market-cap under the (ii) MARKET_VAL fallback; "
            "the final 250 is 60-day-dollar-volume-ranked in stage-1). The MARKET_VAL fallback is "
            "what surfaces ADR contamination — high market cap, low US liquidity."),
        "adr_excluded_total": log["adr_excluded_count"],
        "adr_excluded_by_rule": log["adr_excluded_by_rule"],
        "refill_depth": log["adr_refill_depth"], "scan_depth": log["adr_scan_depth"],
        "keep_carveouts_hit": log["adr_keep_carveouts"],
        "residual_note": ("any well-known ADR the rule misses ⇒ add to RESIDUAL_ADR_EXCLUDE.txt "
                          "before the results commit; residual unidentified foreign names are "
                          "bounded and cannot turn a fail into a pass (same discipline as "
                          "survivorship, per addendum A/§A2 residual clause)."),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(log["superset"]) + "\n")
    _write_json(out.with_suffix(".json"), log)
    # §C4 step 3: the full ADR classification log — the 都察院-auditable artifact. 都水 commits it
    # (before results); 营缮 only ships the code that produces it.
    class_out = Path(args.classification_out)
    _write_json(class_out, {
        "issue": "EVO-162", "addendum": "C (9f34ae5)",
        "operative_prescreen_key": used_key,
        "clean_superset_count": log["superset_count"], "superset_target": args.superset,
        "adr_excluded_count": log["adr_excluded_count"],
        "adr_excluded_by_rule": log["adr_excluded_by_rule"],
        "keep_carveouts_hit": log["adr_keep_carveouts"],
        "refill_waves": log["adr_refill_waves"],
        "classification": list(log["adr_classification"].values()),
    })
    print(f"[resolve_universe stage0] pre-screen key={used_key}  survivors={log['n_survivors_prefilter']}"
          f"  clean_superset={log['superset_count']}/{args.superset}  → {out}")
    print(f"  ADR excluded={log['adr_excluded_count']} by_rule={log['adr_excluded_by_rule']}  "
          f"refill_waves={log['adr_refill_depth']}  carveouts_kept={log['adr_keep_carveouts']}")
    print(f"  type-filter excluded: {log['excluded_counts']}  classification log → {class_out}")
    if not log["pool_sufficient_for_superset"]:
        print(f"  NOTE: only {log['superset_count']} clean US-common < superset target "
              f"{args.superset} (scanned {log['adr_scan_depth']}/{log['n_survivors_prefilter']}).")
    return 0


def _cmd_stage1(args) -> int:
    data_dirs = args.data_dir or ["data/daily_full", "data/daily"]
    superset = [ln.strip().upper() for ln in Path(args.superset_file).read_text().splitlines()
                if ln.strip() and not ln.strip().startswith("#")]
    stage0_log = None
    s0json = Path(args.superset_file).with_suffix(".json")
    if s0json.exists():
        stage0_log = json.loads(s0json.read_text())
    issuer_by_code = (stage0_log or {}).get("issuer_by_code")

    dv, too_short, unreadable = dollar_volumes_from_parquet(
        data_dirs, superset, advol_days=args.advol_days, min_history_weeks=args.min_weeks)
    borrowable = None
    if args.borrowable_file and Path(args.borrowable_file).exists():
        borrowable = {ln.strip().upper() for ln in Path(args.borrowable_file).read_text().splitlines()
                      if ln.strip()}

    sel = stage1_resolve(dv, issuer_by_code=issuer_by_code, borrowable=borrowable,
                         top_n=args.top, stage0_log=stage0_log)
    sel["too_short_history"] = too_short
    sel["unreadable_or_missing_bars"] = unreadable

    # Guardrail (A4 / 工部 rule 4): do NOT emit the canonical RESIDUAL_UNIVERSE_RESOLVED.txt
    # unless explicitly on the host with a sufficient, real superset. Default writes an audit
    # log + a PREVIEW so this agent never freezes a universe by accident.
    out = Path(args.out)
    if args.emit_resolved and not sel["clean_names_below_target"]:
        out.write_text("\n".join(sel["selected"]) + "\n")
        _write_json(out.with_suffix(".json"), sel)
        print(f"[resolve_universe stage1] wrote {sel['selected_count']} → {out}")
    else:
        preview = Path("qlab/reports/residual") / "universe_stage1_preview.txt"
        preview.parent.mkdir(parents=True, exist_ok=True)
        header = ("# EVO-162 C1 Stage-1 PREVIEW — NOT the frozen RESIDUAL_UNIVERSE_RESOLVED.txt.\n"
                  "# Emitted without --emit-resolved (or clean names < target). 都水 runs the real\n"
                  "# resolution on the OpenD host and commits the frozen list before any results.\n")
        preview.write_text(header + "\n".join(sel["selected"]) + "\n")
        _write_json(preview.with_suffix(".json"), sel)
        print(f"[resolve_universe stage1] PREVIEW ({sel['selected_count']} names) → {preview}"
              + ("  [clean<target]" if sel["clean_names_below_target"] else "  [no --emit-resolved]"))
    print(f"  ranked={sel['n_ranked']}  after_dedup={sel['n_after_dedup']}  "
          f"after_borrow={sel['n_after_borrow']}  target={args.top}  "
          f"below_target={sel['clean_names_below_target']}")
    if sel["dual_class_drops"]:
        print(f"  dual-class drops: {[(d['dropped'], '→', d['kept']) for d in sel['dual_class_drops']]}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="EVO-162 C1 two-stage universe resolver (ADDENDUM A)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s0 = sub.add_parser("stage0", help="zero-quota get_stock_filter pre-screen + ADR classify/refill → clean 296 (needs gateway)")
    s0.add_argument("--market-cap-floor", type=float, default=MARKET_CAP_FLOOR)
    s0.add_argument("--superset", type=int, default=SUPERSET_SIZE)
    s0.add_argument("--exclude", default=None, help="comma-separated codes to force-exclude (added to R0)")
    # prereg artifacts live at the qlab project dir (cwd for `-m qlab.swing`), next to the prereg
    # docs + 户部's RESIDUAL_ADR_EXCLUDE.txt — so these paths are cwd-relative, NOT qlab/-prefixed
    # (which would point into the package dir). Generated reports stay under qlab/reports/.
    s0.add_argument("--exclude-file", default="RESIDUAL_ADR_EXCLUDE.txt",
                    help="curated ADR/foreign R0 list (户部 §A2/C; default = the frozen RESIDUAL_ADR_EXCLUDE.txt)")
    s0.add_argument("--classification-out", default="RESIDUAL_UNIVERSE_ADR_CLASSIFICATION.json",
                    help="addendum-C ADR classification log (都水 commits it, before results)")
    s0.add_argument("--host", default="127.0.0.1")
    s0.add_argument("--port", type=int, default=11111)
    s0.add_argument("--pause", type=float, default=3.0,
                    help="seconds between get_stock_filter pages (rate-limit backoff, 10 calls/30s)")
    s0.add_argument("--out", default="RESIDUAL_UNIVERSE_SUPERSET_296.txt")
    s0.set_defaults(func=_cmd_stage0)

    s1 = sub.add_parser("stage1", help="60d $-vol rank + de-dup + borrow sub over fetched bars → top-250")
    s1.add_argument("--superset-file", default="RESIDUAL_UNIVERSE_SUPERSET_296.txt")
    s1.add_argument("--data-dir", action="append", default=None)
    s1.add_argument("--top", type=int, default=TARGET_N)
    s1.add_argument("--advol-days", type=int, default=ADVOL_DAYS)
    s1.add_argument("--min-weeks", type=int, default=MIN_HISTORY_WEEKS)
    s1.add_argument("--borrowable-file", default=None)
    s1.add_argument("--out", default="RESIDUAL_UNIVERSE_RESOLVED.txt")
    s1.add_argument("--emit-resolved", action="store_true",
                    help="(都水, host-only) actually write the frozen RESIDUAL_UNIVERSE_RESOLVED.txt")
    s1.set_defaults(func=_cmd_stage1)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
