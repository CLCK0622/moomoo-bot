"""Explicit synthetic fixtures. No accounts, source adapters or market returns."""

from __future__ import annotations

from datetime import date, timedelta

from .adapter import raw_target
from .contract import ARM, PROFILE_SHA, VERSION, bindings, canonical, digest
from .runtime import Runtime
from .snapshot import build_decision

OPEN = "2026-10-30T13:30:00Z"
START = "2026-10-29T22:00:00Z"
END = "2026-10-29T22:01:00Z"


def payload(fees):
    main = bindings()
    assets = main["input_snapshot"]["asset_order"]
    days = []
    d = date(2026, 10, 29)
    while len(days) < 252:
        if d.weekday() < 5:
            days.append(d.isoformat())
        d -= timedelta(days=1)
    days.reverse()
    zeros = {s: 0 for s in assets}
    qty = dict(zeros, QQQ=12)
    source = digest("SYNTHETIC_NOT_MARKET_DATA")
    prices = {s: "1000" if s == "QQQ" else "100" for s in assets}
    bars = {
        s: [
            dict(
                symbol=s,
                session=t,
                raw_open_usd=prices[s],
                raw_high_usd=prices[s],
                raw_low_usd=prices[s],
                raw_close_usd=prices[s],
                raw_volume_shares=10000,
                source_published_at_utc=START,
                observed_at_utc=START,
                source_sha256=source,
                availability_reason=None,
            )
            for t in days
        ]
        for s in assets
    }
    return dict(
        arm_version=VERSION,
        decision_session=days[-1],
        information_cutoff_utc="2026-10-29T22:00:00Z",
        exchange_timezone="America/New_York",
        calendar_id="SYNTHETIC_WEEKDAYS_NOT_EXCHANGE",
        calendar_sha256=digest(days),
        asset_order=assets,
        bars252=bars,
        causal_events=[],
        derived_TR={s: ["100"] * 252 for s in assets},
        eligibility={s: "VERIFIED_ELIGIBLE" for s in assets[:-1]},
        raw_prices_close=prices,
        adv20_usd={s: "10000000" for s in assets},
        x2_control_state=dict(
            nav_usd="15000",
            available_cash_usd="3000",
            receivable_dividends_usd="0",
            inventory_qty=qty,
            lot_first_fill_session={
                s: "2026-10-20" if qty[s] else None for s in assets
            },
            holding_age_sessions=dict(zeros, QQQ=5),
            cooldown_remaining_sessions=dict(zeros),
            unresolved_intents=[],
            risk_latch=False,
        ),
        policy_state=dict(global_position=5, drawdown_fraction="0", integrity_exits=[]),
        required_action_plan_M=dict(qty),
        cost_bindings=fees.binding,
        source_manifest=[dict(sha256=source, published_at=START, observed_at=START)],
        profile_sha256=PROFILE_SHA,
        diagnostic_state_kind_or_authorized_forward_state_receipt="SYNTHETIC_E0",
    )


def execution(d, fees):
    return dict(
        reference_open_session="2026-10-30",
        reference_open_utc=OPEN,
        raw_open_usd=dict(d["raw_prices_close"]),
        x2_control_state=d["x2_control_state"],
        required_plan_M=d["required_action_plan_M"],
        risk_age_cooldown_state=d["policy_state"],
        fee_binding=fees.binding,
        adv20_usd=d["adv20_usd"],
        eligibility=d["eligibility"],
        calendar_sha256=d["calendar_sha256"],
        corporate_action_and_cash_receipts=d["causal_events"],
        input_sha256=d["input_sha256"],
    )


def output(d, forecast=1000):
    ranks = [s for s, e in d["eligibility"].items() if e == "VERIFIED_ELIGIBLE"]
    _, q, _ = raw_target(d, ranks)
    return dict(
        arm_version=VERSION,
        snapshot_id=d["snapshot_id"],
        input_sha256=d["input_sha256"],
        decision_session=d["decision_session"],
        status="READY",
        reason_code="OK",
        ranked_symbols=ranks,
        targets=[dict(symbol=s, target_qty=q[s]) for s in d["asset_order"]],
        forecasts_h10_bps=[
            dict(symbol=s, gross_return_bps=0 if s == "QQQ" else forecast)
            for s in d["asset_order"]
        ],
        profile_sha256=PROFILE_SHA,
    )


def frozen(runtime):
    config = dict(
        prompt_version=bindings()["prompt"]["sha256"],
        model_snapshot=bindings()["model_binding"]["model_canonical_id"],
        parameters={"effort": "high"},
        ruleset=PROFILE_SHA,
    )
    return runtime.freeze(
        at="2026-10-29T21:00:00Z",
        configuration=config,
        aggregation=dict(
            canonical_index=1,
            entry_repetitions=30,
            monitor_repetitions=5,
            max_signature_mismatches=0,
        ),
    )


def metadata(archive, index, d=None, raw=None):
    b = bindings()["model_binding"]
    from .contract import FIXTURES, sha

    config = dict(
        prompt_version=bindings()["prompt"]["sha256"],
        model_snapshot=b["model_canonical_id"],
        parameters={"effort": "high"},
        ruleset=PROFILE_SHA,
    )
    context = dict(
        system_prompt_sha256=bindings()["prompt"]["sha256"],
        user_input_sha256=sha(canonical(d)),
        output_schema_sha256=sha(
            (FIXTURES / "EVO896-output-schema-v0.1.2.json").read_bytes()
        ),
        tools=[],
    )
    stream = dict(
        provider_model=b["model_canonical_id"],
        provider_request_id="synthetic-request-%s" % index,
        raw_response_sha256=sha(raw),
        status="success",
    )
    return dict(
        provider_model=b["model_canonical_id"],
        cli_version=b["cli_exact_version"],
        binary_before_sha256=b["cli_binary_sha256"],
        binary_after_sha256=b["cli_binary_sha256"],
        context_sha256=archive.put(canonical(context)),
        tools=[],
        subscription_route="existing_subscription",
        fallback=False,
        request_count_known=True,
        provider_request_id_or_unknown="synthetic-request-%s" % index,
        cli_invocation_id="synthetic-invocation-%s" % index,
        retry_of=None,
        purpose="synthetic_diagnostic",
        status="success",
        authority_chain_receipt=archive.put(
            canonical(
                dict(
                    schema="arm_n.fixture_receipt/v1",
                    arm_tag=ARM,
                    configuration_id=digest(config),
                    pre_reserved=True,
                )
            )
        ),
        stderr_redacted_sha256=archive.put(b""),
        visible_events_sha256=archive.put(canonical(stream)),
    )


def group(archive, d, raws, *, entry=False, group_id="synthetic-group"):
    rt = Runtime(archive)
    frozen(rt)
    for i, raw in enumerate(raws, 1):
        rt.record_generation(
            attempt_id="synthetic-%d" % i,
            group_id=group_id,
            index=i,
            decision=d,
            raw=raw,
            metadata=metadata(archive, i, d, raw),
            start=START,
            end=END,
            reference_open_utc=OPEN,
        )
    rt.seal_group(group_id, at="2026-10-29T22:02:00Z", entry=entry)
    return rt


def decision(fees):
    return build_decision(payload(fees))
