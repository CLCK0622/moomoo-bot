"""Synthetic lifecycle, pre-open evidence and final-decision stability gate."""

from __future__ import annotations

from itertools import combinations
from copy import deepcopy
from decimal import Decimal

from qlab.dynamic_factor.contract import is_sha
from qlab.shadow15k.ledger import timestamp
from qlab.shadow15k.fees import decimal_arithmetic

from .adapter import adapt
from .contract import (
    ARM,
    FIXTURES,
    PROFILE_SHA,
    VERSION,
    bindings,
    canonical,
    digest,
    sha,
    strict_json,
)
from .snapshot import verify_decision
from .lifecycle import Lifecycle


def live(events):
    if any(e["body"]["kind"] == "terminate" for e in events):
        raise ValueError("runtime.version_terminated_new_version_registration_required")


class Runtime:
    """Records supplied synthetic responses. There is deliberately no launcher."""

    def __init__(self, archive):
        self.archive = archive
        self.lifecycle = Lifecycle(archive)

    def freeze(self, *, at, configuration, aggregation):
        live(self.archive.events())
        main = bindings()
        timestamp(at)
        if (
            set(configuration)
            != {"prompt_version", "model_snapshot", "parameters", "ruleset"}
            or configuration["prompt_version"] != main["prompt"]["sha256"]
            or configuration["model_snapshot"]
            != main["model_binding"]["model_canonical_id"]
            or configuration["ruleset"] != PROFILE_SHA
            or configuration["parameters"]
            != {"effort": main["model_binding"]["effort"]}
        ):
            raise ValueError("runtime.configuration_mismatch")
        if aggregation != {
            "canonical_index": 1,
            "entry_repetitions": 30,
            "monitor_repetitions": 5,
            "max_signature_mismatches": 0,
        }:
            raise ValueError("runtime.aggregation_mismatch")
        body = dict(
            kind="freeze",
            arm_tag=ARM,
            arm_version=VERSION,
            at=at,
            configuration=configuration,
            configuration_id=digest(configuration),
            aggregation=aggregation,
            aggregation_rule_sha256=digest(aggregation),
            profile_sha256=PROFILE_SHA,
        )
        self.lifecycle.bind(body["configuration_id"], at)
        self.archive.append("freeze", body, validate=live)
        return body

    def _freeze(self):
        self.lifecycle.require_active()
        events = self.archive.events()
        live(events)
        frozen = next((e["body"] for e in events if e["id"] == "freeze"), None)
        if frozen is None:
            raise ValueError("runtime.aggregation_not_frozen")
        return frozen

    def terminate(self, reason, at):
        timestamp(at)
        self.lifecycle.terminate(reason, at)
        return self.archive.append(
            "termination",
            dict(
                kind="terminate",
                reason=reason,
                at=at,
                clause="A3.RT1",
                arm_version=VERSION,
            ),
        )

    def model_available(self, available, at):
        self._freeze()
        if available is not True:
            self.terminate("pinned_snapshot_unavailable", at)
            raise ValueError("runtime.pinned_snapshot_unavailable")

    def freeze_entry_sessions(
        self, sessions, *, calendar_sessions, calendar_sha256, at
    ):
        self._freeze()
        if (
            len(sessions) != 10
            or sessions != sorted(set(sessions))
            or not is_sha(calendar_sha256)
            or calendar_sessions != sorted(set(calendar_sessions))
            or digest(calendar_sessions) != calendar_sha256
            or calendar_sessions[:10] != sessions
            or timestamp(at).date().isoformat() >= sessions[0]
        ):
            raise ValueError("R1.first_ten_sessions_must_be_frozen_before_sampling")

        def validate(events):
            live(events)
            if any(e["body"]["kind"] == "generation" for e in events):
                raise ValueError("R1.entry_schedule_after_generation")

        return self.archive.append(
            "entry:schedule",
            dict(
                kind="entry_schedule",
                sessions=sessions,
                calendar_sha256=calendar_sha256,
                calendar_sessions=calendar_sessions,
                at=at,
            ),
            validate=validate,
        )

    def entry_summary(self):
        self._freeze()
        events = self.archive.events()
        schedule = next(
            (e["body"] for e in events if e["id"] == "entry:schedule"), None
        )
        sealed = [
            e["body"]
            for e in events
            if e["body"]["kind"] == "group_seal" and e["body"]["entry"]
        ]
        if schedule is None or len(sealed) != 10:
            return dict(
                passed=False,
                status="INCOMPLETE_ENTRY_CAMPAIGN",
                required_groups=10,
                required_generations=300,
                observed_groups=len(sealed),
                certifiable=False,
            )
        sessions = []
        for g in sealed:
            rows = [
                e["body"]
                for e in events
                if e["body"]["kind"] == "generation"
                and e["body"]["group_id"] == g["group_id"]
            ]
            if len(rows) != 30:
                raise ValueError("R1.entry_group_not_thirty")
            first = next(r for r in rows if r["index"] == 1)
            sessions.append(
                strict_json(self.archive.get(first["decision_sha256"]))[
                    "decision_session"
                ]
            )
            comparison = next(
                (e["body"] for e in events if e["id"] == "comparison:" + g["group_id"]),
                None,
            )
            if (
                comparison is None
                or not strict_json(self.archive.get(comparison["report_sha256"]))[
                    "passed"
                ]
            ):
                raise ValueError("R1.entry_comparison_missing_or_failed")
        if sessions != schedule["sessions"]:
            raise ValueError("R1.first_ten_session_order_mismatch")
        return dict(
            passed=True,
            status="SYNTHETIC_ENTRY_PROTOCOL_PASS",
            groups=10,
            generations=300,
            certifiable=False,
            runtime_consumable=False,
        )

    def record_generation(
        self,
        *,
        attempt_id,
        group_id,
        index,
        decision,
        raw,
        metadata,
        start,
        end,
        reference_open_utc,
    ):
        f = self._freeze()
        verify_decision(decision)
        if type(index) is not int or index < 1 or not attempt_id or not group_id:
            raise ValueError("log.identity_invalid")
        if timestamp(start) < timestamp(f["at"]) or timestamp(end) < timestamp(start):
            raise ValueError("log.before_freeze_or_time_reversed")
        # Preserve raw invalid/late/failure outputs. These can never be replaced.
        raw_sha = self.archive.put(raw)
        decision_sha = self.archive.put(canonical(decision))
        meta_sha = self.archive.put(canonical(metadata))
        prompt_sha = self.archive.put(
            (FIXTURES / "EVO896-prompt-v0.1.2.txt").read_bytes()
        )
        schema_sha = self.archive.put(
            (FIXTURES / "EVO896-output-schema-v0.1.2.json").read_bytes()
        )
        b = bindings()["model_binding"]
        required = {
            "provider_model",
            "cli_version",
            "binary_before_sha256",
            "binary_after_sha256",
            "context_sha256",
            "tools",
            "subscription_route",
            "fallback",
            "request_count_known",
            "provider_request_id_or_unknown",
            "cli_invocation_id",
            "retry_of",
            "purpose",
            "status",
            "authority_chain_receipt",
            "stderr_redacted_sha256",
            "visible_events_sha256",
        }
        valid = (
            set(metadata) == required
            and metadata["provider_model"] == b["model_canonical_id"]
            and metadata["cli_version"] == b["cli_exact_version"]
            and metadata["binary_before_sha256"]
            == metadata["binary_after_sha256"]
            == b["cli_binary_sha256"]
            and metadata["tools"] == []
            and metadata["subscription_route"] == "existing_subscription"
            and metadata["fallback"] is False
            and metadata["request_count_known"] is True
            and metadata["status"] == "success"
            and isinstance(metadata["cli_invocation_id"], str)
            and bool(metadata["cli_invocation_id"])
            and isinstance(metadata["provider_request_id_or_unknown"], str)
            and metadata["provider_request_id_or_unknown"] not in {"", "unknown"}
            and all(
                is_sha(metadata[k])
                for k in (
                    "context_sha256",
                    "authority_chain_receipt",
                    "stderr_redacted_sha256",
                    "visible_events_sha256",
                )
            )
        )
        # The hashes reference retained bytes, not unobservable asserted context.
        if valid:
            try:
                for k in (
                    "context_sha256",
                    "stderr_redacted_sha256",
                    "visible_events_sha256",
                ):
                    self.archive.get(metadata[k])
                context = strict_json(self.archive.get(metadata["context_sha256"]))
                stream = strict_json(
                    self.archive.get(metadata["visible_events_sha256"])
                )
                receipt = strict_json(
                    self.archive.get(metadata["authority_chain_receipt"])
                )
                valid = (
                    context
                    == dict(
                        system_prompt_sha256=prompt_sha,
                        user_input_sha256=decision_sha,
                        output_schema_sha256=schema_sha,
                        tools=[],
                    )
                    and stream
                    == dict(
                        provider_model=b["model_canonical_id"],
                        provider_request_id=metadata["provider_request_id_or_unknown"],
                        raw_response_sha256=raw_sha,
                        status="success",
                    )
                    and receipt.get("arm_tag") == ARM
                    and receipt.get("configuration_id") == f["configuration_id"]
                    and receipt.get("pre_reserved") is True
                )
            except (OSError, ValueError, KeyError, TypeError):
                valid = False
        body = dict(
            kind="generation",
            arm_tag=ARM,
            arm_version=VERSION,
            attempt_id=attempt_id,
            group_id=group_id,
            index=index,
            start=start,
            end=end,
            reference_open_utc=reference_open_utc,
            input_sha256=decision["input_sha256"],
            raw_output_sha256=raw_sha,
            decision_sha256=decision_sha,
            metadata=metadata,
            valid=valid,
            preopen=timestamp(end) < timestamp(reference_open_utc),
            configuration_id=f["configuration_id"],
            aggregation_rule_sha256=f["aggregation_rule_sha256"],
            prompt_sha256=prompt_sha,
            model_binding_sha256=digest(bindings()["model_binding"]),
            configuration_tuple_sha256=f["configuration_id"],
            N_config_delta=0,
            N_request_delta=1 if metadata.get("request_count_known") is True else None,
            market_outcome_evaluation_id_or_null=None,
            blob_sha256s=[raw_sha, decision_sha, meta_sha, prompt_sha, schema_sha]
            + [
                metadata[k]
                for k in (
                    "context_sha256",
                    "stderr_redacted_sha256",
                    "visible_events_sha256",
                    "authority_chain_receipt",
                )
                if is_sha(metadata.get(k))
                and (self.archive.blobs / metadata[k]).is_file()
            ],
        )

        def validate(events):
            live(events)
            if any(
                e["body"].get("kind") == "generation"
                and (
                    e["body"]["metadata"].get("cli_invocation_id")
                    == metadata.get("cli_invocation_id")
                    or e["body"]["metadata"].get("provider_request_id_or_unknown")
                    == metadata.get("provider_request_id_or_unknown")
                )
                for e in events
            ):
                raise ValueError("log.fresh_session_or_request_reused")
            if any(
                e["body"].get("kind") == "group_seal"
                and e["body"]["group_id"] == group_id
                for e in events
            ):
                raise ValueError("log.group_already_sealed")
            if any(
                e["body"].get("kind") == "generation"
                and e["body"]["group_id"] == group_id
                and e["body"]["index"] == index
                for e in events
            ):
                raise ValueError("log.index_already_recorded")

        self.archive.append("generation:" + attempt_id, body, validate=validate)
        if not body["preopen"]:
            self.terminate("R1.preopen_deadline_failed", end)
        elif not valid:
            self.terminate("model_binding_or_visibility_unverified", end)
        return body

    def seal_group(self, group_id, *, at, entry):
        self._freeze()
        timestamp(at)
        if type(entry) is not bool:
            raise ValueError("log.entry_flag_required")

        def validate(events):
            live(events)
            rows = [
                e["body"]
                for e in events
                if e["body"].get("kind") == "generation"
                and e["body"]["group_id"] == group_id
            ]
            if not rows or any(
                timestamp(r["end"]) > timestamp(at)
                or timestamp(at) >= timestamp(r["reference_open_utc"])
                for r in rows
            ):
                raise ValueError("log.seal_not_preopen")
            if digest(rows) != body["generations_sha256"]:
                raise ValueError("log.concurrent_generation_changed")

        rows = [
            e["body"]
            for e in self.archive.events()
            if e["body"].get("kind") == "generation"
            and e["body"]["group_id"] == group_id
        ]
        body = dict(
            kind="group_seal",
            group_id=group_id,
            at=at,
            entry=entry,
            generations_sha256=digest(rows),
            manifest_sha256=digest(
                {str(r["index"]): r["raw_output_sha256"] for r in rows}
            ),
        )
        return self.archive.append("seal:" + group_id, body, validate=validate)

    def replay(self, group_id, decision, execution, fees, *, at):
        frozen = self._freeze()
        if execution is None:
            return dict(
                status="PENDING_EXECUTION_INPUT",
                passed=False,
                canonical_index=1,
                runtime_consumable=False,
            )
        # Capture the caller's mutable objects once for the whole group.
        decision, execution = deepcopy((decision, execution))
        events = self.archive.events()
        sealed = next(
            (e["body"] for e in events if e["id"] == "seal:" + group_id), None
        )
        if sealed is None:
            raise ValueError("log.preopen_manifest_missing")
        rows = sorted(
            [
                e["body"]
                for e in events
                if e["body"].get("kind") == "generation"
                and e["body"]["group_id"] == group_id
            ],
            key=lambda r: r["index"],
        )
        if timestamp(at) < timestamp(execution["reference_open_utc"]):
            raise ValueError("runtime.execution_replay_before_open")
        expected = frozen["aggregation"][
            "entry_repetitions" if sealed["entry"] else "monitor_repetitions"
        ]
        reasons, results, validations = [], [], []
        state = decision["x2_control_state"]
        if sealed["entry"] and (
            Decimal(state["nav_usd"]) != 15000
            or any(state["inventory_qty"][s] for s in decision["asset_order"][:-1])
            or state["inventory_qty"]["QQQ"]
            != int(Decimal("12000") / Decimal(decision["raw_prices_close"]["QQQ"]))
            or decision["policy_state"]["global_position"] != 5
        ):
            reasons.append("R1.entry_state_not_frozen_diagnostic")
        if len(rows) != expected or [r["index"] for r in rows] != list(
            range(1, expected + 1)
        ):
            reasons.append("R1.incomplete_repetitions")
        for row in rows:
            try:
                if (
                    not row["valid"]
                    or not row["preopen"]
                    or row["reference_open_utc"] != execution["reference_open_utc"]
                    or row["input_sha256"] != decision["input_sha256"]
                    or row["decision_sha256"] != sha(canonical(decision))
                ):
                    raise ValueError("R1.generation_identity_or_time_failure")
                result = adapt(
                    self.archive.get(row["raw_output_sha256"]),
                    decision,
                    execution,
                    fees,
                )
                results.append(result)
                validations.append(
                    dict(
                        index=row["index"],
                        attempt_id=row["attempt_id"],
                        raw_output_sha256=row["raw_output_sha256"],
                        valid=True,
                        reasons=[],
                    )
                )
            except (ValueError, KeyError, TypeError) as exc:
                reasons.append(str(exc))
                validations.append(
                    dict(
                        index=row["index"],
                        attempt_id=row["attempt_id"],
                        raw_output_sha256=row["raw_output_sha256"],
                        valid=False,
                        reasons=[str(exc)],
                    )
                )
        mismatches = dict(
            approval_bit=0, final_holdings65=0, sorted_economic_net_orders=0
        )
        overlap_failures = 0
        for a, b in combinations(results, 2):
            for k in mismatches:
                mismatches[k] += a["signature"][k] != b["signature"][k]
            if not original_metrics(a, b, decision):
                overlap_failures += 1
        if any(mismatches.values()):
            reasons.append("R1.final_decision_disagreement")
        if overlap_failures:
            reasons.append("R1.original_overlap_metrics_failed")
        if sealed["entry"]:
            for r in results:
                raw_target = {
                    s["symbol"]: s["target_qty"] for s in r["output"]["targets"]
                }
                if not nontrivial(raw_target, decision) or not nontrivial(
                    r["final"], decision, prices=execution["raw_open_usd"]
                ):
                    reasons.append("R1.entry_nontriviality_failed")
        report = dict(
            status="PASS" if not reasons else "FAIL",
            passed=not reasons,
            reasons=sorted(set(reasons)),
            canonical_index=1,
            canonical_raw_output_sha256=rows[0]["raw_output_sha256"] if rows else None,
            results=results,
            attempt_validation=validations,
            pairwise_mismatches=mismatches,
            pairwise_comparisons=len(results) * (len(results) - 1) // 2,
            original_metric_failures=overlap_failures,
            preopen_manifest_sha256=sealed["manifest_sha256"],
            execution_snapshot_sha256=digest(execution),
            runtime_consumable=False,
            certifiable=False,
        )
        h = self.archive.put(canonical(report))
        self.archive.append(
            "comparison:" + group_id,
            dict(
                kind="comparison", group_id=group_id, report_sha256=h, blob_sha256s=[h]
            ),
            validate=live,
        )
        if reasons:
            self.terminate("R1.final_decision_gate_failed", at)
        return report


@decimal_arithmetic
def nontrivial(q, decision, *, prices=None):
    if not q:
        return False
    prices = decision["raw_prices_close"] if prices is None else prices
    value = sum(
        Decimal(prices[s]) * q[s] for s in decision["asset_order"][:-1]
    ) / Decimal(decision["x2_control_state"]["nav_usd"])
    return sum(q[s] > 0 for s in decision["asset_order"][:-1]) >= 3 and Decimal(
        "0.12"
    ) <= value <= Decimal("0.20")


@decimal_arithmetic
def original_metrics(a, b, d):
    q = [{r["symbol"]: r["target_qty"] for r in x["output"]["targets"]} for x in (a, b)]
    if not q[0] or not q[1]:
        return q[0] == q[1]
    sets = [{s for s in d["asset_order"][:-1] if p[s]} for p in q]
    union = sets[0] | sets[1]
    j = Decimal(len(sets[0] & sets[1])) / len(union) if union else Decimal(1)
    values = [
        {s: Decimal(d["raw_prices_close"][s]) * p[s] for s in d["asset_order"][:-1]}
        for p in q
    ]
    totals = [sum(v.values()) for v in values]
    overlap = (
        sum(min(values[0][s] / totals[0], values[1][s] / totals[1]) for s in union)
        if all(totals)
        else Decimal(int(not any(totals)))
    )
    nav = Decimal(d["x2_control_state"]["nav_usd"])
    base_diff = (
        abs(q[0]["QQQ"] - q[1]["QQQ"]) * Decimal(d["raw_prices_close"]["QQQ"]) / nav
    )
    cash_diff = (
        abs(
            (totals[0] + q[0]["QQQ"] * Decimal(d["raw_prices_close"]["QQQ"]))
            - (totals[1] + q[1]["QQQ"] * Decimal(d["raw_prices_close"]["QQQ"]))
        )
        / nav
    )
    return (
        j >= Decimal("0.90")
        and overlap >= Decimal("0.95")
        and base_diff <= Decimal("0.01")
        and cash_diff <= Decimal("0.01")
    )
