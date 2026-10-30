"""Versioned pre-score receipts. No acquisition, liquidation or runtime approval.

The producer supplies source-bound gate evidence. These checks establish receipt
consistency; they do not independently attest the supplied market/source facts.
"""

from copy import deepcopy
from datetime import datetime
import math

from .contract import digest, is_sha, result
from .conventions import load_conventions
from .fees import finite, iso_date
from .input_scope import reject_b2_inputs

ROLES = {
    "train_solo_probes",
    "train_calibration",
    "train_meta",
    "external_reference_roles",
    "test_meta",
    "authorized_forward",
}
STATES = {"VERIFIED_USABLE", "VERIFIED_INELIGIBLE", "QUARANTINED", "UNKNOWN"}
FIELDS = {
    "symbol",
    "field_role",
    "from_date",
    "to_date_or_null_with_reason",
    "reason",
    "source_sha256",
    "dependency_lineage",
    "evidence_version",
    "state",
    "gates_by_date",
    "received_at",
}
GATES = {
    "history_dates",
    "raw_price",
    "dollar_adv",
    "units_verified",
    "security_line_verified",
    "recipe_inputs_verified",
}


def timestamp(s):
    t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError("isolation.timezone_required")
    return t


def seal_manifest(request, policy=None):
    """Close the input schema before scoring; no outcome-dependent selectors."""
    reject_b2_inputs(request, "features")
    p = policy or load_conventions()
    if p.document["version"] not in ("v2.0.0", "v3.0.0"):
        raise ValueError("isolation.v2_required")
    allowed = {
        "role",
        "records",
        "mode",
        "sealed_at",
        "first_performance_at",
        "signal_close",
    }
    if set(request) - allowed or request.get("role") not in ROLES:
        raise ValueError("isolation.outcome_selector_or_role_forbidden")
    if request.get("mode") not in ("history", "forward"):
        raise ValueError("isolation.mode_required")
    sealed = timestamp(request["sealed_at"])
    if sealed >= timestamp(request["first_performance_at"]):
        raise ValueError("isolation.not_preperformance")
    universe = p.profile["universe"]
    records = deepcopy(request["records"])
    if not isinstance(records, list):
        raise ValueError("isolation.records_required")
    for r in records:
        if (
            set(r) != FIELDS
            or r["symbol"] not in universe
            or r["field_role"] != "selection"
            or r["state"] not in STATES
            or not r["reason"]
            or not r["evidence_version"]
            or not is_sha(r["source_sha256"])
            or not isinstance(r["dependency_lineage"], list)
            or not r["dependency_lineage"]
            or (
                p.document["version"] == "v2.0.0"
                and not all(is_sha(x) for x in r["dependency_lineage"])
            )
            or not isinstance(r["gates_by_date"], dict)
        ):
            raise ValueError("isolation.evidence_incomplete")
        start, end = iso_date(r["from_date"]), r["to_date_or_null_with_reason"]
        if end is not None and iso_date(end) < start:
            raise ValueError("isolation.range_invalid")
        received = timestamp(r["received_at"])
        if received > sealed or (
            request["mode"] == "forward"
            and received > timestamp(request["signal_close"])
        ):
            raise ValueError("isolation.evidence_not_received_in_time")
        for date, g in r["gates_by_date"].items():
            if (
                set(g) != GATES
                or not start <= iso_date(date)
                or (end is not None and date > end)
            ):
                raise ValueError("isolation.gates_or_date_invalid")
    payload = {"request": deepcopy(request), **p.binding}
    sealed = dict(payload, quarantine_manifest_sha256=digest(payload))
    if p.document["version"] == "v3.0.0":
        from .event_quarantine import normalize_dependencies, _project, sources

        graph = normalize_dependencies({"isolation_manifest": sealed})
        projected = {r["id"]: r for r in _project(graph, sources()[0])}
        for record in records:
            if record["state"] == "VERIFIED_USABLE" and any(
                projected[n["id"]]["reasons"] for n in record["dependency_lineage"]
            ):
                raise ValueError("isolation.verified_member_has_quarantined_ancestry")
    return sealed


def checked_manifest(sealed, policy):
    expected = seal_manifest(sealed["request"], policy)
    if expected != sealed:
        raise ValueError("isolation.sealed_identity_mismatch")


def eligible_day(sealed, date, policy=None):
    p = policy or load_conventions()
    checked_manifest(sealed, p)
    if date not in p.calendar:
        raise ValueError("isolation.date_outside_calendar")
    i = p.calendar.index(date)
    history = list(p.calendar[max(0, i - 251) : i + 1])
    status, reasons = {}, {}
    for symbol in p.profile["universe"]:
        rows = [
            r
            for r in sealed["request"]["records"]
            if r["symbol"] == symbol
            and r["from_date"] <= date
            and (
                r["to_date_or_null_with_reason"] is None
                or date <= r["to_date_or_null_with_reason"]
            )
        ]
        states = {r["state"] for r in rows}
        state = "UNKNOWN"
        if "QUARANTINED" in states:
            state = "QUARANTINED"
        elif states == {"VERIFIED_INELIGIBLE"}:
            # A concrete failed price threshold proves exclusion; absence does not.
            if all(
                finite(r["gates_by_date"].get(date, {}).get("raw_price"))
                and 0
                < r["gates_by_date"][date]["raw_price"]
                < p.profile["signal_params"]["entry_signal_price_min_usd"]
                for r in rows
            ):
                state = "VERIFIED_INELIGIBLE"
        elif states == {"VERIFIED_USABLE"}:

            def usable(r):
                g = r["gates_by_date"].get(date, {})
                return (
                    len(history) == 252
                    and g.get("history_dates") == history
                    and finite(g.get("raw_price"))
                    and g["raw_price"]
                    >= p.profile["signal_params"]["entry_signal_price_min_usd"]
                    and finite(g.get("dollar_adv"))
                    and g["dollar_adv"] > 0
                    and all(
                        g.get(k) is True
                        for k in (
                            "units_verified",
                            "security_line_verified",
                            "recipe_inputs_verified",
                        )
                    )
                )

            if all(usable(r) for r in rows):
                state = "VERIFIED_USABLE"
        status[symbol] = state
        reasons[symbol] = [r["reason"] for r in rows] or ["isolation.evidence_missing"]
    eligible = sorted(s for s, state in status.items() if state == "VERIFIED_USABLE")
    upper = len(eligible) + sum(x == "UNKNOWN" for x in status.values())
    quantity = (
        "VERIFIED_GE50"
        if len(eligible) >= 50
        else "VERIFIED_LT50"
        if upper < 50
        else "UNKNOWN"
    )
    payload = {
        "date": date,
        "eligible": eligible,
        "states": status,
        "reasons": reasons,
        "verified_count": len(eligible),
        "upper_bound": upper,
        "quantity_state": quantity,
        "quarantine_manifest_sha256": sealed["quarantine_manifest_sha256"],
        "new_tilt_allowed": quantity == "VERIFIED_GE50",
        "required_M_valuation_cash_fees_still_required": True,
        **p.binding,
    }
    return dict(payload, eligible_set_derivation_sha256=digest(payload))


def rank_scores(scores, eligible):
    """Average ties, no padding and no post-score deletion to rescue a recipe."""
    if set(scores) != set(eligible):
        raise ValueError("isolation.score_membership_or_padding")
    if not all(finite(x) for x in scores.values()) or len(set(scores.values())) < 2:
        raise ValueError("isolation.nonfinite_or_constant_recipe_date")
    ordered = sorted(eligible, key=lambda s: (scores[s], s))
    result, i = {}, 0
    while i < len(ordered):
        j = i + 1
        while j < len(ordered) and scores[ordered[j]] == scores[ordered[i]]:
            j += 1
        u = ((i + 1 + j) / 2 - 0.5) / len(eligible)
        for s in ordered[i:j]:
            result[s] = u
        i = j
    return result


def score_day(sealed, date, scorer, policy=None):
    """The scorer sees E(t) only. Labels/returns are not an input to E(t)."""
    p = policy or load_conventions()
    day = eligible_day(sealed, date, p)
    ranks = None
    scores = None
    if day["quantity_state"] == "VERIFIED_GE50":
        ids = p.document["variance_layers"]["family_definitions"]["candidate_members"]
        scores = scorer(tuple(day["eligible"]))
        if set(scores) != set(ids):
            raise ValueError("isolation.recipe_family_incomplete")
        ranks = {k: {s: None for s in p.profile["universe"]} for k in ids}
        for k in ids:
            ranks[k].update(rank_scores(scores[k], day["eligible"]))
    payload = {
        "day": day,
        "ranks": ranks,
        "scores": scores,
        "receipt_consistency_only": True,
        "strict_count_independently_certified": False,
        "selection_bias": p.document["pre_score_isolation"]["selection_bias"],
        "runtime_consumable": False,
        "certifiable": False,
    }
    return dict(payload, rank_receipt_sha256=digest(payload))


def verify_rank_receipt(receipt, sealed, policy=None):
    p = policy or load_conventions()
    if (
        digest({k: v for k, v in receipt.items() if k != "rank_receipt_sha256"})
        != receipt["rank_receipt_sha256"]
    ):
        raise ValueError("isolation.rank_receipt_identity_mismatch")
    day = eligible_day(sealed, receipt["day"]["date"], p)
    if day != receipt["day"] or day["quantity_state"] != "VERIFIED_GE50":
        raise ValueError("isolation.ranked_quantity_or_mask_mismatch")
    ids = p.document["variance_layers"]["family_definitions"]["candidate_members"]
    if set(receipt["ranks"]) != set(ids):
        raise ValueError("isolation.recipe_family_incomplete")
    for k, row in receipt["ranks"].items():
        if set(row) != set(p.profile["universe"]) or any(
            (not finite(row[s]) or not 0 < row[s] < 1)
            if s in day["eligible"]
            else row[s] is not None
            for s in row
        ):
            raise ValueError("isolation.rank_membership_or_padding")
        if not math.isclose(
            math.fsum(row[s] for s in day["eligible"]), len(day["eligible"]) / 2
        ):
            raise ValueError("isolation.rank_denominator_invalid")
        expected = {s: None for s in p.profile["universe"]}
        expected.update(rank_scores(receipt["scores"][k], day["eligible"]))
        if expected != row:
            raise ValueError("isolation.rank_denominator_or_ties_invalid")
    return day


def selection_projection(request, policy):
    """Remove only explicitly tagged selection consumers from the old blanket halt.

    Holdings, rights, cash and untagged consumers retain their original blockers.
    Isolated inputs remain in the returned audit list; U64 is never rewritten.
    """
    sealed = request["isolation_manifest"]
    checked_manifest(sealed, policy)
    projected, removed, days = deepcopy(request), [], {}
    fields = {
        "feature",
        "raw_close",
        "raw_open",
        "total_return",
        "C",
        "r",
        "history",
        "ADV",
        "volume",
    }
    for key in ("inputs", "dependency_nodes"):
        keep = []
        for item in request.get(key, []):
            if item.get("consumer_role") in ROLES and item.get("field") in fields:
                d = item["date"]
                days.setdefault(d, eligible_day(sealed, d, policy))
                state = days[d]["states"].get(item.get("symbol"), "UNKNOWN")
                if state != "VERIFIED_USABLE":
                    removed.append(
                        dict(
                            item,
                            value=None,
                            isolation_state=state,
                            reason=days[d]["reasons"].get(
                                item.get("symbol"), ["isolation.not_U64"]
                            ),
                        )
                    )
                    continue
            keep.append(item)
        projected[key] = keep
    return projected, removed, days


def isolation_readout(request, *, conventions=None):
    p = conventions or load_conventions()
    metrics, reasons = {"rank_receipt": None, "quantity_state": None}, []
    try:
        if set(request) != {"manifest", "date", "scores"}:
            raise ValueError("isolation.readout_schema_invalid")
        sealed = seal_manifest(request["manifest"], p)
        receipt = score_day(sealed, request["date"], lambda names: request["scores"], p)
        metrics.update(
            rank_receipt=receipt,
            quantity_state=receipt["day"]["quantity_state"],
            manifest=sealed,
        )
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        reasons.append(
            str(exc) if isinstance(exc, ValueError) else "isolation.input_missing"
        )
    return p.bind(
        result(
            "pre_score_isolation",
            request,
            metrics=metrics,
            reasons=reasons,
            assumptions=[
                "Synthetic/producer receipt consistency only; quantity does not waive any remaining financial gate."
            ],
        )
    )
