"""Calendar/price and explicit walk-forward boundary checks, before any fitting."""

from __future__ import annotations

from .contract import result, unavailable
from .fees import finite, iso_date


def calendar_index(calendar):
    if not calendar or not isinstance(calendar, list):
        raise ValueError("calendar_missing")
    if [iso_date(d) for d in calendar] != sorted(set(calendar)):
        raise ValueError("calendar_invalid")
    return {d: i for i, d in enumerate(calendar)}


def fold_reasons(manifest):
    reasons = []
    try:
        index = calendar_index(manifest["calendar"])
        horizon, embargo = manifest["label_horizon"], manifest["embargo"]
        if any(type(v) is not int or v < 0 for v in (horizon, embargo)):
            return ["wf.invalid_horizon_or_embargo"]
        if not manifest["folds"]:
            return ["wf.folds_missing"]
        previous_end = -1
        ids = set()
        for fold in manifest["folds"]:
            a, b, c, d = [
                index[fold[k]]
                for k in ("train_start", "train_end", "test_start", "test_end")
            ]
            if not fold["fold_id"] or fold["fold_id"] in ids:
                reasons.append("wf.fold_id_invalid")
            ids.add(fold["fold_id"])
            if not a <= b < c <= d or c <= previous_end:
                reasons.append("wf.nonforward_or_overlapping_fold")
            if b + horizon >= c:
                reasons.append("wf.future_label_rejected")
            if b + horizon + embargo >= c:
                reasons.append("wf.embargo_violation")
            previous_end = d
    except (KeyError, ValueError, TypeError):
        reasons.append("wf.manifest_invalid_or_missing")
    return list(dict.fromkeys(reasons))


def wf_manifest_check(manifest):
    reasons, issues = [], {}
    try:
        index = calendar_index(manifest["calendar"])
        calendar = manifest["calendar"]
        series = manifest["series"]
        if not isinstance(series, dict) or not series:
            raise ValueError("series_missing")
        for name, rows in series.items():
            if not isinstance(rows, list):
                raise ValueError("series_invalid")
            dates, bad_prices = [], []
            for row in rows:
                dates.append(iso_date(row["date"]))
                if not finite(row["close"]) or row["close"] <= 0:
                    bad_prices.append(row["date"])
            if not dates:
                issues[name] = {"empty": True}
                reasons.append("data.empty_series")
                continue
            holidays = sorted(set(dates) - set(index))
            missing = sorted(
                set(d for d in calendar if min(dates) <= d <= max(dates)) - set(dates)
            )
            outside = min(dates) < calendar[0] or max(dates) > calendar[-1]
            issues[name] = {
                "missing_dates": missing,
                "nontrading_dates": holidays,
                "nonpositive_or_unknown_prices": bad_prices,
                "calendar_coverage_incomplete": outside,
            }
            if dates != sorted(set(dates)):
                reasons.append("data.duplicate_or_unsorted_dates")
            if missing:
                reasons.append("data.calendar_gap")
            if holidays:
                reasons.append("data.nontrading_bar")
            if bad_prices:
                reasons.append("data.nonpositive_or_unknown_price")
            if outside:
                reasons.append("data.calendar_coverage_incomplete")
        portfolio = manifest["portfolio"]
        if not manifest["benchmarks"]:
            raise ValueError("benchmarks_missing")
        portfolio_dates = [r["date"] for r in series[portfolio]]
        for name in manifest["benchmarks"]:
            if [r["date"] for r in series[name]] != portfolio_dates:
                reasons.append("data.benchmark_calendar_gap")
        reasons.extend(fold_reasons(manifest))
    except (KeyError, ValueError, TypeError):
        reasons.append("data.manifest_invalid_or_missing")
    # Validation is not a beta/IR estimator. It never forward-fills prices.
    reason = (
        "calendar_or_price_validation_failed" if reasons else "estimator_not_connected"
    )
    return result(
        "wf_manifest_check",
        manifest,
        reasons=reasons,
        metrics={"beta": None, "information_ratio": None, "series_checks": issues},
        availability={k: unavailable(reason) for k in ("beta", "information_ratio")},
        assumptions=[
            "Caller supplies a frozen unified exchange calendar with provenance.",
            "Missingness is checked within each series' own range; benchmarks must match portfolio dates.",
            "No price repair, calendar alignment, or forward-fill is performed.",
        ],
    )
