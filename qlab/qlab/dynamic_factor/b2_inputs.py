"""Separate B2 diagnostics with field-level provenance and a snapshot-off switch.

No strategy consumer imports this module. Existing source receipts are read
offline; no issuer/OpenD requests or real return generation happen at import.
"""

import csv
import io
import json

from .contract import is_sha, result, sha256
from .conventions import FIXTURES, load_conventions
from .fees import finite
from .fixture_inventory import frozen_fixture_hashes


def event_inputs(include_snapshot=True):
    hashes = frozen_fixture_hashes()
    root = FIXTURES / "vti-b2-r3"
    manifest = json.loads((root / "EVO891-VTI-B2-manifest-r3.json").read_bytes())
    raw = (root / manifest["events_file"]).read_bytes()
    half = (root / manifest["halfyear_file"]).read_bytes()
    if (
        sha256(raw) != manifest["events_sha256"]
        or sha256(half) != manifest["halfyear_sha256"]
    ):
        raise ValueError("B2.input_source_SHA_mismatch")
    rehab = next(
        r["sha256"] for r in manifest["non_event_inputs"] if "get_rehab" in r["input"]
    )
    events = []
    for row in csv.DictReader(io.StringIO(raw.decode())):
        issuer = row["source_sha256"].split(";")[0].split(":")[-1]
        fields, levels = {}, {}

        def field(name, value, tier, source):
            fields[name] = (
                None
                if tier == "issuer_snapshot_only" and not include_snapshot
                else value
            )
            levels[name] = dict(
                tier=tier,
                source_sha256=source,
                enabled=include_snapshot or tier != "issuer_snapshot_only",
            )

        def number(value):
            return float(value) if value else None

        amount = number(row["rehab_amount"])
        field("rehab_amount", amount, "OpenD_get_rehab", rehab)
        field(
            "rehab_ex_date",
            row["ex_date"] if amount is not None else None,
            "OpenD_get_rehab",
            rehab,
        )
        for name, value in (
            ("issuer_amount", number(row["issuer_amount"])),
            ("issuer_ex_date", row["ex_date"]),
            ("issuer_record_date", row["record_date"]),
            ("issuer_pay_date", row["pay_date"]),
            ("issuer_reinvest_price", number(row["issuer_reinvest_price"])),
            ("per_event_split_crosscheck", row["rehab_vs_issuer"]),
        ):
            field(name, value, "issuer_snapshot_only", issuer)
        field(
            "audited_half_year_sum",
            number(row["audited_half_year_sum"]),
            "audited_aggregate_constraint_only",
            row["constraint_filings_sha256"],
        )
        tier = "OpenD_get_rehab" if amount is not None else "issuer_snapshot_only"
        field(
            "D_used_for_TR",
            amount if amount is not None else number(row["issuer_amount"]),
            tier,
            rehab if amount is not None else issuer,
        )
        events.append(
            dict(
                # Identity preserves the row/calendar even when the event's actual
                # ex-date field loses its only source. It is not asserted evidence.
                event_key=row["ex_date"],
                identity_kind="frozen_source_row_key_not_verified_exdate",
                fields=fields,
                field_sources=levels,
                snapshot_only_fields=[
                    k for k, v in levels.items() if v["tier"] == "issuer_snapshot_only"
                ],
                reasons=[]
                if fields["D_used_for_TR"] is not None
                else ["B2.snapshot_only_distribution_disabled"],
            )
        )
    return events, dict(
        manifest_sha256=hashes["vti-b2-r3/EVO891-VTI-B2-manifest-r3.json"],
        events_sha256=sha256(raw),
        halfyear_sha256=sha256(half),
        rehab_source_sha256=rehab,
        source_scope="EVO891 source receipt transcription; raw OpenD/issuer sources not reacquired by this tool",
        audited_aggregates="constraint only; never allocate them to event amounts or dates",
        issuer_source_label="issuer public-page snapshot; terms verification pending",
        immutable_calendar_sha256=manifest["isolation"]["items"][-1]["contract_fields"][
            -1
        ]["value"],
    )


def b2_input_readout(request, *, conventions=None):
    policy = conventions or load_conventions()
    metrics = dict(events=None, daily=None, formal_return=None, account_cash=None)
    reasons, provenance = [], None
    try:
        enabled = request.get("include_issuer_snapshot_fields", True)
        if type(enabled) is not bool:
            raise ValueError("B2.snapshot_switch_must_be_boolean")
        events, provenance = event_inputs(enabled)
        metrics.update(
            events=events,
            include_issuer_snapshot_fields=enabled,
            calendar=list(policy.calendar),
        )
        if "prices" in request:
            prices = request["prices"]
            if (
                request.get("price_basis") != "raw_close"
                or not is_sha(request.get("raw_source_sha256"))
                or [r["date"] for r in prices] != list(policy.calendar)
                or any(not finite(r["close"]) or r["close"] <= 0 for r in prices)
            ):
                raise ValueError("B2.original_full_calendar_raw_prices_required")
            by_date = {e["event_key"]: e["fields"]["D_used_for_TR"] for e in events}
            daily, previous, index = [], None, 100.0
            for row in prices:
                d = by_date.get(row["date"], 0)
                r = (
                    None
                    if previous is None or d is None
                    else (row["close"] + d) / previous - 1
                )
                if previous is not None:
                    index = None if index is None or r is None else index * (1 + r)
                daily.append(
                    dict(
                        date=row["date"],
                        raw_close=row["close"],
                        raw_price_return=None
                        if previous is None
                        else row["close"] / previous - 1,
                        daily_total_return=r,
                        cumulative_index=index,
                        field_sources={
                            "date": "frozen_common_calendar",
                            "raw_close": request["raw_source_sha256"],
                            "raw_price_return": "derived_from_adjacent_raw_closes",
                            "daily_total_return": "derived_from_raw_closes_and_event_D_used_for_TR",
                            "cumulative_index": "derived_from_all_previous_daily_total_returns",
                        },
                        reasons=["B2.snapshot_only_distribution_disabled"]
                        if d is None
                        else [],
                    )
                )
                previous = row["close"]
            metrics["daily"] = daily
        metrics["snapshot_disabled_event_keys"] = [
            e["event_key"] for e in events if e["fields"]["D_used_for_TR"] is None
        ]
    except (KeyError, TypeError, ValueError, OSError) as exc:
        reasons.append(
            str(exc) if isinstance(exc, ValueError) else "B2.input_invalid_or_missing"
        )
    return policy.bind(
        result(
            "b2_input_readout",
            {"request": request, "provenance": provenance, **policy.binding},
            metrics=metrics,
            reasons=reasons,
            assumptions=[
                "B2 source diagnostics only; no formal full-period return acceptance, strategy performance, reference run or account receipt.",
                "OpenD get_rehab is the event backbone; audited aggregates constrain totals; issuer snapshot fields are supplemental and individually removable.",
                "Unknown event distributions null that daily TR and dependent cumulative index; unaffected daily returns/raw prices and all frozen dates remain.",
                "Issuer pay date is not account cash arrival; issuer reinvest price is not substituted for raw market close.",
            ],
            availability={
                "formal_return": {
                    "available": False,
                    "reason": "B2.formal_full_period_acceptance_missing",
                }
            },
        )
    )
