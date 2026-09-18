"""FRED Treasury constant-maturity yields — free, keyless daily curve source.

Candidate A (rate-carry sleeve) needs the Treasury yield curve to build
curve-steepness / roll-down signals. FRED publishes the H.15 constant-maturity
series as a plain CSV with **no API key**::

    https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS2

so this is a first-class free source alongside :mod:`qlab.events.datafetch.prices`
(Stooq/Yahoo/Nasdaq for equities). Same honesty contract: every fetch returns
``(DataFrame | None, note)`` and a blocked/empty pull degrades to an explicit
gap, never fabricated numbers.

Series (H.15 constant maturity, % per annum, close-of-day):

    DGS1MO DGS3MO DGS6MO DGS1 DGS2 DGS5 DGS7 DGS10 DGS20 DGS30

FRED marks non-trading days and missing observations with ``"."`` — we drop
those rather than forward-fill, so no look-ahead / synthetic value is injected.
The consumer (signal layer) decides alignment/lag; publication timing is
close-of-day for the trade date, so deciding at close ``t`` and executing at
``t+1`` open is look-ahead-free.

Output: a wide panel ``data/fred_yields.parquet`` with columns
``[date, <series...>]`` (yields in percent), plus a provenance JSON.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Iterable, Optional, Tuple

import pandas as pd
import requests

# Full curve; steepness signals typically use DGS2/DGS10, roll-down the belly.
DEFAULT_SERIES = ["DGS3MO", "DGS2", "DGS5", "DGS10", "DGS30"]
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

Result = Tuple[Optional[pd.DataFrame], str]


def fetch_fred_series(series_id: str, start: str, end: str,
                      session: Optional[requests.Session] = None) -> Result:
    """One FRED series -> ``(DataFrame[date, <series_id>] | None, note)``.

    ``"."`` observation markers (holidays / missing) are dropped, not filled.
    """
    session = session or requests.Session()
    session.headers.setdefault("User-Agent", BROWSER_UA)
    params = {
        "id": series_id,
        "cosd": pd.Timestamp(start).strftime("%Y-%m-%d"),
        "coed": pd.Timestamp(end).strftime("%Y-%m-%d"),
    }
    try:
        r = session.get(FRED_CSV, params=params, timeout=30)
    except requests.RequestException as e:
        return None, f"fred {series_id}: request error {type(e).__name__}"
    if r.status_code != 200:
        return None, f"fred {series_id}: http {r.status_code}"
    df = pd.read_csv(io.StringIO(r.text))
    # FRED renamed the date header to `observation_date`; older exports use `DATE`.
    date_col = next((c for c in df.columns if c.lower() in ("observation_date", "date")), None)
    if date_col is None or series_id not in df.columns:
        return None, f"fred {series_id}: unexpected columns {list(df.columns)}"
    df = df.rename(columns={date_col: "date"})[["date", series_id]]
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    # FRED uses "." for missing; coerce to NaN then drop those rows for this series.
    df[series_id] = pd.to_numeric(df[series_id], errors="coerce")
    df = df.dropna(subset=[series_id]).sort_values("date").reset_index(drop=True)
    if df.empty:
        return None, f"fred {series_id}: 0 observations in window"
    return df, f"fred {series_id}: {len(df)} obs (H.15 constant maturity, % p.a.)"


def fetch_curve(series: Iterable[str] = DEFAULT_SERIES,
                start: str = "2002-01-01", end: str = "2026-12-31",
                session: Optional[requests.Session] = None) -> Tuple[pd.DataFrame, dict]:
    """Fetch several series and outer-join into a wide date-indexed panel.

    Returns ``(wide_df, notes)``. ``wide_df`` has one row per trading day that
    appears in *any* fetched series; a series missing a given day stays NaN
    (never forward-filled). ``notes[series]`` records fetched/blocked per series.
    """
    session = session or requests.Session()
    frames: list[pd.DataFrame] = []
    notes: dict = {}
    for sid in series:
        df, note = fetch_fred_series(sid, start, end, session=session)
        notes[sid] = note
        if df is not None:
            frames.append(df.set_index("date"))
    if not frames:
        return pd.DataFrame(columns=["date"]), notes
    wide = pd.concat(frames, axis=1).sort_index()
    wide.index.name = "date"
    wide = wide.reset_index()
    # column order = requested order, keep only the ones that came back
    cols = ["date"] + [s for s in series if s in wide.columns]
    return wide[cols], notes


def write_parquet(wide: pd.DataFrame, out_path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wide.to_parquet(out_path, index=False)
    return out_path
