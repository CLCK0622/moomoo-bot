"""EVO-162 C1 ADDENDUM A universe resolver — deterministic two-stage screen unit tests.

Covers every deterministic decision (mock filter/daily bars, NO gateway needed): Stage-0
type/cap/rank/top-296 cut + per-step exclusion counts + pre-screen key priority; A2 dual-class
de-dup (keep higher 60d $-vol; tie ≤5% ⇒ alphabetical); Stage-1 60d mean(close×volume) ranking
from bars; borrow top-down substitution; the merged selection-effect log fields; and the
<250-clean-names honest-labelling-without-padding rule.
"""
import numpy as np
import pandas as pd

from qlab.swing.resolve_universe import (choose_prescreen_key, dedup_dual_class,
                                         dollar_volumes_from_parquet, issuer_key,
                                         stage0_select, stage1_resolve)


# --------------------------------------------------------------------------- #
# issuer_key + dual-class de-dup (A2)
# --------------------------------------------------------------------------- #
def test_issuer_key_groups_dual_classes():
    assert issuer_key("Alphabet Inc. Class A", "GOOGL") == issuer_key("Alphabet Inc. Class C", "GOOG")
    assert issuer_key("Fox Corporation Class B", "FOX") == issuer_key("Fox Corporation Class A", "FOXA")
    assert issuer_key("Under Armour Inc. Class C", "UA") == issuer_key("Under Armour Inc. Class A", "UAA")
    # ticker fallback (no name) still groups BRK.A / BRK.B by base ticker
    assert issuer_key(None, "BRK.A") == issuer_key(None, "BRK.B")
    # distinct issuers do NOT collide
    assert issuer_key("Apple Inc.", "AAPL") != issuer_key("Microsoft Corporation", "MSFT")


def test_dedup_keeps_higher_dollar_volume_class():
    # input is already rank-sorted (as stage1_resolve passes it); GOOG is >5% below GOOGL ⇒ dropped
    ranked = [
        {"code": "AAPL", "dollar_volume": 200.0, "issuer": "apple"},
        {"code": "GOOGL", "dollar_volume": 100.0, "issuer": "alphabet"},
        {"code": "GOOG", "dollar_volume": 60.0, "issuer": "alphabet"},   # 40% lower ⇒ dropped
    ]
    kept, drops = dedup_dual_class(ranked)
    assert [k["code"] for k in kept] == ["AAPL", "GOOGL"]                  # rank order preserved
    assert len(drops) == 1 and drops[0]["dropped"] == "GOOG" and drops[0]["kept"] == "GOOGL"


def test_dedup_tie_within_5pct_takes_alphabetical():
    ranked = [
        {"code": "BRK.B", "dollar_volume": 50.0, "issuer": "berkshire hathaway"},
        {"code": "BRK.A", "dollar_volume": 49.0, "issuer": "berkshire hathaway"},   # within 5% ⇒ alpha
    ]
    kept, drops = dedup_dual_class(ranked)
    assert [k["code"] for k in kept] == ["BRK.A"]                          # alphabetically-first
    assert drops[0]["dropped"] == "BRK.B" and drops[0]["tie_within_pct"] is True


def test_dedup_tie_beyond_5pct_takes_higher_volume():
    ranked = [
        {"code": "BRK.B", "dollar_volume": 50.0, "issuer": "berkshire hathaway"},
        {"code": "BRK.A", "dollar_volume": 40.0, "issuer": "berkshire hathaway"},   # >5% below ⇒ keep B
    ]
    kept, _ = dedup_dual_class(ranked)
    assert [k["code"] for k in kept] == ["BRK.B"]


# --------------------------------------------------------------------------- #
# Stage-0 pre-screen (A1)
# --------------------------------------------------------------------------- #
def test_choose_prescreen_key_priority():
    assert choose_prescreen_key(["VOLUME"]) == ("snapshot_dollar_volume", "VOLUME")
    assert choose_prescreen_key(["AVG_VOLUME_10D"]) == ("snapshot_dollar_volume", "AVG_VOLUME_10D")
    assert choose_prescreen_key([]) == ("market_val", "MARKET_VAL")        # fallback (ii)
    assert choose_prescreen_key(["TURNOVER"]) == ("market_val", "MARKET_VAL")  # non-candidate ⇒ fallback


def _rec(code, mv, price, vol, sec="STOCK", market="US", name=None, is_common=None):
    return {"code": code, "name": name or f"{code} Inc", "sec_type": sec, "market": market,
            "market_val": mv, "cur_price": price, "volume": vol, "is_common": is_common}


def test_stage0_excludes_adr_etf_below_cap_and_ranks():
    recs = [
        _rec("AAA", 5e11, 100, 2e7),                       # $-vol 2.0e9  (kept, rank 1)
        _rec("CCC", 2e11, 20, 5e7),                        # $-vol 1.0e9  (kept, rank 2)
        _rec("BBB", 3e11, 50, 1e7),                        # $-vol 0.5e9  (kept, rank 3 = cut)
        _rec("TSM", 6e11, 180, 9e6, sec="ADR"),            # ADR ⇒ excluded_sec_type
        _rec("XETF", 5e11, 500, 8e7, sec="ETF"),           # ETF ⇒ excluded_sec_type
        _rec("SMALL", 5e9, 10, 1e6),                       # < $10B ⇒ below_cap
        _rec("HUH", 4e11, 30, 3e7, sec="UNKNOWN"),         # unconfirmed type ⇒ dropped (conservative)
    ]
    log = stage0_select(recs, prescreen_mode="snapshot_dollar_volume", prescreen_key="VOLUME",
                        superset_size=3)
    assert log["superset"] == ["AAA", "CCC", "BBB"]        # ranked by snapshot $-vol desc
    assert log["cut_prescreen_value_296th"] == 50 * 1e7    # BBB's price×volume (the 296th/cut)
    assert log["excluded_counts"]["excluded_sec_type"] == 2
    assert log["excluded_counts"]["below_cap"] == 1
    assert log["excluded_counts"]["unconfirmed_common"] == 1
    assert log["pool_sufficient_for_superset"] is True
    assert log["issuer_by_code"]["AAA"]                    # issuer map present for de-dup


def test_stage0_reit_kept_and_factor_etfs_auto_excluded():
    recs = [
        _rec("PLD", 1.2e11, 130, 4e6, name="Prologis Inc"),   # REIT = SecurityType.STOCK ⇒ kept
        _rec("SPY", 5e11, 500, 8e7, sec="ETF"),               # a factor ETF, auto-excluded
    ]
    log = stage0_select(recs, prescreen_mode="market_val", prescreen_key="MARKET_VAL", superset_size=10)
    assert "PLD" in log["superset"]                            # REIT retained (disclosed limitation)
    assert "SPY" not in log["superset"]
    assert log["excluded_counts"]["curated_exclude"] == 1      # SPY caught as a factor ETF


def test_stage0_adr_excluded_only_via_curated_list():
    """moomoo classifies ADRs as STOCK (no ADR flag), so a curated exclude is the only lever."""
    recs = [
        _rec("AAPL", 3e12, 200, 5e7),
        _rec("TSM", 6e11, 180, 9e6),                       # ADR, but sec_type reports STOCK
    ]
    # without the curated list TSM survives (moomoo cannot flag it)...
    kept = stage0_select(recs, prescreen_mode="market_val", prescreen_key="MARKET_VAL",
                         superset_size=10)
    assert "TSM" in kept["superset"]
    # ...with the curated ADR list it is dropped as curated_exclude
    dropped = stage0_select(recs, prescreen_mode="market_val", prescreen_key="MARKET_VAL",
                            superset_size=10, exclude_codes={"TSM"})
    assert "TSM" not in dropped["superset"]
    assert dropped["excluded_counts"]["curated_exclude"] == 1


def test_stage0_market_val_fallback_ranks_by_cap():
    recs = [_rec("AAA", 3e11, None, None), _rec("BBB", 5e11, None, None), _rec("CCC", 1e11, None, None)]
    log = stage0_select(recs, prescreen_mode="market_val", prescreen_key="MARKET_VAL", superset_size=2)
    assert log["superset"] == ["BBB", "AAA"]                   # by MARKET_VAL desc


def test_stage0_superset_insufficient_flagged():
    recs = [_rec("AAA", 5e11, 100, 2e7), _rec("BBB", 3e11, 50, 1e7)]
    log = stage0_select(recs, prescreen_mode="snapshot_dollar_volume", prescreen_key="VOLUME",
                        superset_size=296)
    assert log["pool_sufficient_for_superset"] is False
    assert log["cut_prescreen_value_296th"] is None           # fewer than 296 ⇒ no cut threshold
    assert log["superset_count"] == 2


# --------------------------------------------------------------------------- #
# Stage-1 — 60d ranking from bars, borrow substitution, selection-effect, no padding
# --------------------------------------------------------------------------- #
def _write_parquet(dir_, code, n, price, vol):
    dates = pd.bdate_range("2006-01-02", periods=n)
    df = pd.DataFrame({"date": dates, "open": np.full(n, price), "high": np.full(n, price),
                       "low": np.full(n, price), "close": np.full(n, price), "volume": np.full(n, vol)})
    df.to_parquet(dir_ / f"{code}_1d.parquet", index=False)


def test_stage1_60d_dollar_volume_from_parquet_and_history_filter(tmp_path):
    _write_parquet(tmp_path, "AAA", 900, 100.0, 2e6)          # 60d $-vol = 2.0e8, long history
    _write_parquet(tmp_path, "BBB", 900, 50.0, 1e6)           # 60d $-vol = 5.0e7
    _write_parquet(tmp_path, "SHORT", 100, 100.0, 9e9)        # only 100 bars ⇒ dropped (short history)
    dv, too_short, unreadable = dollar_volumes_from_parquet([str(tmp_path)], ["AAA", "BBB", "SHORT", "GONE"])
    assert dv == {"AAA": 2.0e8, "BBB": 5.0e7}                 # mean(close×volume) over last 60 bars
    assert [t["symbol"] for t in too_short] == ["SHORT"]
    assert unreadable == ["GONE"]                             # no parquet at all


def test_stage1_borrow_substitution_walks_top_down():
    dv = {"AAPL": 200.0, "MSFT": 150.0, "NVDA": 120.0, "TSLA": 90.0}
    # TSLA not borrowable ⇒ skipped, next-ranked fills the slot
    sel = stage1_resolve(dv, borrowable={"AAPL", "MSFT", "NVDA"}, top_n=3)
    assert sel["selected"] == ["AAPL", "MSFT", "NVDA"]
    assert sel["borrow_substitutions"][0]["dropped_non_borrowable"] == ["TSLA"]


def test_stage1_below_target_is_labelled_not_padded():
    dv = {"AAPL": 200.0, "MSFT": 150.0}
    sel = stage1_resolve(dv, borrowable={"AAPL", "MSFT"}, top_n=250)
    assert sel["selected"] == ["AAPL", "MSFT"]
    assert sel["selected_count"] == 2
    assert sel["clean_names_below_target"] is True
    assert sel["padded"] is False                            # NEVER padded (A3)
    assert "shortfall_note" in sel


def test_stage1_selection_effect_log_merges_stage0():
    dv = {"AAA": 100.0, "BBB": 80.0, "CCC": 60.0}
    stage0_log = {"prescreen_key": "VOLUME", "prescreen_mode": "snapshot_dollar_volume",
                  "superset_count": 3, "superset": ["AAA", "BBB", "CCC"],
                  "cut_prescreen_value_296th": 6.0e8,
                  "excluded_counts": {"excluded_sec_type": 5, "below_cap": 9}}
    sel = stage1_resolve(dv, top_n=2, stage0_log=stage0_log)
    se = sel["selection_effect"]
    assert se["stage0_prescreen_key"] == "VOLUME"
    assert se["superset_size"] == 3
    assert se["cut_296th_code"] == "CCC"                     # 296th (last) superset name
    assert se["cut_296th_prescreen_value"] == 6.0e8
    assert se["cut_296th_60d_dollar_volume"] == 60.0        # its real 60d $-vol from stage-1
    assert se["stage0_excluded_counts"]["below_cap"] == 9
    assert "cannot turn a fail into a pass" in se["disclosure"]


def test_stage1_dedup_then_rank_end_to_end():
    # GOOG is >5% below GOOGL ⇒ dropped as the lower dual class; final top-2 by 60d $-vol
    dv = {"AAPL": 300.0, "GOOGL": 250.0, "GOOG": 200.0, "MSFT": 180.0}
    issuer = {"AAPL": "apple", "GOOGL": "alphabet", "GOOG": "alphabet", "MSFT": "microsoft"}
    sel = stage1_resolve(dv, issuer_by_code=issuer, top_n=2)
    assert sel["selected"] == ["AAPL", "GOOGL"]              # GOOG removed as the lower dual class
    assert sel["n_after_dedup"] == 3
    assert any(d["dropped"] == "GOOG" for d in sel["dual_class_drops"])


def test_stage1_dedup_close_dual_class_takes_alphabetical():
    # GOOGL vs GOOG within 5% ⇒ frozen tie rule keeps the alphabetically-first ticker (GOOG)
    dv = {"AAPL": 300.0, "GOOGL": 250.0, "GOOG": 245.0}
    issuer = {"AAPL": "apple", "GOOGL": "alphabet", "GOOG": "alphabet"}
    sel = stage1_resolve(dv, issuer_by_code=issuer, top_n=2)
    assert sel["selected"] == ["AAPL", "GOOG"]              # GOOG < GOOGL alphabetically, tie ≤5%
