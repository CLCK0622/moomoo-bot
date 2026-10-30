"""Tests for the FRED point-in-time (vintage) fetcher — candidate C data path.

Offline (canned FRED API JSON via a fake session). Pins the two things that
matter: (1) fail-closed on a missing key — never a silent latest fall-back; and
(2) the requirement-#2 self-check decision table — HTTP 200 is not proof, and
"identical to latest" is resolved into revised / single-vintage / trap / broken
-control WITHOUT a live key.
"""
from __future__ import annotations

import pytest

from qlab.events.datafetch import fred_vintage as fv


class _Resp:
    def __init__(self, payload):
        self._p = payload
        self.status_code = 200
        self.text = ""

    def json(self):
        return self._p


class _FakeSession:
    """Serves canned observations / vintagedates keyed by series + realtime flag.

    spec[series_id] = {"vintage": [(date,val)...], "latest": [...], "vintages": [dates...]}
    """

    def __init__(self, spec):
        self.spec = spec
        self.headers = {}

    def get(self, url, params=None, timeout=30):
        params = params or {}
        sid = params["series_id"]
        s = self.spec[sid]
        if url.endswith("series/vintagedates"):
            return _Resp({"vintage_dates": s.get("vintages", [])})
        # observations: realtime_start present => vintage, else latest
        key = "vintage" if "realtime_start" in params else "latest"
        obs = [{"date": d, "value": v} for d, v in s[key]]
        return _Resp({"observations": obs})


def test_missing_key_is_fail_closed(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    with pytest.raises(fv.MissingApiKey):
        fv.get_api_key()
    with pytest.raises(fv.MissingApiKey):
        fv.fetch_observations("BAMLH0A0HYM2", obs_start="2018-01-01",
                              obs_end="2018-12-31", as_of="2019-01-02")


def test_observations_parse_drops_missing(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "TESTKEY")
    spec = {"BAMLH0A0HYM2": {"vintage": [("2018-01-02", "3.5"), ("2018-01-03", "."),
                                          ("2018-01-04", "3.7")], "latest": [], "vintages": []}}
    df = fv.fetch_observations("BAMLH0A0HYM2", obs_start="2018-01-01",
                               obs_end="2018-12-31", as_of="2019-01-02",
                               session=_FakeSession(spec))
    assert list(df.columns) == ["date", "value"]
    assert len(df) == 2                       # the "." row dropped, not filled
    assert df["value"].tolist() == [3.5, 3.7]


_CTRL_REVISED = {"vintage": [("2018-01-01", "100.0")], "latest": [("2018-01-01", "105.0")],
                 "vintages": ["2018-04-01", "2018-07-01"]}


def _verdict(target_spec, monkeypatch, run_control=True):
    monkeypatch.setenv("FRED_API_KEY", "TESTKEY")
    spec = {"BAMLH0A0HYM2": target_spec, fv.REVISED_CONTROL: _CTRL_REVISED}
    return fv.assert_vintage_trustworthy(
        "BAMLH0A0HYM2", as_of="2019-01-02", obs_start="2018-01-01",
        obs_end="2018-12-31", session=_FakeSession(spec), run_control=run_control)


def test_revised_series_is_trustworthy(monkeypatch):
    v = _verdict({"vintage": [("2018-06-01", "5.0")], "latest": [("2018-06-01", "5.4")],
                  "vintages": ["2018-06-02", "2019-01-01"]}, monkeypatch)
    assert v.trustworthy and "distinguishable" in v.reason
    assert v.max_abs_diff_vs_latest == pytest.approx(0.4)


def test_identical_with_passing_control_is_no_revision_evidence(monkeypatch):
    # The real BAA10YM case: identical to latest AND many vintages, BUT the
    # revised control (GDPC1) differs -> realtime works -> genuine no-revision.
    v = _verdict({"vintage": [("2018-06-01", "5.0")], "latest": [("2018-06-01", "5.0")],
                  "vintages": ["2018-06-02", "2018-09-01", "2019-01-01"]}, monkeypatch)
    assert v.trustworthy and v.reason.startswith("no_revision_confirmed")
    assert v.control_ok is True and v.identical_to_latest


def test_identical_single_vintage_is_evidence_not_bug(monkeypatch):
    # no control run; identical + only one vintage date -> never-revised evidence
    v = _verdict({"vintage": [("2018-06-01", "5.0")], "latest": [("2018-06-01", "5.0")],
                  "vintages": ["2018-06-02"]}, monkeypatch, run_control=False)
    assert v.trustworthy and v.reason.startswith("single_vintage_never_revised")
    assert v.identical_to_latest


def test_identical_many_vintages_no_control_must_investigate(monkeypatch):
    # identical + many vintages + NO control to prove the call -> not trustworthy
    v = _verdict({"vintage": [("2018-06-01", "5.0")], "latest": [("2018-06-01", "5.0")],
                  "vintages": ["2018-06-02", "2018-09-01", "2019-01-01"]},
                 monkeypatch, run_control=False)
    assert not v.trustworthy
    assert "endpoint_not_honoring_realtime" in v.reason


def test_broken_control_overrides(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "TESTKEY")
    # control comes back identical too => the point-in-time call itself is broken
    broken_ctrl = {"vintage": [("2018-01-01", "100.0")], "latest": [("2018-01-01", "100.0")],
                   "vintages": ["2018-04-01", "2018-07-01"]}
    spec = {"BAMLH0A0HYM2": {"vintage": [("2018-06-01", "5.0")], "latest": [("2018-06-01", "5.0")],
                             "vintages": ["a", "b", "c"]}, fv.REVISED_CONTROL: broken_ctrl}
    v = fv.assert_vintage_trustworthy("BAMLH0A0HYM2", as_of="2019-01-02",
                                      obs_start="2018-01-01", obs_end="2018-12-31",
                                      session=_FakeSession(spec))
    assert v.control_ok is False and not v.trustworthy
    assert "broken" in v.reason
