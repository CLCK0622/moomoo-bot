"""EVO-23 momentum adapter: contract + no-look-ahead + long-only + sizing/regime."""
import numpy as np
import pandas as pd

from qlab.swing.momentum_signals import MomentumParams, momentum_curve


def _series(n, drift, seed=0, start="2015-01-02"):
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range(start, periods=n)
    close = 50.0 * np.cumprod(1.0 + rng.normal(drift, 0.01, n))
    open_ = close * (1.0 + rng.normal(0.0, 0.002, n))
    return pd.DataFrame({"date": dates, "open": open_, "close": close})


N = 600  # > 12-month lookback (252) + margin


def test_equity_contract_and_opentoopen():
    frames = {"SPY": _series(N, 0.0006, 1)}
    res = momentum_curve(frames, ["SPY"], MomentumParams(lookback_months=12))
    eq = res["equity_df"]
    assert list(eq.columns) == ["date", "ret", "equity", "traded_notional"]
    assert len(eq) == N - 2                      # open-to-open loses 2 endpoints
    assert res["diagnostics"]["return_convention"].startswith("open-to-open")


def test_long_only_no_shorting_and_gross_le_1():
    frames = {s: _series(N, d, i) for i, (s, d) in
              enumerate([("SPY", 0.0006), ("QQQ", -0.0006), ("IWM", 0.0004)])}
    res = momentum_curve(frames, ["SPY", "QQQ", "IWM"], MomentumParams(lookback_months=12))
    W = res["weights_df"][["SPY", "QQQ", "IWM"]].to_numpy()
    assert (W >= -1e-12).all()                   # never short
    assert (W.sum(axis=1) <= 1.0 + 1e-9).all()   # never levered


def test_downtrend_goes_to_cash():
    frames = {"SPY": _series(N, -0.004, 3)}       # strong decline ⇒ 12-mo mom always <0
    res = momentum_curve(frames, ["SPY"], MomentumParams(lookback_months=12))
    assert res["diagnostics"]["frac_days_deployed"] == 0.0
    assert float(np.abs(res["equity_df"]["ret"]).sum()) == 0.0


def test_uptrend_fully_deployed_at_slot():
    frames = {"SPY": _series(N, 0.0015, 5)}       # strong uptrend ⇒ mom>0
    res = momentum_curve(frames, ["SPY"], MomentumParams(lookback_months=12))
    d = res["diagnostics"]
    assert d["frac_days_deployed"] > 0.3          # deployed after the 12-mo warmup
    assert abs(d["max_gross"] - 1.0) < 1e-9       # single-symbol universe ⇒ slot = 1/1


def test_frozen_N_universe_sizing_not_resized():
    """One present symbol in an 8-name frozen universe ⇒ slot stays 1/8, NOT 1/1."""
    frames = {"SPY": _series(N, 0.0015, 7)}
    universe = ["SPY", "QQQ", "IWM", "TLT", "IEF", "GLD", "DBC", "UUP"]
    res = momentum_curve(frames, universe, MomentumParams(lookback_months=12))
    assert abs(res["diagnostics"]["max_gross"] - 1.0 / 8) < 1e-9
    assert res["diagnostics"]["universe_missing"] == ["QQQ", "IWM", "TLT", "IEF", "GLD", "DBC", "UUP"]
    assert res["diagnostics"]["data_complete"] is False


def test_no_look_ahead():
    """Perturbing FUTURE bars must not change any earlier realized return."""
    frames = {"SPY": _series(N, 0.0008, 9)}
    p = MomentumParams(lookback_months=12)
    base = momentum_curve(frames, ["SPY"], p)["equity_df"]["ret"].to_numpy()
    k = 500
    f2 = {"SPY": frames["SPY"].copy()}
    f2["SPY"].loc[k:, ["open", "close"]] *= 1.5   # shock everything from k on
    pert = momentum_curve(f2, ["SPY"], p)["equity_df"]["ret"].to_numpy()
    assert np.allclose(base[: k - 2], pert[: k - 2])


def test_rs_holds_top_n_equal_weight():
    """RS top-2 of 4 sectors holds the two strongest, 1/2 each; weak/down ⇒ excluded."""
    frames = {
        "A": _series(N, 0.0016, 11),   # strongest up
        "B": _series(N, 0.0010, 12),   # up
        "C": _series(N, 0.0002, 13),   # ~flat
        "D": _series(N, -0.0012, 14),  # down
    }
    res = momentum_curve(frames, ["A", "B", "C", "D"],
                         MomentumParams(lookback_months=12, top_n=2))
    W = res["weights_df"][["A", "B", "C", "D"]].to_numpy()
    deployed = W[W.sum(axis=1) > 0]
    assert len(deployed) > 0
    # D (downtrend) is never held; each held slot is 1/2
    assert (W[:, 3] == 0.0).all()
    nz = W[W > 0]
    assert np.allclose(nz, 0.5)
