"""FRED point-in-time (vintage) fetcher — for anti-look-ahead signal series.

Candidate C (macro-credit regime) needs credit-spread values **as they were
known on the trade date**, not the latest revised series — using revised data to
backtest a regime signal is look-ahead. This module fetches true vintages via the
FRED API's ``realtime_start``/``realtime_end`` params (ALFRED point-in-time).

WHY NOT the graph CSV endpoint (the trap 工部尚书 caught, md5-proven):

    fred.stlouisfed.org/graph/fredgraph.csv?id=...&vintage_date=YYYY-MM-DD
      -> silently IGNORES vintage_date (and cosd/coed), returns LATEST.
      -> HTTP 200 + valid CSV that LOOKS like a successful vintage pull but is
         latest. A C backtest built on it becomes "latest vs latest" — the very
         look-ahead the killer test exists to catch, disguised as a pass.

So we use the **API** (``api.stlouisfed.org/fred/series/observations``), the only
endpoint that actually honors point-in-time. It needs a free API key
(``FRED_API_KEY``). This module is **fail-closed**: no key -> raise, never a
silent fall-back to latest. And HTTP 200 is NOT treated as proof of a real
vintage — see ``assert_vintage_trustworthy`` (requirement #2).

Runtime note (2026-07): from this workspace, ``api.stlouisfed.org`` is reachable
but ``fred.stlouisfed.org`` / ``alfred.stlouisfed.org`` / ``fredaccount...`` time
out (connection reset). So the API is the only viable FRED path here, and even
obtaining the key via the signup host is blocked — see rate_carry-style provenance.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
import requests

FRED_API = "https://api.stlouisfed.org/fred"
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# Series C may use (both market-price-derived -> expected near-unrevised).
CREDIT_SERIES = {
    "BAMLH0A0HYM2": "ICE BofA US High Yield OAS (%)",
    "BAA10YM": "Moody's Baa - 10y Treasury spread (%)",
}
# A heavily-revised control series — used as a POSITIVE control so an "identical"
# result can be attributed to the series, not a broken point-in-time call.
REVISED_CONTROL = "GDPC1"   # real GDP, revised every release


class MissingApiKey(RuntimeError):
    """No FRED_API_KEY — we refuse to fall back to latest (that would be the trap)."""


class VintageEndpointError(RuntimeError):
    """The API returned something we can't treat as a trustworthy vintage."""


def get_api_key(explicit: Optional[str] = None) -> str:
    key = explicit or os.environ.get("FRED_API_KEY")
    if not key:
        raise MissingApiKey(
            "FRED_API_KEY not set. Vintage data needs the FRED API "
            "(api.stlouisfed.org/fred). We do NOT fall back to the graph CSV "
            "vintage_date endpoint — it silently returns latest (look-ahead).")
    return key


def _get_json(path: str, params: dict, session: Optional[requests.Session] = None) -> dict:
    session = session or requests.Session()
    session.headers.setdefault("User-Agent", BROWSER_UA)
    r = session.get(f"{FRED_API}/{path}", params={**params, "file_type": "json"},
                    timeout=30)
    if r.status_code != 200:
        raise VintageEndpointError(f"{path}: http {r.status_code}: {r.text[:160]}")
    return r.json()


def fetch_vintage_dates(series_id: str, *, api_key: Optional[str] = None,
                        session: Optional[requests.Session] = None) -> list[str]:
    """All dates on which this series was released/revised (ALFRED)."""
    js = _get_json("series/vintagedates",
                   {"series_id": series_id, "api_key": get_api_key(api_key)}, session)
    return list(js.get("vintage_dates", []))


def fetch_observations(series_id: str, *, obs_start: str, obs_end: str,
                       as_of: Optional[str] = None,
                       api_key: Optional[str] = None,
                       session: Optional[requests.Session] = None) -> pd.DataFrame:
    """Observations for ``[obs_start, obs_end]``.

    ``as_of`` set -> the series **as it was known on that date** (realtime = as_of):
    a true point-in-time vintage. ``as_of`` None -> latest (revised).
    Returns ``DataFrame[date, value]`` ('.' missing markers dropped, not filled).
    """
    params = {
        "series_id": series_id, "api_key": get_api_key(api_key),
        "observation_start": obs_start, "observation_end": obs_end,
    }
    if as_of is not None:
        params["realtime_start"] = as_of
        params["realtime_end"] = as_of
    js = _get_json("series/observations", params, session)
    rows = js.get("observations", [])
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["date", "value"])
    df = df.rename(columns={"date": "date"})[["date", "value"]]
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df["value"] = pd.to_numeric(df["value"], errors="coerce")  # FRED '.' -> NaN
    return df.dropna(subset=["value"]).sort_values("date").reset_index(drop=True)


@dataclass
class VintageVerdict:
    series_id: str
    as_of: str
    n_vintage_dates: int
    max_abs_diff_vs_latest: float
    identical_to_latest: bool
    trustworthy: bool
    reason: str
    control_ok: Optional[bool] = None
    detail: dict = field(default_factory=dict)


def assert_vintage_trustworthy(series_id: str, *, as_of: str,
                               obs_start: str, obs_end: str,
                               api_key: Optional[str] = None,
                               session: Optional[requests.Session] = None,
                               run_control: bool = True) -> VintageVerdict:
    """Requirement #2: HTTP 200 is NOT proof a vintage pull worked.

    Compares the as-of vintage against latest over the same window and decides:

    * differ            -> ``trustworthy=True`` (real point-in-time, series revised)
    * identical + the series has only ~1 vintage date
                        -> ``trustworthy=True``, reason ``single_vintage_never_revised``
                           (legitimate no-revision — EVIDENCE, not assumption)
    * identical + many vintage dates exist
                        -> ``trustworthy=False``, reason ``endpoint_not_honoring_realtime``
                           (the trap: it silently served latest — INVESTIGATE, do not use)

    ``run_control``: also pull a known-revised series (GDPC1) as-of vs latest; if
    even that comes back identical, the point-in-time call itself is broken
    (``control_ok=False``), which overrides any per-series conclusion.
    """
    key = get_api_key(api_key)
    vintage = fetch_observations(series_id, obs_start=obs_start, obs_end=obs_end,
                                 as_of=as_of, api_key=key, session=session)
    latest = fetch_observations(series_id, obs_start=obs_start, obs_end=obs_end,
                                as_of=None, api_key=key, session=session)
    merged = vintage.merge(latest, on="date", how="inner",
                           suffixes=("_vin", "_lat"))
    max_abs = float((merged["value_vin"] - merged["value_lat"]).abs().max()) \
        if not merged.empty else float("nan")
    identical = bool(merged.empty is False and max_abs == 0.0)
    n_vin = len(fetch_vintage_dates(series_id, api_key=key, session=session))

    control_ok = None
    if run_control:
        cv = fetch_observations(REVISED_CONTROL, obs_start=obs_start, obs_end=obs_end,
                                as_of=as_of, api_key=key, session=session)
        cl = fetch_observations(REVISED_CONTROL, obs_start=obs_start, obs_end=obs_end,
                                as_of=None, api_key=key, session=session)
        cm = cv.merge(cl, on="date", how="inner", suffixes=("_vin", "_lat"))
        # a revised control MUST differ across vintages if the call really works
        control_ok = (not cm.empty) and float((cm["value_vin"] - cm["value_lat"]).abs().max()) > 0.0

    if control_ok is False:
        trustworthy, reason = False, "point_in_time_call_broken (revised control identical)"
    elif not identical:
        trustworthy, reason = True, "distinguishable (series is revised; real vintage)"
    elif control_ok is True:
        # The revised control (GDPC1) DID differ across vintages, so the realtime
        # mechanism is verified working. This series being identical across
        # vintages is therefore genuine no-revision — EVIDENCE, not the trap.
        # (A series gets a new vintage date every time a new period is appended;
        # "many vintage dates" alone does NOT mean old values were revised.)
        trustworthy, reason = True, ("no_revision_confirmed: realtime verified via revised "
                                     "control (GDPC1 differs) yet this series is identical "
                                     "across vintages -> genuinely not revised (evidence)")
    elif n_vin <= 1:
        trustworthy, reason = True, "single_vintage_never_revised (evidence: series has one vintage)"
    else:
        # identical, many vintages, and NO passing control to prove the call works
        # -> cannot rule out the endpoint silently serving latest. Investigate.
        trustworthy, reason = False, ("endpoint_not_honoring_realtime? (identical despite many "
                                      "vintages and control not run) — investigate before use")

    return VintageVerdict(
        series_id=series_id, as_of=as_of, n_vintage_dates=n_vin,
        max_abs_diff_vs_latest=max_abs, identical_to_latest=identical,
        trustworthy=trustworthy, reason=reason, control_ok=control_ok,
        detail={"obs_start": obs_start, "obs_end": obs_end, "n_overlap": int(len(merged))},
    )
