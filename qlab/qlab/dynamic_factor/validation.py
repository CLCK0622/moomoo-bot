"""Calendar/price and explicit walk-forward boundary checks, before any fitting."""

from __future__ import annotations

from .conventions import authoritative

from datetime import date

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


def convention_manifest_reasons(manifest, conventions):
    expected = conventions.fold_manifest()
    return (
        ["wf.conventions_manifest_mismatch"]
        if any(manifest.get(k) != v for k, v in expected.items())
        else []
    )


def jump_reversals(rows, config, index):
    """Flag raw adjacent-observation reversal patterns, including off-calendar bad bars."""
    jump, tolerance, gap = (
        config[k]
        for k in (
            "min_abs_jump",
            "max_abs_roundtrip",
            "max_observation_gap_calendar_days",
        )
    )
    if (
        not finite(jump)
        or jump <= 0
        or not finite(tolerance)
        or tolerance < 0
        or type(gap) is not int
        or gap < 1
    ):
        raise ValueError("invalid_jump_policy")
    found = []
    for before, middle, after in zip(rows, rows[1:], rows[2:]):
        prices = [r["close"] for r in (before, middle, after)]
        if not all(finite(v) and v > 0 for v in prices):
            continue
        d0, d1, d2 = [date.fromisoformat(r["date"]) for r in (before, middle, after)]
        if not (0 < (d1 - d0).days <= gap and 0 < (d2 - d1).days <= gap):
            continue
        first, second = prices[1] / prices[0] - 1, prices[2] / prices[1] - 1
        restore = prices[2] / prices[0] - 1
        if abs(first) >= jump and first * second < 0 and abs(restore) <= tolerance:
            dates = [r["date"] for r in (before, middle, after)]
            found.append(
                {
                    "date": middle["date"],
                    "window_dates": dates,
                    "observed_jump": first,
                    "next_observation_change": second,
                    "roundtrip_change": restore,
                    "adjacent_reference_sessions": all(d in index for d in dates)
                    and index[dates[1]] == index[dates[0]] + 1
                    and index[dates[2]] == index[dates[1]] + 1,
                }
            )
    return found


def _wf_manifest_check_unbound(manifest, *, conventions=None):
    reasons, issues = [], {}
    try:
        index = calendar_index(manifest["calendar"])
        calendar = manifest["calendar"]
        series = manifest["series"]
        config = manifest.get("jump_reversal_policy")
        if config is None and conventions is not None:
            config = conventions.document.get("jump_reversal_policy")
        if config is None:
            reasons.append("data.jump_reversal_policy_missing")
        else:
            try:
                jump_reversals([], config, index)
            except (ValueError, TypeError, KeyError):
                reasons.append("data.jump_reversal_policy_invalid")
                config = None
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
                "date_reasons": {d: ["data.nontrading_bar"] for d in holidays},
            }
            for d in missing:
                issues[name]["date_reasons"].setdefault(d, []).append(
                    "data.calendar_gap"
                )
            if config is not None:
                patterns = jump_reversals(rows, config, index)
                issues[name]["jump_reversals"] = patterns
                if patterns:
                    reasons.append("data.jump_reversal")
                for pattern in patterns:
                    issues[name]["date_reasons"].setdefault(pattern["date"], []).append(
                        "data.jump_reversal"
                    )
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
        if conventions is not None:
            reasons.extend(convention_manifest_reasons(manifest, conventions))
    except (KeyError, ValueError, TypeError):
        reasons.append("data.manifest_invalid_or_missing")
    # Validation is not a beta/IR estimator. It never forward-fills prices.
    reason = (
        "calendar_or_price_validation_failed" if reasons else "estimator_not_connected"
    )
    report = result(
        "wf_manifest_check",
        {"manifest": manifest, **(conventions.binding if conventions else {})},
        reasons=reasons,
        metrics={"beta": None, "information_ratio": None, "series_checks": issues},
        availability={k: unavailable(reason) for k in ("beta", "information_ratio")},
        assumptions=[
            "Caller supplies a frozen unified exchange calendar with provenance.",
            "Missingness is checked within each series' own range; benchmarks must match portfolio dates.",
            "No price repair, calendar alignment, or forward-fill is performed.",
        ],
    )
    return conventions.bind(report) if conventions else report


def quarantined_manifest(manifest, rows, conventions):
    from .input_disposition import panel_input_check

    return panel_input_check(
        {
            "inputs": manifest.get("panel_inputs", [])
            + [item for row in rows for item in row.get("panel_inputs", [])],
            "dependency_nodes": manifest.get("dependency_nodes", [])
            + [node for row in rows for node in row.get("dependency_nodes", [])],
            "replacement_symbols": manifest.get("replacement_symbols"),
            "truncate_sample": manifest.get("truncate_sample"),
            **(
                {"panel_symbols": manifest["panel_symbols"]}
                if "panel_symbols" in manifest
                else {}
            ),
        },
        conventions=conventions,
    )


def wf_manifest_check(manifest, *, conventions=None):
    from .conventions import load_conventions

    reasons = ["wf.conventions_required"] if conventions is None else []
    if conventions is not None and not authoritative(conventions):
        reasons.append("wf.conventions_mismatch")
    if conventions is not None:
        reasons.extend(convention_manifest_reasons(manifest, conventions))
    if reasons:
        return result(
            "wf_manifest_check",
            {"manifest": manifest},
            reasons=reasons,
            metrics={"beta": None, "information_ratio": None, "series_checks": {}},
        )
    if conventions.document["version"] in ("v1.0.1", "v2.0.0"):
        from .valuation import vti_evidence_check
        from .input_disposition import panel_input_check
        from .scope_proof import b2_manifest_check
        from .contract import digest

        try:
            panel = panel_input_check(
                {
                    "inputs": manifest.get("panel_inputs", []),
                    "replacement_symbols": manifest.get("replacement_symbols"),
                    "truncate_sample": manifest.get("truncate_sample"),
                    "dependency_nodes": manifest.get("dependency_nodes", []),
                    **(
                        {"panel_symbols": manifest["panel_symbols"]}
                        if "panel_symbols" in manifest
                        else {}
                    ),
                },
                conventions=conventions,
            )
            if not panel["ok"]:
                raise ValueError(panel["reasons"][0])
            if "VTI" not in manifest.get("benchmarks", []):
                raise ValueError("data.VTI_fixed_B2_required")
            if "QQQ" not in manifest["benchmarks"]:
                raise ValueError("data.QQQ_fixed_B1_required")
            if "b2_manifest" in manifest:
                b2 = b2_manifest_check(manifest["b2_manifest"], conventions)
                if [
                    r["date"] for r in manifest.get("series", {}).get("QQQ", [])
                ] != list(conventions.calendar):
                    raise ValueError("data.QQQ_full_frozen_calendar_required")
                if "VTI" in manifest.get("series", {}):
                    raise ValueError("scope.B2_series_must_stay_in_separate_readout")
                primary = dict(
                    manifest,
                    benchmarks=[b for b in manifest["benchmarks"] if b != "VTI"],
                )
                primary.pop("b2_manifest")
                primary.pop("benchmark_evidence", None)
                report = _wf_manifest_check_unbound(primary, conventions=conventions)
                report["input_sha256"] = digest(
                    {"manifest": manifest, **conventions.binding}
                )
                report["metrics"].update(
                    B2=b2, data_bindings_complete=True, all_readouts_available=False
                )
                report["assumptions"].append(
                    "B2 metadata is present but unavailable; only primary calendar/data precheck can pass. Runtime gates remain independent."
                )
                return report
            vti_evidence_check(
                manifest.get("benchmark_evidence", {}).get("VTI"), conventions
            )
        except ValueError as exc:
            return conventions.bind(
                result(
                    "wf_manifest_check",
                    {"manifest": manifest, **conventions.binding},
                    reasons=[str(exc)],
                    metrics={
                        "beta": None,
                        "information_ratio": None,
                        "series_checks": {},
                        "B2": None,
                    },
                )
            )
    return _wf_manifest_check_unbound(manifest, conventions=conventions)
