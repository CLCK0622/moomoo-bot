"""EVO-238 portfolio layer: contract · causal inverse-vol · BTAL cap · gate-B bootstrap.

Boundary + error-handling coverage requested by the 吏部-frozen stage-2 spec. All
synthetic, seeded, value-stable; zero engine dependency (feeds return series直接).
"""
import numpy as np
import pandas as pd
import pytest

from qlab.swing import portfolio as P


def _ret_series(name, n, mu, sigma, seed, start="2018-01-02"):
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range(start, periods=n)
    return pd.DataFrame({"date": dates, name: rng.normal(mu, sigma, n)})


N = 400  # > vol_lookback(63) + several monthly rebalances


def _components(names_sigmas, n=N, seed0=0):
    return {nm: _ret_series(nm, n, mu, sg, seed0 + i)
            for i, (nm, mu, sg) in enumerate(names_sigmas)}


def _spy(n=N, seed=99):
    return _ret_series("spy", n, 0.0003, 0.011, seed)


# --------------------------------------------------------------------------- #
# contract
# --------------------------------------------------------------------------- #
def test_equity_contract_columns_and_axis():
    comps = _components([("BASE", 0.0004, 0.008), ("DBMF", 0.0003, 0.006)])
    port = P.build_portfolio(comps, _spy(), cost_mult=2.0)
    eq = port["equity_df"]
    assert list(eq.columns) == ["date", "ret", "equity"]
    # active axis starts only after the first vol estimate is available (causal warmup)
    assert port["diagnostics"]["n_days"] < N
    assert (eq["equity"] > 0).all()
    # SPY is aligned to the exact active axis
    assert len(port["spy"]) == len(eq)
    assert (port["spy"]["date"].to_numpy() == eq["date"].to_numpy()).all()


def test_inner_join_axis_is_intersection():
    a = _ret_series("BASE", N, 0.0004, 0.008, 1, start="2018-01-02")
    b = _ret_series("DBMF", N, 0.0003, 0.006, 2, start="2019-01-02")  # later start
    port = P.build_portfolio({"BASE": a, "DBMF": b}, _spy(seed=3), cost_mult=1.0)
    assert pd.Timestamp(port["diagnostics"]["sample_start"]) >= pd.Timestamp("2019-01-02")


# --------------------------------------------------------------------------- #
# causal inverse-vol weighting
# --------------------------------------------------------------------------- #
def test_inv_vol_lower_vol_gets_more_weight():
    w = P._inv_vol_target(np.array([0.005, 0.020]), ["BASE", "DBMF"], btal_cap=None)
    assert w[0] > w[1] and abs(w.sum() - 1.0) < 1e-12   # lower-σ BASE overweighted


def test_inv_vol_handles_zero_and_nan_sigma():
    w = P._inv_vol_target(np.array([0.0, np.nan, 0.01]), ["A", "B", "C"], btal_cap=None)
    assert abs(w.sum() - 1.0) < 1e-9 and np.isfinite(w).all()
    assert w[2] == pytest.approx(1.0)                    # only finite-positive σ funded


def test_btal_cap_snaps_and_renormalizes():
    # BTAL has the lowest σ ⇒ raw inverse-vol would over-allocate; cap must bind
    sigma = np.array([0.010, 0.020, 0.004])
    names = ["BASE", "DBMF", "BTAL"]
    w = P._inv_vol_target(sigma, names, btal_cap=P.BTAL_CAP)
    assert w[2] == pytest.approx(P.BTAL_CAP)             # snapped to 15%
    assert w[:2].sum() == pytest.approx(1.0 - P.BTAL_CAP)  # rest renormalized to 85%
    assert w[0] > w[1]                                   # rest keep inverse-vol order


def test_btal_cap_inactive_when_below_cap():
    sigma = np.array([0.004, 0.004, 0.030])              # BTAL highest σ ⇒ tiny weight
    w = P._inv_vol_target(sigma, ["BASE", "DBMF", "BTAL"], btal_cap=P.BTAL_CAP)
    assert w[2] < P.BTAL_CAP and abs(w.sum() - 1.0) < 1e-12


# --------------------------------------------------------------------------- #
# no look-ahead — perturbing FUTURE returns cannot change earlier portfolio ret
# --------------------------------------------------------------------------- #
def test_no_look_ahead():
    comps = _components([("BASE", 0.0004, 0.008), ("DBMF", 0.0003, 0.006)])
    base = P.build_portfolio(comps, _spy(), cost_mult=2.0)["equity_df"]
    k = 300
    c2 = {nm: df.copy() for nm, df in comps.items()}
    for nm in c2:
        c2[nm].loc[k:, nm] += 0.05                       # shock every future bar
    pert = P.build_portfolio(c2, _spy(), cost_mult=2.0)["equity_df"]
    m = min(len(base), len(pert))
    early = base["date"] < base["date"].iloc[0] + pd.Timedelta(days=300)
    n_cmp = int(early.sum())
    assert np.allclose(base["ret"].to_numpy()[:n_cmp], pert["ret"].to_numpy()[:n_cmp])


# --------------------------------------------------------------------------- #
# stationary block bootstrap (Politis-Romano) + gate B
# --------------------------------------------------------------------------- #
def test_stationary_block_indices_valid_and_seeded():
    rng1 = np.random.RandomState(7)
    rng2 = np.random.RandomState(7)
    i1 = P._stationary_block_indices(200, 21.0, rng1)
    i2 = P._stationary_block_indices(200, 21.0, rng2)
    assert len(i1) == 200 and i1.min() >= 0 and i1.max() < 200
    assert (i1 == i2).all()                              # deterministic under a fixed seed


def test_gate_b_bounds_and_reproducible():
    rng = np.random.RandomState(5)
    ret = rng.normal(0.0006, 0.010, 800)
    g1 = P.gate_b_bootstrap(ret, n_boot=500, seed=1)
    g2 = P.gate_b_bootstrap(ret, n_boot=500, seed=1)
    assert not g1["degenerate"]
    assert g1["cagr_5pct_lb"] <= g1["cagr_point"]        # lower bound below point
    assert g1["mdd_95pct_ub"] >= g1["mdd_point"]         # upper bound above point
    assert g1 == g2                                      # seeded ⇒ value-stable


def test_gate_b_degenerate_on_short_series():
    g = P.gate_b_bootstrap(np.array([0.01, -0.02, 0.03]), n_boot=100)
    assert g["degenerate"] and g["passed"] is False


def test_gate_b_pass_logic_requires_both_legs():
    # a strong, smooth series should clear BOTH legs; assert the AND-gate holds
    rng = np.random.RandomState(2)
    strong = rng.normal(0.004, 0.004, 900)              # ~ high CAGR, low MDD
    g = P.gate_b_bootstrap(strong, n_boot=800, cagr_floor=0.50, mdd_cap=0.20, seed=3)
    assert g["passed"] == (g["cagr_lb_passes"] and g["mdd_ub_passes"])


# --------------------------------------------------------------------------- #
# error handling
# --------------------------------------------------------------------------- #
def test_short_axis_raises():
    comps = _components([("BASE", 0.0004, 0.008)], n=40)  # < vol_lookback + margin
    with pytest.raises(ValueError):
        P.build_portfolio(comps, _spy(n=40), cost_mult=1.0)


def test_disjoint_axis_raises():
    a = _ret_series("BASE", 200, 0.0004, 0.008, 1, start="2010-01-04")
    b = _ret_series("DBMF", 200, 0.0003, 0.006, 2, start="2020-01-02")  # no overlap
    with pytest.raises(ValueError):
        P.build_portfolio({"BASE": a, "DBMF": b}, _spy(seed=4), cost_mult=1.0)
