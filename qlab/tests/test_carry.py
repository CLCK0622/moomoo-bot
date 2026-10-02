"""EVO-25 carry adapter: contract + no-look-ahead + risk-overlay behaviour."""
import numpy as np
import pandas as pd

from qlab.swing.carry_signals import CarryParams, carry_curve


def _synth_etp(n=400, seed=0):
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range("2015-01-02", periods=n)
    close = 50.0 * np.cumprod(1.0 + rng.normal(0.0002, 0.02, n))
    open_ = close * (1.0 + rng.normal(0.0, 0.003, n))
    return pd.DataFrame({"date": dates, "open": open_, "high": close * 1.01,
                         "low": close * 0.99, "close": close, "volume": 1e6})


def _synth_signal(dates, ratio):
    return pd.DataFrame({"date": dates, "vix": 15.0 * ratio, "vix3m": 15.0,
                         "term_ratio": ratio})


def test_equity_contract_and_opentoopen():
    etp = _synth_etp()
    sig = _synth_signal(etp["date"], np.full(len(etp), 0.90))   # always contango
    res = carry_curve(etp, sig, CarryParams())
    eq = res["equity_df"]
    assert list(eq.columns) == ["date", "ret", "equity", "traded_notional"]
    assert len(eq) == len(etp) - 2                              # open-to-open loses 2 endpoints
    assert res["diagnostics"]["frac_days_deployed"] > 0.5       # contango ⇒ mostly deployed


def test_backwardation_goes_to_cash():
    etp = _synth_etp()
    sig = _synth_signal(etp["date"], np.full(len(etp), 1.20))   # always backwardation
    res = carry_curve(etp, sig, CarryParams())
    assert res["diagnostics"]["frac_days_deployed"] == 0.0      # never long a vol product
    assert abs(res["equity_df"]["ret"]).sum() == 0.0            # flat cash → zero P&L


def test_no_look_ahead():
    """Perturbing a FUTURE bar must not change any earlier realized return."""
    etp = _synth_etp()
    sig = _synth_signal(etp["date"], np.full(len(etp), 0.90))
    base = carry_curve(etp, sig, CarryParams())["equity_df"]["ret"].to_numpy()
    k = 300
    etp2 = etp.copy()
    etp2.loc[k:, ["open", "close"]] *= 1.5                      # shock everything from k on
    pert = carry_curve(etp2, sig, CarryParams())["equity_df"]["ret"].to_numpy()
    # returns strictly before the shocked open (period end index < k-1) are untouched
    assert np.allclose(base[: k - 2], pert[: k - 2])


def test_abnormal_vix_stop_flattens():
    etp = _synth_etp()
    ratio = np.full(len(etp), 0.90)                            # contango throughout
    sig = _synth_signal(etp["date"], ratio)
    sig["vix"] = 40.0                                          # > vix_cap 35 everywhere
    res = carry_curve(etp, sig, CarryParams())
    assert res["diagnostics"]["frac_days_deployed"] == 0.0     # hard stop keeps it flat
