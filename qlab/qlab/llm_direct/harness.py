"""Synthetic adversarial acceptance harness; no model or network transport."""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from qlab.llm_direct.arm_n import event
from qlab.dynamic_factor.pipeline import _n_snapshot
from qlab.dynamic_factor.statistics import dsr_eval_arm
from qlab.dynamic_factor.contract import source_manifest as dynamic_sources
from qlab.dynamic_factor.ledger import AttemptLedger
from qlab.shadow15k import ledger as ledger_module
from qlab.shadow15k.harness import fixture_fees, offline
from qlab.shadow15k.ledger import ShadowLedger

from . import archive as archive_module
from .adapter import adapt
from .archive import Archive
from .contract import (
    ARM,
    BINDINGS,
    FIXTURES,
    PROFILE_SHA,
    VERSION,
    bindings,
    canonical,
    digest,
    sha,
    validate_output,
)
from .intent import envelope, register_synthetic
from .milestone import decide
from .reference import ReferenceBook, signal
from .runtime import Runtime, nontrivial
from .snapshot import build_decision
from .synthetic import (
    END,
    OPEN,
    START,
    decision,
    execution,
    frozen,
    group,
    metadata,
    output,
    payload,
)


def refused(call, contains):
    try:
        call()
    except (ValueError, KeyError, TypeError) as exc:
        if contains not in str(exc):
            raise AssertionError(
                "wrong refusal: %s (expected %s)" % (exc, contains)
            ) from exc
        return str(exc)
    raise AssertionError("accepted negative: " + contains)


def run(workdir):
    root = Path(workdir).resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError("harness.empty_private_workdir_required")
    root.mkdir(parents=True, exist_ok=True)
    cases = []

    def archive_for(path):
        # Each adversarial scenario is a separate synthetic host. The actual
        # runtime has one fixed host anchor and one persistent version registry.
        with patch.object(archive_module, "PHYSICAL_ROOT", path.resolve()):
            return Archive(path / "archive")

    def case(cid, fn):
        observed = fn()
        assert observed is not False, cid
        cases.append(dict(case_id=cid, status="PASS", observed=observed))

    with (
        offline() as attempts,
        patch.object(archive_module, "PHYSICAL_ROOT", root),
        patch.object(ledger_module, "PHYSICAL_ROOT", root),
    ):
        fees = fixture_fees("x2")
        d = decision(fees)
        x = execution(d, fees)
        o = output(d)
        raw = canonical(o)
        case(
            "bindings.seven_SHA_and_receipt_links",
            lambda: dict(BINDINGS) if bindings() else None,
        )

        def bad_output(key, value, reason):
            b = deepcopy(o)
            b["targets"][0][key] = value
            return refused(lambda: validate_output(json.dumps(b).encode(), d), reason)

        for name, value, reason in [
            ("float", 6.0, "decimal_strings"),
            ("bool", True, "integer_shares"),
            ("string", "6", "integer_shares"),
            ("negative", -1, "integer_shares"),
        ]:
            case(
                "schema." + name + "_shares",
                lambda v=value, r=reason: bad_output("target_qty", v, r),
            )
        case("schema.outside_panel", lambda: bad_output("symbol", "SPY", "asset_order"))
        case(
            "schema.duplicate_symbol",
            lambda: bad_output("symbol", "ABBV", "asset_order"),
        )
        case(
            "schema.duplicate_JSON_key",
            lambda: refused(
                lambda: validate_output(b'{"status":"READY","status":"ABSTAIN"}', d),
                "duplicate_key",
            ),
        )
        case(
            "schema.truncated",
            lambda: refused(lambda: validate_output(raw[:-4], d), "json.invalid"),
        )
        case(
            "schema.nonfinite",
            lambda: refused(lambda: validate_output(b'{"bad":NaN}', d), "nonfinite"),
        )
        extra = deepcopy(o)
        extra["future_labels"] = []
        case(
            "schema.extra_field",
            lambda: refused(
                lambda: validate_output(canonical(extra), d), "exact_fields"
            ),
        )

        def bad_input(change, reason):
            p = payload(fees)
            change(p)
            return refused(lambda: build_decision(p), reason)

        case(
            "data.future_bar",
            lambda: bad_input(
                lambda p: p["bars252"]["AAPL"][-1].update(
                    observed_at_utc="2026-10-30T14:00:00Z"
                ),
                "future_or_invalid_bar",
            ),
        )
        case(
            "data.unknown_eligibility",
            lambda: bad_input(
                lambda p: p["eligibility"].update(AAPL="UNKNOWN"), "eligibility_unknown"
            ),
        )
        case(
            "data.missing_history",
            lambda: bad_input(lambda p: p["bars252"]["AAPL"].pop(), "history252"),
        )
        case(
            "data.future_top_level",
            lambda: bad_input(
                lambda p: p.update(next_open="19"), "exact_decision_fields"
            ),
        )
        case(
            "data.unresolved_intent",
            lambda: bad_input(
                lambda p: p["x2_control_state"].update(
                    unresolved_intents=["unknown-submit"]
                ),
                "unreconciled_state",
            ),
        )

        for price, cancelled in [
            ("19", True),
            ("19.99", True),
            ("20", False),
            ("20.01", False),
        ]:

            def boundary(price=price, cancelled=cancelled):
                changed = deepcopy(x)
                changed["raw_open_usd"]["AAPL"] = price
                r = adapt(raw, d, changed, fees)
                assert ("AAPL" in r["cancelled_buy_symbols"]) == cancelled
                assert r["P"]["AAPL"] == (0 if cancelled else 6)
                assert all(
                    r["P"][s] <= o["targets"][i]["target_qty"]
                    for i, s in enumerate(d["asset_order"])
                )
                assert (
                    r["trace"].index("PRICE_CANCEL")
                    < r["trace"].index("FINAL_P")
                    < r["trace"].index("COSTS")
                    < r["trace"].index("G_K")
                )
                return dict(P_AAPL=r["P"]["AAPL"], C2_P=r["C2_P"], trace=r["trace"])

            case("R3.boundary_" + price, boundary)

        def add_existing():
            p = payload(fees)
            p["raw_prices_close"]["AAPL"] = "40"
            for bar in p["bars252"]["AAPL"]:
                for field in (
                    "raw_open_usd",
                    "raw_high_usd",
                    "raw_low_usd",
                    "raw_close_usd",
                ):
                    bar[field] = "40"
            p["x2_control_state"]["inventory_qty"]["AAPL"] = 10
            p["x2_control_state"]["available_cash_usd"] = "2600"
            p["x2_control_state"]["holding_age_sessions"]["AAPL"] = 5
            p["required_action_plan_M"]["AAPL"] = 10
            own = build_decision(p)
            ox = execution(own, fees)
            ox["raw_open_usd"]["AAPL"] = "19"
            r = adapt(canonical(output(own)), own, ox, fees)
            assert r["P"]["AAPL"] == 10 and r["M"]["AAPL"] == 10
            assert not any(
                q["symbol"] == "AAPL" and q["side"] == "SELL" for q in r["orders"]
            )
            assert output(own)["targets"][0]["target_qty"] == 15
            return dict(existing=10, proposed=15, after_cancel=r["P"]["AAPL"])

        case("R3.existing_position_add_no_forced_sale", add_existing)
        bad = deepcopy(x)
        bad["raw_open_usd"]["AAPL"] = "NaN"
        case("R3.bad_price", lambda: refused(lambda: adapt(raw, d, bad, fees), "money"))
        missing = deepcopy(x)
        del missing["raw_open_usd"]["AAPL"]
        case(
            "R3.missing_price",
            lambda: refused(lambda: adapt(raw, d, missing, fees), "prices_missing"),
        )

        def qqq_buy_exempt():
            p = payload(fees)
            p["x2_control_state"]["inventory_qty"]["QQQ"] = 0
            p["x2_control_state"]["available_cash_usd"] = "15000"
            p["required_action_plan_M"]["QQQ"] = 0
            own = build_decision(p)
            lowq = execution(own, fees)
            lowq["raw_open_usd"]["QQQ"] = "19"
            r = adapt(canonical(output(own)), own, lowq, fees)
            assert "QQQ" not in r["cancelled_buy_symbols"] and r["P"]["QQQ"] > 0
            assert any(q["symbol"] == "QQQ" and q["side"] == "BUY" for q in r["orders"])
            return dict(exempt=True, QQQ_buy_qty=r["P"]["QQQ"])

        case("R3.QQQ_exempt", qqq_buy_exempt)
        no_fee = deepcopy(x)
        del no_fee["fee_binding"]
        case(
            "cost.missing_fee_binding_refused",
            lambda: refused(
                lambda: adapt(raw, d, no_fee, fees), "required_fields_missing"
            ),
        )
        wrong_state = deepcopy(x)
        wrong_state["x2_control_state"]["inventory_qty"]["QQQ"] += 1
        case(
            "R1.execution_inventory_mismatch_refused",
            lambda: refused(
                lambda: adapt(raw, d, wrong_state, fees), "state_or_x2_binding_mismatch"
            ),
        )
        case(
            "cost.x1_cannot_control_x2",
            lambda: refused(lambda: adapt(raw, d, x, fixture_fees("x1")), "x2_binding"),
        )
        unknown = deepcopy(o)
        unknown["forecasts_h10_bps"][0]["gross_return_bps"] = None

        def null_mu():
            r = adapt(canonical(unknown), d, x, fees)
            assert not r["signature"]["approval_bit"] and r["final"] == r["M"]
            return r["rejection_reason"]

        case("GK.null_forecast_retains_M", null_mu)
        zero = canonical(output(d, 0))
        case(
            "GK.strict_zero_is_rejected",
            lambda: (
                adapt(zero, d, x, fees)["signature"]
                if not adapt(zero, d, x, fees)["signature"]["approval_bit"]
                else False
            ),
        )

        def cash_constraints():
            changed = deepcopy(x)
            changed["raw_open_usd"].update({s: "10000" for s in d["asset_order"][:5]})
            r = adapt(raw, d, changed, fees)
            assert all(r["P"][s] <= 6 for s in d["asset_order"][:5])
            assert r["P"] != {row["symbol"]: row["target_qty"] for row in o["targets"]}
            return dict(P=r["P"], C2_P=r["C2_P"])

        case("plan.monotone_cash_turnover_feasibility", cash_constraints)

        rt = group(archive_for(root / "agree"), d, [raw] * 5)
        case(
            "R1.pending_open_is_not_pass",
            lambda: rt.replay("synthetic-group", d, None, fees, at=END),
        )
        good = rt.replay("synthetic-group", d, x, fees, at=OPEN)
        assert good["passed"] and good["pairwise_comparisons"] == 10
        case(
            "R1.exact_final_signatures_pass",
            lambda: {"pairs": 10, "mismatches": good["pairwise_mismatches"]},
        )
        env = envelope(rt, "synthetic-group", decision_ts=OPEN)
        changed_env = deepcopy(env)
        changed_env["kernel"]["orders"][0]["planned_qty"] += 1
        case(
            "intent.tampered_envelope_refused_before_ledger_access",
            lambda: refused(
                lambda: register_synthetic(changed_env, None, runtime=rt),
                "archived_envelope_mismatch",
            ),
        )
        assert (
            envelope(
                Runtime(archive_for(root / "agree")),
                "synthetic-group",
                decision_ts="2026-11-01T13:30:00Z",
            )
            == env
        )
        case(
            "intent.restart_retry_same_business_ID",
            lambda: dict(
                intent_id=env["kernel"]["intent_id"],
                input_hash=env["kernel"]["input_hash"],
            ),
        )
        assert all(
            z["planned_qty"] > 0 and not z["protective"]
            for z in env["kernel"]["orders"]
        )

        def r1_failure():
            a = group(
                archive_for(root / "opposite"),
                d,
                [canonical(output(d, 100))] * 15 + [canonical(output(d, -100))] * 15,
                entry=True,
            )
            report = a.replay("synthetic-group", d, x, fees, at=OPEN)
            assert report["pairwise_comparisons"] == 435
            assert report["pairwise_mismatches"] == {
                k: 225 for k in report["pairwise_mismatches"]
            }
            assert report["original_metric_failures"] == 0 and not report["passed"]
            assert report["canonical_raw_output_sha256"] == sha(
                canonical(output(d, 100))
            )
            refused(
                lambda: envelope(a, "synthetic-group", decision_ts=OPEN),
                "version_terminated",
            )
            refused(
                lambda: frozen(Runtime(archive_for(root / "opposite"))),
                "version_terminated",
            )
            return dict(
                pairs=435,
                mismatches=report["pairwise_mismatches"],
                old_metric_failures=0,
                version_terminated=True,
            )

        case("R1.same_targets_opposite_approvals_225_pairs", r1_failure)

        def invalid_all():
            a = group(archive_for(root / "invalid"), d, [b"{}"][0:1] * 5)
            report = a.replay("synthetic-group", d, x, fees, at=OPEN)
            assert not report["passed"] and not report["results"]
            assert len(report["attempt_validation"]) == 5 and all(
                not v["valid"] for v in report["attempt_validation"]
            )
            return report["reasons"]

        case("R1.all_same_invalid_never_stable", invalid_all)

        def incomplete():
            a = group(archive_for(root / "short"), d, [raw] * 4)
            r = a.replay("synthetic-group", d, x, fees, at=OPEN)
            assert not r["passed"] and "R1.incomplete_repetitions" in r["reasons"]
            return r["reasons"]

        case("R1.incomplete_monitoring_group", incomplete)

        def log_probe(kind):
            ar = archive_for(root / kind)
            a = Runtime(ar)
            frozen(a)
            meta = metadata(ar, kind, d, raw)
            if kind == "binary_drift":
                meta["binary_after_sha256"] = digest("changed binary")
            elif kind == "fallback":
                meta["fallback"] = True
            elif kind == "hidden_requests":
                meta["request_count_known"] = False
            if kind == "snapshot_unavailable":
                return refused(
                    lambda: a.model_available(False, END), "snapshot_unavailable"
                )
            end = "2026-10-30T13:31:00Z" if kind == "late" else END
            a.record_generation(
                attempt_id=kind,
                group_id="g",
                index=1,
                decision=d,
                raw=raw,
                metadata=meta,
                start=START,
                end=end,
                reference_open_utc=OPEN,
            )
            assert ar.get(sha(raw)) == raw
            if kind == "late":
                return refused(
                    lambda: a.seal_group("g", at="2026-10-30T13:32:00Z", entry=False),
                    "version_terminated",
                )
            return refused(lambda: a.model_available(True, END), "version_terminated")

        for kind in (
            "binary_drift",
            "fallback",
            "hidden_requests",
            "snapshot_unavailable",
            "late",
        ):
            case("log." + kind, lambda kind=kind: log_probe(kind))
        altered = deepcopy(frozen(rt)["aggregation"])
        altered["canonical_index"] = 2
        case(
            "log.no_posthoc_aggregation",
            lambda: refused(
                lambda: rt.freeze(
                    at=START,
                    configuration=frozen(rt)["configuration"],
                    aggregation=altered,
                ),
                "aggregation_mismatch",
            ),
        )

        case("R1.no_300_request_claim_from_one_group", rt.entry_summary)

        def final_weights():
            changed = deepcopy(x)
            changed["raw_open_usd"].update({s: "30" for s in d["asset_order"][:5]})
            r = adapt(raw, d, changed, fees)
            original = {row["symbol"]: row["target_qty"] for row in o["targets"]}
            assert nontrivial(original, d)
            assert not nontrivial(r["final"], d, prices=changed["raw_open_usd"])
            return dict(raw_nontrivial=True, actual_open_final_nontrivial=False)

        case("R1.final_nontriviality_uses_actual_open_prices", final_weights)

        def repeated_request():
            ar = archive_for(root / "reused-provider-request")
            a = Runtime(ar)
            frozen(a)
            meta = metadata(ar, "same-actual-request", d, raw)
            args = dict(
                group_id="g",
                decision=d,
                raw=raw,
                metadata=meta,
                start=START,
                end=END,
                reference_open_utc=OPEN,
            )
            a.record_generation(attempt_id="first", index=1, **args)
            return refused(
                lambda: a.record_generation(attempt_id="second", index=2, **args),
                "fresh_session_or_request_reused",
            )

        case("log.fresh_sessions_cannot_reuse_request", repeated_request)
        case(
            "R1.campaign_schedule_not_posthoc",
            lambda: refused(
                lambda: rt.freeze_entry_sessions(
                    ["2026-11-%02d" % i for i in range(1, 11)],
                    calendar_sessions=["2026-11-%02d" % i for i in range(1, 11)],
                    calendar_sha256=digest(["2026-11-%02d" % i for i in range(1, 11)]),
                    at=START,
                ),
                "entry_schedule_after_generation",
            ),
        )

        def skipped_entry_calendar():
            a = Runtime(archive_for(root / "entry-calendar"))
            frozen(a)
            days = ["2026-11-%02d" % i for i in range(1, 12)]
            return refused(
                lambda: a.freeze_entry_sessions(
                    days[1:],
                    calendar_sessions=days,
                    calendar_sha256=digest(days),
                    at=START,
                ),
                "first_ten_sessions_must_be_frozen",
            )

        case("R1.entry_cannot_skip_first_frozen_session", skipped_entry_calendar)

        def mandatory():
            p = payload(fees)
            p["x2_control_state"]["inventory_qty"]["AAPL"] = 6
            p["x2_control_state"]["holding_age_sessions"]["AAPL"] = 20
            p["x2_control_state"]["available_cash_usd"] = "2400"
            own = build_decision(p)
            r = adapt(canonical(output(own, -10000)), own, execution(own, fees), fees)
            assert not r["signature"]["approval_bit"] and r["final"]["AAPL"] == 0
            sell = next(z for z in r["orders"] if z["symbol"] == "AAPL")
            assert sell["side"] == "SELL" and sell["protective"] is True
            return sell

        case("plan.age20_exit_survives_GK_rejection_protective_sell_only", mandatory)

        def abstain_protection():
            p = payload(fees)
            p["x2_control_state"]["inventory_qty"]["AAPL"] = 6
            p["x2_control_state"]["holding_age_sessions"]["AAPL"] = 20
            p["x2_control_state"]["available_cash_usd"] = "2400"
            own = build_decision(p)
            abstain = dict(
                output(own),
                status="ABSTAIN",
                reason_code="RISK_LATCH",
                ranked_symbols=[],
                targets=[],
                forecasts_h10_bps=[],
            )
            a = group(
                archive_for(root / "abstain-protection"), own, [canonical(abstain)] * 5
            )
            r = a.replay("synthetic-group", own, execution(own, fees), fees, at=OPEN)
            assert r["passed"] and not r["results"][0]["signature"]["approval_bit"]
            orders = r["results"][0]["orders"]
            assert (
                len(orders) == 1
                and orders[0]["symbol"] == "AAPL"
                and orders[0]["side"] == "SELL"
                and orders[0]["protective"]
                and orders[0]["planned_qty"] == 6
            )
            return dict(
                optional_approved=False,
                required_protective_orders=orders,
                execution_verified=False,
            )

        case("R1.ABSTAIN_keeps_independent_protective_M", abstain_protection)

        def no_op():
            p = payload(fees)
            p["policy_state"]["global_position"] = 4
            own = build_decision(p)
            a = group(archive_for(root / "noop"), own, [canonical(output(own))] * 5)
            r = a.replay("synthetic-group", own, execution(own, fees), fees, at=OPEN)
            assert r["passed"]
            result = envelope(a, "synthetic-group", decision_ts=OPEN)
            assert result["status"] == "NOOP" and result["kernel"]["orders"] == []
            return dict(status=result["status"], fabricated_orders=0)

        case("intent.NOOP_no_fabricated_order", no_op)

        def milestone_cases():
            args = dict(
                day=63,
                lower="-0.01",
                upper="0.01",
                extended=False,
                configuration_sha256=PROFILE_SHA,
                original_configuration_sha256=PROFILE_SHA,
            )
            for dsr in (None, "0.10"):
                assert (
                    decide(**args, dsr=dsr)["action"] == "EXTEND_ONCE_TO126_UNVERIFIED"
                )
            assert (
                decide(**dict(args, upper="0"), dsr="0.99")["action"] == "STOP_VERSION"
            )
            assert (
                decide(**dict(args, configuration_sha256=digest("changed")))["action"]
                == "DATA_INVALID_HANDOFF_NO_CLOCK_RESET"
            )
            refused(
                lambda: decide(**dict(args, extended=True)), "extension_already_used"
            )
            return dict(
                missing_DSR_does_not_block=True,
                low_DSR_does_not_block=True,
                QQQ_stop_first=True,
                second_extension_refused=True,
            )

        case(
            "A3.QQQ_stop_first_crosszero_extension_independent_of_DSR", milestone_cases
        )

        # N events use an isolated fixture chain. No authoritative writer is opened.
        chain = AttemptLedger(root / "fixture-chain.sqlite3")
        c = dict(
            prompt_version="synthetic-p1",
            model_snapshot="synthetic-model",
            parameters={},
            ruleset="synthetic-r1",
        )
        for arm in ("EVO883_FACTOR", ARM):
            chain.record(arm + ":reserve", event("configuration_reserved", arm, c))
            for i in range(2 if arm == "EVO883_FACTOR" else 7):
                chain.record(
                    arm + ":request:%d" % i,
                    event(
                        "generation_request",
                        arm,
                        c,
                        actual_request_id=arm + ":%d" % i,
                        request_count_known=True,
                        status="failed" if i == 0 else "success",
                        evidence_sha256=digest([arm, i]),
                    ),
                )
            for i in range(2):
                chain.record(
                    arm + ":outcome:%d" % i,
                    event(
                        "market_outcome_evaluated",
                        arm,
                        c,
                        evaluation_id=arm + ":outcome:%d" % i,
                        evidence_sha256=digest([arm, "outcome", i]),
                    ),
                )
        # Extra evaluated LLM configurations make cross-arm leakage observable,
        # while a reserved, unevaluated factor config must add nothing to primary N.
        for i in range(2):
            extra = dict(c, parameters={"synthetic_variant": i})
            chain.record(
                "extra:%d:reserve" % i, event("configuration_reserved", ARM, extra)
            )
            chain.record(
                "extra:%d:outcome" % i,
                event(
                    "market_outcome_evaluated",
                    ARM,
                    extra,
                    evaluation_id="extra:%d" % i,
                    evidence_sha256=digest(["extra", i]),
                ),
            )
        chain.record(
            "document-only",
            event(
                "configuration_reserved",
                "EVO883_FACTOR",
                dict(c, ruleset="unevaluated"),
            ),
        )

        def arm_inputs(arm_tag):
            # Exercise the actual readout/DSR/pipeline entries, not project().
            before = (chain.path.read_bytes(), chain.anchor_path.read_bytes())
            ledger_report = chain.arm_readout(arm_tag)
            request = {} if arm_tag is None else {"arm_tag": arm_tag}
            dsr_report = dsr_eval_arm(request, chain)
            pipeline_n = _n_snapshot(chain, 10**9, arm_tag=arm_tag)
            assert before == (chain.path.read_bytes(), chain.anchor_path.read_bytes())
            arm = dsr_report["metrics"]["arm_n"]
            assert ledger_report["metrics"]["arm_n"] == pipeline_n["arm_n"] == arm
            assert (
                dsr_report["metrics"]["N_rows"]
                == ledger_report["metrics"]["N_rows"]
                == pipeline_n["N_rows"]
            )
            assert (
                dsr_report["metrics"]["dsr"] is None and not dsr_report["certifiable"]
            )
            assert pipeline_n["gate_n"] is None and not pipeline_n["n_complete"]
            return arm

        factor = arm_inputs("EVO883_FACTOR")
        llm = arm_inputs(ARM)
        assert factor["observed_N_config"] == 1 and llm["observed_N_config"] == 3
        assert (
            factor["observed_N_generation_requests"] == 2
            and llm["observed_N_generation_requests"] == 7
        )
        case(
            "N.other_arm_trials_excluded",
            lambda: dict(
                factor=factor["observed_N_config"],
                llm=llm["observed_N_config"],
                entries=[
                    "dsr_eval",
                    "AttemptLedger.arm_readout",
                    "pipeline._n_snapshot",
                ],
                chain_unchanged=True,
            ),
        )
        assert [r["observed_N"] for r in factor["rows"]] == [1, 2] and factor[
            "cumulative_n"
        ] is None
        case(
            "N.config_primary_and_request_sensitivity_side_by_side",
            lambda: dict(
                rows=factor["rows"],
                duplicate_outcomes_count_once=True,
                failed_requests_retained=True,
                unevaluated_configuration_excluded=True,
            ),
        )
        missing = arm_inputs(None)
        assert missing["observed_N_config"] is None
        assert "arm_n.arm_tag_missing_or_invalid" in missing["reasons"]
        case("N.missing_request_arm_tag_refused", lambda: missing["reasons"])
        chain.record(
            "untagged", {"schema": "arm_n.event/v1", "kind": "generation_request"}
        )
        missing = arm_inputs(ARM)
        assert missing["observed_N_config"] is None
        assert "arm_n.event_arm_tag_missing_or_invalid" in missing["reasons"]
        case("N.missing_event_arm_tag_refused", lambda: missing["reasons"])

        def reference_cases():
            ar = archive_for(root / "reference")
            book = ReferenceBook(ar, "R1_MOM20")
            source = sha((Path(__file__).parent / "reference.py").read_bytes())
            args = dict(
                at=START,
                sessions=["2026-10-30", "2026-11-02"],
                producer_source_sha256=source,
            )
            book.freeze(**args)
            book.seal_day(
                session="2026-10-30",
                at="2026-10-30T21:00:00Z",
                source_bytes=b"SYNTHETIC_MARKET",
                ledger_bytes=b"SYNTHETIC_R1_BOOK",
                return_bytes=b"SYNTHETIC_RETURN_SOURCE_NOT_EVIDENCE",
                source_run_id="synthetic-r1-D0",
            )
            backfill = refused(
                lambda: book.seal_day(
                    session="2026-11-02",
                    at="2026-11-03T21:00:00Z",
                    source_bytes=b"s",
                    ledger_bytes=b"l",
                    return_bytes=b"r",
                    source_run_id="backfill",
                ),
                "backfill",
            )
            replacement = refused(
                lambda: ReferenceBook(ar, "R2_REV20").freeze(**args),
                "event_identity_conflict",
            )
            assert (
                signal("R1_MOM20", d)["ranked_symbols"]
                == signal("R2_REV20", d)["ranked_symbols"]
            )  # constant prices: frozen ticker tie-break
            return dict(
                backfill=backfill, replacement=replacement, frozen_tie_break=True
            )

        case("reference.daily_seal_no_backfill_no_replacement", reference_cases)

        def integration():
            # Build one canonical x2 state from actual synthetic accounting, rather
            # than pretending the fixture's initial target was already filled.
            books = {}
            for scenario in ("x2", "x1"):
                g = dict(
                    namespace="evo881.shadow15k.offline",
                    mode="offline_synthetic",
                    initial_cash="15000",
                    candidate_id=ARM,
                    version=VERSION,
                    price_basis="reference",
                )
                book = ShadowLedger(
                    root / scenario / "shadow15k", g, fixture_fees(scenario)
                )
                seed = dict(
                    intent_id="synthetic-seed",
                    decision_ts="2026-10-28T13:30:00Z",
                    input_hash=digest("synthetic seed"),
                    orders=[
                        dict(
                            order_id="synthetic-seed-QQQ",
                            symbol="QQQ",
                            side="BUY",
                            planned_qty=12,
                            trade_date="2026-10-28",
                            protective=False,
                        )
                    ],
                )
                assert book.register_intent(seed)["ok"]
                assert book.record_receipt(
                    "synthetic-seed",
                    dict(
                        receipt_id="synthetic-seed-fill",
                        receipt_ts="2026-10-28T13:31:00Z",
                        orders=[
                            dict(
                                order_id="synthetic-seed-QQQ",
                                confirmed_qty=12,
                                gross_usd="12000",
                                fee_known=True,
                                status="filled",
                            )
                        ],
                    ),
                )["ok"]
                books[scenario] = book
            marks = dict(
                as_of="2026-10-29T21:00:00Z",
                price_basis="reference",
                prices={"QQQ": "1000"},
            )
            initial = books["x2"].readout(marks)["metrics"]
            p = payload(fees)
            p["x2_control_state"]["available_cash_usd"] = initial["available_cash"]
            p["x2_control_state"]["nav_usd"] = initial["nav"]
            own = build_decision(p)
            ox = execution(own, fees)
            a = group(
                archive_for(root / "integration"), own, [canonical(output(own))] * 5
            )
            report = a.replay("synthetic-group", own, ox, fees, at=OPEN)
            assert report["passed"]
            env = envelope(a, "synthetic-group", decision_ts=OPEN)
            for book in books.values():
                assert register_synthetic(env, book, runtime=a)["ok"]
                assert register_synthetic(env, book, runtime=a)["ok"]
                # Unconfirmed intent is blocked, not silently assumed filled.
                pending = book.readout(dict(marks, as_of=OPEN))["metrics"]
                assert (
                    pending["reconciliation_required"]
                    and not pending["execution_verified"]
                )
                orders = env["kernel"]["orders"]
                receipt = dict(
                    receipt_id="synthetic-fill",
                    receipt_ts="2026-10-30T13:31:00Z",
                    orders=[
                        dict(
                            order_id=o["order_id"],
                            confirmed_qty=o["planned_qty"],
                            gross_usd=str(
                                int(ox["raw_open_usd"][o["symbol"]]) * o["planned_qty"]
                            ),
                            fee_known=True,
                            status="filled",
                        )
                        for o in orders
                    ],
                )
                assert book.record_receipt(env["kernel"]["intent_id"], receipt)["ok"]
                assert book.record_receipt(env["kernel"]["intent_id"], receipt)["ok"]
            observed = {}
            for scenario, book in books.items():
                state = book.readout(
                    dict(marks, as_of="2026-10-30T21:00:00Z", prices=ox["raw_open_usd"])
                )["metrics"]
                observed[scenario] = dict(
                    inventory=state["inventory"],
                    event_count=state["event_count"],
                    execution_verified=state["execution_verified"],
                )
            assert observed["x1"]["inventory"] == observed["x2"]["inventory"]
            # Missing marks and unknown fills use the existing kernel's null and
            # reconciliation rules; no adapter overrides its cash/receipt logic.
            no_marks = books["x2"].readout(
                dict(marks, as_of="2026-10-30T21:00:00Z", prices={})
            )
            assert no_marks["metrics"]["nav"] is None
            return observed

        case(
            "intent.shadow15k_x2_control_x1_same_orders_and_idempotent_receipts",
            integration,
        )

    sources = {
        str(p.relative_to(Path(__file__).parents[1])): sha(p.read_bytes())
        for p in sorted(Path(__file__).parent.glob("*.py"))
    }
    sources.update({"dynamic_factor/" + k: v for k, v in dynamic_sources().items()})
    return dict(
        schema="llm_direct.harness/v1",
        status="PASS",
        cases_passed=len(cases),
        cases=cases,
        bindings=BINDINGS,
        fixture_sha256={
            p.name: sha(p.read_bytes()) for p in sorted(FIXTURES.iterdir())
        },
        source_files=sources,
        network_attempts=len(attempts),
        model_calls=0,
        strategy_backtests=0,
        forward_samples=0,
        authority_writes=0,
        runtime_consumable=False,
        certifiable=False,
        dependencies={"python": sys.version.split()[0], "external": []},
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            run(args.workdir),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
