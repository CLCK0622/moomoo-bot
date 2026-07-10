"""EVO-162 C1 residual-reversal adapter: contract + neutrality + no-look-ahead + data gaps.

The T-close → T+1 execution anti-look-ahead test (``test_no_look_ahead``) is the hard
self-check item required by the frozen pre-registration §7 and the 工部 handoff.
"""
import numpy as np
import pandas as pd

from qlab.swing.residual_signals import (FACTOR_ETFS, ResidualDataGap, ResidualParams,
                                          _rebalance_weights, residual_curve)

# enough business days for E=156wk + F=1wk + margin (≈ 165 weeks → ≈ 825 days); use 1100
N = 1100
START = "2006-01-02"


def _series(n, drift, seed, start=START, vol=0.012):
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range(start, periods=n)
    close = 50.0 * np.cumprod(1.0 + rng.normal(drift, vol, n))
    open_ = close * (1.0 + rng.normal(0.0, 0.002, n))
    return pd.DataFrame({"date": dates, "open": open_, "close": close})


def _stocks(n_stocks, seed0=0):
    return {f"S{i:02d}": _series(N, 0.0002, seed0 + i) for i in range(n_stocks)}


def _factors(seed0=500):
    return {s: _series(N, 0.0003, seed0 + k) for k, s in enumerate(FACTOR_ETFS)}


def test_equity_contract_and_opentoopen():
    stocks, factors = _stocks(40), _factors()
    res = residual_curve(stocks, factors, list(stocks), ResidualParams())
    eq = res["equity_df"]
    assert list(eq.columns) == ["date", "ret", "equity", "traded_notional"]
    assert len(eq) == N - 2                       # open-to-open loses 2 endpoints
    assert res["diagnostics"]["return_convention"].startswith("open-to-open")
    assert np.isfinite(eq["ret"].to_numpy()).all()


def test_gross_cap_is_hard_and_ref_is_unlevered():
    stocks, factors = _stocks(60), _factors()
    res = residual_curve(stocks, factors, list(stocks), ResidualParams())
    gross = res["gross_series"]["gross"].to_numpy()
    assert gross.max() <= 2.0 + 1e-9              # 2.0× hard cap, never exceeded (§5)
    active = gross[gross > 0]
    assert active.min() >= 0.5 - 1e-9             # floor 0.5×
    # risk-frontier reference: fixed 1.0× gross, vol-target/breaker disabled (§14)
    ref = residual_curve(stocks, factors, list(stocks), ResidualParams(lever=False))
    rg = ref["gross_series"]["gross"].to_numpy()
    rg_active = rg[rg > 0]
    assert np.allclose(rg_active, 1.0)


def test_long_short_balanced_equal_names_per_leg():
    stocks, factors = _stocks(60), _factors()
    res = residual_curve(stocks, factors, list(stocks), ResidualParams())
    W = res["weights_df"][[c for c in res["weights_df"].columns if c != "date"]].to_numpy()
    active = W[np.abs(W).sum(axis=1) > 0]
    assert len(active) > 0
    n_long = (active > 1e-12).sum(axis=1)
    n_short = (active < -1e-12).sum(axis=1)
    assert (n_long == n_short).all()             # equal-size long / short legs (decile each)
    # dollar-neutral base (net dollar small vs gross); tolerance covers beta-neutral rescale
    net = active.sum(axis=1)
    gross = np.abs(active).sum(axis=1)
    assert (np.abs(net) <= 0.5 * gross).all()


def test_decile_selects_residual_loser_long_winner_short():
    """With zero factors, residual ≈ raw return: last-week big winner ⇒ short, big loser ⇒ long."""
    n_weeks, n_stocks = 200, 30
    rng = np.random.RandomState(3)
    wret = rng.normal(0.0, 0.01, (n_weeks, n_stocks))
    wret[0, :] = np.nan                          # week 0 has no prior return
    F = rng.normal(0.0, 0.01, (n_weeks, 3))       # non-degenerate factors (full-rank design)
    F[0, :] = np.nan
    # spike ONLY the last (formation) week, which is outside every stock's beta-estimation window,
    # so betas are unchanged and residual ≈ the raw last-week move.
    wret[-1, 0] = +0.30                           # stock 0: big residual winner ⇒ signal low ⇒ SHORT
    wret[-1, 1] = -0.30                           # stock 1: big residual loser  ⇒ signal high ⇒ LONG
    reb_w, _ = _rebalance_weights(wret, F, ResidualParams(), None)
    assert reb_w, "expected at least one rebalance"
    w_last = reb_w[max(reb_w)]
    assert w_last[0] < 0.0                         # winner is shorted
    assert w_last[1] > 0.0                         # loser is longed


def test_no_look_ahead():
    """Perturbing FUTURE bars (stocks AND factors) must not change any earlier realized return.

    Hard self-check (pre-registration §7): weekly weights decided at close(T) execute from
    open(T+1); the causal leverage overlay (vol-target/breaker) uses trailing data only.
    """
    stocks, factors = _stocks(40, seed0=100), _factors(seed0=700)
    p = ResidualParams()
    base = residual_curve(stocks, factors, list(stocks), p)["equity_df"]["ret"].to_numpy()
    k = 1000
    s2 = {s: df.copy() for s, df in stocks.items()}
    f2 = {s: df.copy() for s, df in factors.items()}
    for s in s2:
        s2[s].loc[k:, ["open", "close"]] *= 1.7   # shock every stock bar from k on
    for s in f2:
        f2[s].loc[k:, ["open", "close"]] *= 1.7   # and every factor bar from k on
    pert = residual_curve(s2, f2, list(stocks), p)["equity_df"]["ret"].to_numpy()
    # row i ↔ open(i+1)→open(i+2); the earliest row that reads O[k] is i = k-2, so rows 0..k-3
    # are strictly pre-shock and must be byte-identical.
    cut = k - 2
    assert np.allclose(base[:cut], pert[:cut])
    assert not np.allclose(base[cut:], pert[cut:])  # the shock DID move later returns (sanity)


def test_frozen_N_universe_not_resized():
    """Missing universe symbols are permanently-absent slots, recorded — never silently re-sized."""
    stocks, factors = _stocks(40), _factors()
    universe = list(stocks) + ["GHOST1", "GHOST2"]   # two frozen names with no bars
    res = residual_curve(stocks, factors, universe, ResidualParams())
    d = res["diagnostics"]
    assert d["universe_missing"] == ["GHOST1", "GHOST2"]
    assert d["data_complete"] is False
    assert set(d["universe_present"]) == set(stocks)


def test_missing_factor_etf_raises_data_gap():
    """The 3-factor primary口径 cannot be built without all four factor ETFs — a data gap."""
    stocks = _stocks(40)
    factors = _factors()
    del factors["IVE"]                             # drop value ETF ⇒ HML unbuildable
    try:
        residual_curve(stocks, factors, list(stocks), ResidualParams())
    except ResidualDataGap as exc:
        assert "IVE" in str(exc)
    else:
        raise AssertionError("expected ResidualDataGap when a factor ETF is missing")


def test_higher_cost_lowers_return():
    """×2 commission is a strictly heavier drag than ×1 (cost stress is a main judgment, §8)."""
    stocks, factors = _stocks(60), _factors()
    x1 = residual_curve(stocks, factors, list(stocks), ResidualParams(), cost_mult=1.0)
    x2 = residual_curve(stocks, factors, list(stocks), ResidualParams(), cost_mult=2.0)
    e1 = float(x1["equity_df"]["equity"].iloc[-1])
    e2 = float(x2["equity_df"]["equity"].iloc[-1])
    assert e2 <= e1 + 1e-9                          # more cost ⇒ never higher terminal equity


def test_thin_book_flagged_when_below_min_names():
    """A decile with < min_names_per_leg names is flagged data-insufficient (never a verdict)."""
    stocks, factors = _stocks(30), _factors()      # decile of 30 ⇒ 3 names/leg < 20
    res = residual_curve(stocks, factors, list(stocks), ResidualParams())
    d = res["diagnostics"]
    assert d["any_thin_book"] is True
    assert d["min_names_per_leg"] < d["min_names_per_leg_required"]
