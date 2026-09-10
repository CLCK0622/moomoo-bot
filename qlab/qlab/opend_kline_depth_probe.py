"""OpenD historical-K-line DEPTH + QUOTA + RATE probe (EVO-130 blocking item).

Read-only, quote-side measurement of what ``request_history_kline`` can actually
retrieve under the **current OpenD subscription** — the gate that decides whether
a swing walk-forward can cover the 2018 / 2020 / 2022 stress windows *before any
backtest is run*. Per the EVO-130 brief this is Step 1 and Step 1 only: if the
retrievable depth cannot reach the stress windows we ship a gap list and do NOT
fabricate a short-sample backtest.

Hard constraints honored (auditable):

* **Quote-only.** Opens ONLY ``OpenQuoteContext``. It never constructs an
  ``OpenSecTradeContext``, never unlocks trade, never places an order. The
  ``TrdEnv.SIMULATE`` lock is therefore satisfied vacuously — no trade env is
  ever selected because the trade path is never touched. ``trd_ctx_opened`` is
  reported ``False`` so a reviewer can confirm it.
* **Quota-frugal.** The historical-K quota is a scarce 30-day rolling resource.
  ``get_history_kl_quota(get_detail=True)`` is queried FIRST and is
  **non-consuming**; its ``detail`` list of already-counted codes drives the
  "free to re-pull" decision. Re-pulling a code that is already counted costs 0
  additional quota, so depth is measured on counted codes by preference and a
  full run consumes at most ``len(new codes you pass)`` fresh slots.
* **No fabrication.** If the SDK / gateway is absent the probe raises
  :class:`OpenDUnavailable` (same contract as ``events.datafetch.opend_daily``)
  rather than emitting invented depth. Every number in ``report.json`` is a live
  measurement or a documented ``None``.

Run it (needs a reachable OpenD gateway + ``moomoo-api``)::

    python -m qlab.opend_kline_depth_probe --out qlab/reports/opend_kline_depth

The offline unit test (``tests/test_kline_depth_probe.py``) injects a fake quote
context, so build/test/lint stays green with no gateway.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Callable, List, Optional

import numpy as np
import pandas as pd


class OpenDUnavailable(RuntimeError):
    """Raised when the moomoo SDK / OpenD gateway is not importable/reachable."""


# The stress windows the EVO-130 brief flags as must-cover for a credible
# walk-forward. Each is a representative slice inside the named year; the overall
# gate only needs the retrievable floor to sit at/below the earliest of these.
STRESS_WINDOWS = {
    "2018_volmageddon": ("2018-01-15", "2018-03-15"),   # Feb-2018 vol blow-up
    "2018_Q4_selloff": ("2018-10-01", "2018-12-31"),    # Q4-2018 draw-down
    "2020_covid_crash": ("2020-02-15", "2020-04-30"),   # COVID crash + rebound
    "2022_rate_bear": ("2022-01-01", "2022-12-31"),     # 2022 rate-hike bear
}

# Gate line: to cover all three flagged years the retrievable floor must reach
# at least the start of the earliest window.
COVERAGE_FLOOR_DATE = "2018-01-01"

DEFAULT_DEEP_START = "2000-01-01"   # asks well below any plausible floor
DEFAULT_KTYPE = "K_DAY"
DEFAULT_AUTYPE = "qfq"


# --------------------------------------------------------------------------- #
# Live quote-context factory (lazy import so the module loads without the SDK)
# --------------------------------------------------------------------------- #
def _live_quote_ctx_factory(host: str, port: int):
    """Return a zero-arg factory that opens a live ``OpenQuoteContext``.

    Importing ``moomoo`` and connecting are both deferred to call time so the
    module imports cleanly on a host with no SDK/gateway (the unit test never
    calls this — it injects a fake context instead).
    """
    try:
        from moomoo import OpenQuoteContext  # noqa: WPS433 (lazy on purpose)
    except Exception as exc:  # noqa: BLE001
        raise OpenDUnavailable(
            "moomoo SDK not importable. Install moomoo-api matching your OpenD "
            f"gateway version and run on a host with a reachable gateway. "
            f"Underlying error: {exc!r}"
        ) from exc

    def _factory():
        try:
            return OpenQuoteContext(host=host, port=port)
        except Exception as exc:  # noqa: BLE001
            raise OpenDUnavailable(
                f"could not open OpenQuoteContext at {host}:{port}: {exc!r}"
            ) from exc

    return _factory


# --------------------------------------------------------------------------- #
# Pure measurement helpers (no SDK dependency — unit-testable directly)
# --------------------------------------------------------------------------- #
def _pull_full_daily(ctx, code: str, *, start: str, end: str, ktype: str,
                     autype: str, max_count: int, pause: float,
                     ret_ok: int) -> dict:
    """Paginate ``request_history_kline`` for one code; measure depth + latency.

    Returns ``{rows, requests, earliest, latest, latency_ms:[...], error}``. Never
    raises on an API error — the error is recorded so the batch keeps going.
    """
    chunks: List[pd.DataFrame] = []
    latency_ms: List[float] = []
    page_req_key = None
    requests = 0
    error: Optional[str] = None
    while True:
        t0 = time.perf_counter()
        ret, data, page_req_key = ctx.request_history_kline(
            code, start=start, end=end, ktype=ktype, autype=autype,
            max_count=max_count, page_req_key=page_req_key,
        )
        latency_ms.append((time.perf_counter() - t0) * 1000.0)
        requests += 1
        if ret != ret_ok:
            error = str(data)[:200]
            break
        if data is not None and not data.empty:
            chunks.append(data)
        if not page_req_key:
            break
        time.sleep(pause)

    out = {"code": code, "rows": 0, "requests": requests,
           "earliest": None, "latest": None, "latency_ms": latency_ms,
           "error": error}
    if not chunks:
        return out
    df = pd.concat(chunks, ignore_index=True)
    df["time_key"] = pd.to_datetime(df["time_key"])
    df = df.drop_duplicates(subset=["time_key"]).sort_values("time_key")
    out["rows"] = int(len(df))
    out["earliest"] = str(df["time_key"].min().date())
    out["latest"] = str(df["time_key"].max().date())
    out["_frame"] = df  # kept in-memory for stress-window counting; stripped before JSON
    return out


def _stress_coverage(frame: pd.DataFrame) -> dict:
    """Bar counts inside each stress window on a single symbol's daily frame."""
    cov = {}
    tk = frame["time_key"]
    for name, (a, b) in STRESS_WINDOWS.items():
        m = frame[(tk >= a) & (tk <= b)]
        cov[name] = {
            "covered": bool(len(m) > 0),
            "n_bars": int(len(m)),
            "first": str(m["time_key"].min().date()) if len(m) else None,
            "last": str(m["time_key"].max().date()) if len(m) else None,
        }
    return cov


def _pctile(vals: List[float], p: float) -> Optional[float]:
    return float(np.percentile(vals, p)) if vals else None


def _classify_counted(quota_detail, codes: List[str]) -> dict:
    """Split ``codes`` into already-counted (free re-pull) vs new (consumes 1)."""
    counted = {d.get("code") for d in (quota_detail or [])}
    return {
        "already_counted": [c for c in codes if c in counted],
        "would_consume": [c for c in codes if c not in counted],
    }


# --------------------------------------------------------------------------- #
# Probe
# --------------------------------------------------------------------------- #
def probe(out_dir: Path, *,
          depth_symbols: Optional[List[str]] = None,
          deep_start: str = DEFAULT_DEEP_START,
          end: str = "2026-07-10",
          ktype: str = DEFAULT_KTYPE,
          autype: str = DEFAULT_AUTYPE,
          max_count: int = 1000,
          pause: float = 0.35,
          burst_n: int = 20,
          host: str = "127.0.0.1",
          port: int = 11111,
          ctx_factory: Optional[Callable] = None,
          ret_ok: Optional[int] = None,
          write: bool = True) -> dict:
    """Measure retrievable depth, quota, and request rate for daily history K.

    ``ctx_factory`` and ``ret_ok`` are injectable for offline testing; when left
    ``None`` the live moomoo SDK is used. ``depth_symbols`` defaults to a couple
    of large, long-listed US names that the EVO-24 fetch already counted (so
    re-pulling them for depth is free); pass the swing universe to also measure
    the codes you actually need.
    """
    out_dir = Path(out_dir)
    if depth_symbols is None:
        # US.AAPL is already quota-counted by the EVO-24 fetch (free re-pull);
        # US.SPY is the S5 (FOMC) essential and the natural floor witness.
        depth_symbols = ["US.AAPL", "US.SPY"]

    if ctx_factory is None:
        ctx_factory = _live_quote_ctx_factory(host, port)
    if ret_ok is None:
        try:
            from moomoo import RET_OK  # noqa: WPS433
            ret_ok = RET_OK
        except Exception:  # noqa: BLE001
            ret_ok = 0

    ctx = ctx_factory()
    report: dict = {
        "probe": "opend_kline_depth",
        "purpose": "EVO-130 blocking item: request_history_kline retrievable "
                   "depth + quota under current OpenD subscription",
        "host": f"{host}:{port}",
        "ktype": ktype,
        "autype": autype,
        "trd_ctx_opened": False,   # this probe never opens a trade context
        "trd_env_touched": None,   # no trade env ever selected (quote-only)
    }
    try:
        # 1) global / market state (context, not a gate input)
        try:
            r, gs = ctx.get_global_state()
            report["market_us"] = gs.get("market_us") if r == ret_ok else "UNKNOWN"
            report["qot_logined"] = gs.get("qot_logined") if r == ret_ok else None
        except Exception as exc:  # noqa: BLE001
            report["market_us"] = "UNKNOWN"
            report["global_state_error"] = str(exc)[:160]

        # 2) NON-CONSUMING quota query (must run before any pull)
        rq, used, remaining, detail = None, None, None, []
        try:
            # SDK contract: (ret, (used, remaining, detail_list)) when get_detail=True.
            rq, qdata = ctx.get_history_kl_quota(get_detail=True)
            if rq == ret_ok and qdata is not None:
                used, remaining = qdata[0], qdata[1]
                detail = qdata[2] if len(qdata) > 2 else []
        except Exception as exc:  # noqa: BLE001
            report["quota_error"] = str(exc)[:160]
        total = (used + remaining) if (used is not None and remaining is not None) else None
        report["quota"] = {
            "total": total, "used": used, "remaining": remaining,
            "window_days": 30,
            "counted_codes": [d.get("code") for d in (detail or [])],
            "note": "historical-K quota is per-account, per 30-day rolling window; "
                    "re-pulling an already-counted code costs 0 additional quota.",
        }
        report["quota_plan"] = _classify_counted(detail, depth_symbols)

        # 3) depth per symbol + stress-window coverage
        sym_reports: dict = {}
        all_latency: List[float] = []
        floor_dates: List[str] = []
        # union stress coverage across probed symbols (a window counts as covered
        # if ANY probed symbol has bars in it — depth is a subscription property)
        union_cov: dict = {k: {"covered": False, "n_bars": 0} for k in STRESS_WINDOWS}
        for code in depth_symbols:
            res = _pull_full_daily(ctx, code, start=deep_start, end=end, ktype=ktype,
                                   autype=autype, max_count=max_count, pause=pause,
                                   ret_ok=ret_ok)
            all_latency.extend(res.get("latency_ms", []))
            frame = res.pop("_frame", None)
            if frame is not None and len(frame):
                floor_dates.append(res["earliest"])
                res["stress_coverage"] = _stress_coverage(frame)
                for k, v in res["stress_coverage"].items():
                    if v["covered"]:
                        union_cov[k]["covered"] = True
                        union_cov[k]["n_bars"] = max(union_cov[k]["n_bars"], v["n_bars"])
            sym_reports[code] = res
        report["depth"] = {
            "symbols": sym_reports,
            "floor_date": min(floor_dates) if floor_dates else None,
            "years_retrievable": (
                round((pd.Timestamp(end) - pd.Timestamp(min(floor_dates))).days / 365.25, 1)
                if floor_dates else None
            ),
        }
        report["stress_coverage_union"] = union_cov

        # 4) request-rate / frequency probe on an already-counted code (free).
        #    A short burst of single-page requests; watch for a throttle error.
        rate_code = next((c for c in depth_symbols
                          if c in report["quota_plan"]["already_counted"]), depth_symbols[0])
        burst_lat: List[float] = []
        throttle_err = None
        t_start = time.perf_counter()
        n_ok = 0
        for _ in range(max(0, burst_n)):
            s = time.perf_counter()
            ret, data, _key = ctx.request_history_kline(
                rate_code, start="2024-01-01", end=end, ktype=ktype,
                autype=autype, max_count=max_count,
            )
            dt = (time.perf_counter() - s) * 1000.0
            if ret == ret_ok:
                n_ok += 1
                burst_lat.append(dt)
            else:
                throttle_err = str(data)[:160]
                break
        elapsed = time.perf_counter() - t_start
        report["rate"] = {
            "burst_code": rate_code,
            "requests_ok": n_ok,
            "elapsed_s": round(elapsed, 3),
            "req_per_s": round(n_ok / elapsed, 2) if elapsed > 0 and n_ok else None,
            "latency_ms": {"p50": _pctile(burst_lat, 50), "p95": _pctile(burst_lat, 95),
                           "max": max(burst_lat) if burst_lat else None},
            "throttle_error": throttle_err,
            "note": "historical-K request rate is SDK-paced; the binding resource "
                    "constraint is the 30-day symbol quota above, not this rate.",
        }

        # 5) THE GATE
        floor = report["depth"]["floor_date"]
        covers = bool(floor is not None and floor <= COVERAGE_FLOOR_DATE
                      and all(v["covered"] for v in union_cov.values()))
        gap_list = []
        if not covers:
            if floor is None:
                gap_list.append("no daily history returned for any probed symbol")
            elif floor > COVERAGE_FLOOR_DATE:
                gap_list.append(
                    f"retrievable floor {floor} is later than required "
                    f"{COVERAGE_FLOOR_DATE}; stress years before the floor are unreachable")
            for k, v in union_cov.items():
                if not v["covered"]:
                    gap_list.append(f"stress window {k} has 0 retrievable bars")
        report["gate"] = {
            "required_floor_date": COVERAGE_FLOOR_DATE,
            "measured_floor_date": floor,
            "covers_2018_2020_2022": covers,
            "verdict": "PASS_NO_GAP" if covers else "GAP",
            "gap_list": gap_list,
        }
    finally:
        try:
            ctx.close()
        except Exception:  # noqa: BLE001
            pass

    if write:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "report.json").write_text(json.dumps(report, indent=2, default=str))
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="OpenD historical-K depth/quota/rate probe (EVO-130)")
    ap.add_argument("--out", default="qlab/reports/opend_kline_depth")
    ap.add_argument("--symbols", nargs="*", default=None,
                    help="depth-probe codes, e.g. US.AAPL US.SPY (default: US.AAPL US.SPY)")
    ap.add_argument("--deep-start", default=DEFAULT_DEEP_START)
    ap.add_argument("--end", default="2026-07-10")
    ap.add_argument("--burst-n", type=int, default=20)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=11111)
    args = ap.parse_args(argv)
    rep = probe(Path(args.out), depth_symbols=args.symbols, deep_start=args.deep_start,
                end=args.end, burst_n=args.burst_n, host=args.host, port=args.port)
    summary = {
        "verdict": rep["gate"]["verdict"],
        "measured_floor_date": rep["gate"]["measured_floor_date"],
        "years_retrievable": rep["depth"]["years_retrievable"],
        "quota": {k: rep["quota"][k] for k in ("total", "used", "remaining")},
        "rate_req_per_s": rep["rate"]["req_per_s"],
        "gap_list": rep["gate"]["gap_list"],
    }
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
