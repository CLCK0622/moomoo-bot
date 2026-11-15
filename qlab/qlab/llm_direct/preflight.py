"""Single-dispatch P0 wiring; the command line only prepares or verifies offline.

AuthorityPort and EvidencePort are deliberately unimplemented trust boundaries.
They are parameters, not local receipt issuers or self-attested CLI metadata.
No real dispatch is authorized by this change (EVO-1019 chief 01a1e008-4a74).
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re

from qlab.shadow15k.harness import fixture_fees
from qlab.shadow15k.ledger import timestamp

from . import archive as archive_module
from .archive import Archive
from .contract import ARM, FIXTURES, PROFILE_SHA, bindings, canonical, digest, sha
from .launcher import (
    DEFAULT_APPROVAL_SHA, DEFAULT_BINARY_SHA, DEFAULT_VERSION,
    BinaryBinding, LaunchRejected, SubprocessLauncher,
)
from .snapshot import build_decision
from .synthetic import payload

PURPOSE = "P0_subscription_preflight"
MODEL = "claude-sonnet-4-6"
AUTHORITY_CHAIN_ID = "37a3871d39df8a641f64d39b335338c0f1d66bb1e20ed9b6c4cf456a508f02cc"


@dataclass(frozen=True)
class Receipts:
    chief_dispatch_grant: bytes
    reservation: bytes
    append_readiness: bytes
    subscription_route: bytes
    usage_credits: bytes = b""

    def blobs(self):
        values = vars(self)
        if any(not isinstance(v, bytes) or not v for v in values.values()):
            raise ValueError("P0.missing_receipt")
        return values


class AuthorityPort:
    """Trusted adapter to the existing EVO-891 chain; never a new authority.

    Before dispatch, verify the chief's separate single-request grant, binary
    binding approval, existing non-metered subscription with this exact model,
    and this arm/configuration/purpose's reservation and append availability.
    Reject key/helper/cloud/extra-usage routes, credential copying, new login or
    new deployment. The adapter must not return True merely for a supplied JSON
    assertion. Return the normalized verified identity: chain_id, arm_tag,
    configuration_id, purpose and verified=True. This does not replace checking
    original signed/anchored evidence. No production implementation is included.
    Verify the exact config isolation binding/approval against the trusted
    approved record in the sealed context as well.
    """

    def verify_before_dispatch(self, context, receipts):
        return False

    def append_attempt(self, context, attempt):
        raise ValueError("P0.authority_adapter_unavailable")

    def verify_append(self, context, attempt, receipt):
        return False


@dataclass(frozen=True)
class Evidence:
    """Provider extraction supplied by a trusted, independently reviewed adapter.

    CLI init/model names and model-generated JSON alone cannot establish this.
    Complete means every actual request and effective input is accounted for.
    Multiple requests/repair/retry require further chief budget authorization;
    this implementation preserves their bytes and refuses to certify a count.
    """

    provider_model: str
    provider_request_id: str
    response: bytes
    effective_context: bytes
    managed_policy: bytes
    request_map: bytes
    request_count: object
    complete: bool
    fallback: bool


class EvidencePort:
    def extract(self, stdout, context):
        return None

    def implemented(self):
        return callable(self.extract) and type(self).extract is not EvidencePort.extract


def fixture_receipt(raw):
    """Inspect parsed schema values, including JSON-escaped and nested schemas."""
    schemas = []

    def object_pairs(pairs):
        schemas.extend(value for key, value in pairs if key == "schema")
        return dict(pairs)

    try:
        json.loads(raw, object_pairs_hook=object_pairs)
    except (ValueError, UnicodeError, TypeError):
        return False
    return "arm_n.fixture_receipt/v1" in schemas


def usage_projection(stdout):
    """Retain observed event values; absence never means overage is disabled.

    This is post-dispatch evidence only. It cannot satisfy the external usage
    credit proof gate. Keep every observation rather than erasing earlier events.
    """
    events = []

    def fields(node, index):
        if isinstance(node, dict):
            if any(key in node for key in ("overageEnabled", "errorCode")):
                events.append(dict(
                    event_index=index,
                    overageEnabled=node.get("overageEnabled", "unknown"),
                    errorCode=node.get("errorCode", "unknown"),
                    overageEnabled_present="overageEnabled" in node,
                    errorCode_present="errorCode" in node,
                ))
            for value in node.values():
                fields(value, index)
        elif isinstance(node, list):
            for value in node:
                fields(value, index)

    for index, line in enumerate(stdout.splitlines()):
        try:
            event = json.loads(line)
        except (ValueError, UnicodeError):
            continue
        previous = len(events)
        fields(event, index)
        if isinstance(event, dict) and event.get("type") == "rate_limit_event" and len(events) == previous:
            events.append(dict(
                event_index=index, overageEnabled="unknown", errorCode="unknown",
                overageEnabled_present=False, errorCode_present=False,
            ))
    latest = events[-1] if events else dict(
        overageEnabled="unknown", errorCode="unknown",
        overageEnabled_present=False, errorCode_present=False,
    )
    return dict(
        overageEnabled=latest["overageEnabled"], errorCode=latest["errorCode"],
        overageEnabled_present=latest["overageEnabled_present"],
        errorCode_present=latest["errorCode_present"], usage_events=events,
    )


def _require_archive(archive):
    if archive.mode not in {"p0_subscription_preflight", "p0_offline_test"}:
        raise ValueError("P0.distinct_archive_identity_required")


def prepare(archive, binding, run_id, *, launcher=None):
    _require_archive(archive)
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", run_id):
        raise ValueError("P0.invalid_run_id")
    main = bindings()
    decision = build_decision(payload(fixture_fees("x2")))
    prompt = (FIXTURES / "EVO896-prompt-v0.1.2.txt").read_bytes()
    schema = (FIXTURES / "EVO896-output-schema-v0.1.2.json").read_bytes()
    input_bytes = canonical(decision)
    launcher = launcher if launcher is not None else SubprocessLauncher(binding)
    if launcher.binding != binding:
        raise ValueError("P0.launcher_binding_mismatch")
    transport = launcher.plan(prompt, schema)
    configuration = dict(
        prompt_version=main["prompt"]["sha256"], model_snapshot=MODEL,
        parameters={"effort": "high"}, ruleset=PROFILE_SHA,
    )
    context = dict(
        schema="llm_direct.p0.context/v1", arm_tag=ARM, purpose=PURPOSE,
        run_id_sha256=sha(run_id.encode()), configuration_id=digest(configuration),
        configuration_tuple_sha256=digest(configuration),
        model_binding_sha256=digest(main["model_binding"]),
        binary_binding=binding.manifest(), prompt_sha256=sha(prompt),
        launch_plan_sha256=digest(transport),
        config_isolation_binding=transport["config_isolation_binding"],
        schema_sha256=sha(schema), input_sha256=sha(input_bytes),
        aggregation_rule_sha256=digest(dict(max_dispatches=1, market_outcomes=False)),
        authority_chain="EVO-891", authority_chain_id=AUTHORITY_CHAIN_ID,
        N_config_delta=0,
        market_outcome_evaluation_id_or_null=None,
    )
    plan = dict(
        kind="p0_plan", context=context,
        transport=transport,
        blob_sha256s=[archive.put(b) for b in (prompt, schema, input_bytes)],
    )
    archive.append("p0:plan", plan)
    return context, prompt, schema, input_bytes


def _validate_evidence(evidence, context):
    if not isinstance(evidence, Evidence):
        return False
    expected_context = dict(
        system_prompt_sha256=context["prompt_sha256"],
        user_input_sha256=context["input_sha256"],
        output_schema_sha256=context["schema_sha256"], tools=[], mcp_servers={},
        managed_policy_sha256=sha(evidence.managed_policy),
    )
    expected_map = [dict(
        provider_model=MODEL, provider_request_id=evidence.provider_request_id,
        response_sha256=sha(evidence.response), retry_of=None,
    )]
    return (
        evidence.complete is True and evidence.fallback is False
        and type(evidence.request_count) is int and evidence.request_count == 1
        and evidence.provider_model == MODEL
        and isinstance(evidence.provider_request_id, str)
        and evidence.provider_request_id not in {"", "unknown"}
        and evidence.effective_context == canonical(expected_context)
        and evidence.request_map == canonical(expected_map)
    )


def run_preflight(
    archive, binding, run_id, *, receipts=None, authority=None, evidence_port=None,
    launcher=None, start, end_clock,
):
    """One dispatch at most, only through separately supplied trusted ports.

    No CLI flag activates this API. The later real-request release must supply
    reviewed authority/authentication/provider extraction adapters. Offline tests
    use p0_offline_test and fake subprocesses; their evidence is never P0 proof.
    """
    launcher = launcher if launcher is not None else SubprocessLauncher(binding)
    context, prompt, schema, input_bytes = prepare(
        archive, binding, run_id, launcher=launcher,
    )

    def gate(allowed, reason):
        archive.append("p0:gate", dict(
            kind="p0_dispatch_gate", allowed=allowed, reason=reason,
            context_sha256=digest(context), blob_sha256s=[],
        ))
        if not allowed:
            raise ValueError("P0." + reason)

    if not isinstance(receipts, Receipts) or not isinstance(authority, AuthorityPort):
        gate(False, "separate_dispatch_grant_and_authority_required")
    try:
        receipts.blobs()
    except ValueError:
        gate(False, "required_proof_missing_including_usage_credits")
    if any(fixture_receipt(raw) for raw in receipts.blobs().values()):
        gate(False, "fixture_receipt_not_authoritative")
    try:
        identity = authority.verify_before_dispatch(json.loads(canonical(context)), receipts)
        verified = identity == dict(
            chain_id=AUTHORITY_CHAIN_ID, arm_tag=ARM,
            configuration_id=context["configuration_id"], purpose=PURPOSE, verified=True,
        )
    except Exception:
        verified = False
    if not verified:
        gate(False, "dispatch_receipts_or_subscription_unverified")
    timestamp(start)
    if not isinstance(evidence_port, EvidencePort) or not evidence_port.implemented():
        gate(False, "provider_extraction_adapter_required")
    if launcher.config_dir is None:
        gate(False, "config_location_not_selected")
    gate(True, "external_receipts_verified")

    def unused(events):
        if any(e["body"]["kind"] == "p0_dispatch" for e in events):
            raise ValueError("P0.dispatch_already_claimed_no_automatic_retry")

    receipt_shas = {k: archive.put(v) for k, v in receipts.blobs().items()}
    claim = dict(
        kind="p0_dispatch", context_sha256=digest(context), start_utc=start,
        receipt_sha256s=receipt_shas, blob_sha256s=list(receipt_shas.values()),
    )
    # A unique claim and guard share one SQLite transaction. Crash/unknown never
    # permits a second invocation, even after restarting this Python process.
    archive.append("p0:dispatch", claim, validate=unused, require_new=True)
    stdout, stderr, result, evidence, error = b"", b"", None, None, None
    launch_rejection = None
    try:
        result = launcher.launch(
            prompt=prompt, schema=schema, input_bytes=input_bytes,
            workdir=archive.anchor / (run_id + "-work"),
            authorize=lambda plan_sha: verified and plan_sha == context["launch_plan_sha256"],
        )
        stdout, stderr = result.stdout, result.stderr
        evidence = evidence_port.extract(stdout, json.loads(canonical(context)))
    except LaunchRejected as exc:
        error, launch_rejection = "LaunchRejected", exc.code
    except Exception as exc:
        # Exception strings can contain account IDs, filenames or credentials.
        error = type(exc).__name__
    end = end_clock()
    timestamp(end)
    if timestamp(end) < timestamp(start):
        error = "ClockReversed"
    known = False
    try:
        known = _validate_evidence(evidence, context)
    except (TypeError, ValueError):
        pass
    binary_ok = result is not None and (
        result.binary_before_sha256 == result.binary_after_sha256 == binding.binary_sha256
        and result.cli_version_before == result.cli_version_after == binding.version
    )
    completed = result is not None and result.returncode == 0 and not result.timed_out
    evidence_blobs = {}
    if isinstance(evidence, Evidence):
        for key in ("response", "effective_context", "managed_policy", "request_map"):
            raw = getattr(evidence, key)
            if isinstance(raw, bytes):
                evidence_blobs[key] = archive.put(raw)
    # stderr is entirely redacted, rather than relying on a token/email regex.
    # Its original digest is local evidence, not content uploaded to the issue.
    stderr_redacted = canonical(dict(
        redaction="entire_stream", original_sha256=sha(stderr), byte_count=len(stderr)
    ))
    raw_sha = archive.put(stdout)
    stderr_sha = archive.put(stderr_redacted)
    attempt = dict(
        kind="p0_attempt", arm_version=bindings()["arm_version"], arm_tag=ARM,
        attempt_id=digest(context), cli_invocation_id=digest(claim),
        provider_request_id_or_unknown=(
            evidence.provider_request_id if known else "unknown"
        ), retry_of=None, purpose=PURPOSE, start_utc=start, end_utc=end,
        model_binding_sha256=context["model_binding_sha256"],
        prompt_sha256=context["prompt_sha256"], input_sha256=context["input_sha256"],
        raw_output_sha256=raw_sha, stderr_redacted_sha256=stderr_sha,
        status="recorded" if completed and binary_ok and known and error is None else "unverified",
        request_count_known=known, N_config_delta=0, N_request_delta=1 if known else None,
        authority_chain_receipt=receipt_shas["reservation"],
        configuration_id=context["configuration_id"],
        configuration_tuple_sha256=context["configuration_tuple_sha256"],
        market_outcome_evaluation_id_or_null=None,
        preopen_all_generations_manifest_sha256=None,
        aggregation_rule_sha256=context["aggregation_rule_sha256"],
        binary_verified=binary_ok, completed=completed,
        evidence_sha256s=evidence_blobs, error_kind=error,
        launch_rejection=launch_rejection,
        **usage_projection(stdout),
        requires_extended_audit=(not known),
        blob_sha256s=[raw_sha, stderr_sha] + list(evidence_blobs.values()),
    )
    archive.append("p0:attempt", attempt)
    # Unknown/failure requests still go to the single existing authority chain.
    # Failure to append is itself durable and never licenses another request.
    settlement = None
    try:
        receipt = authority.append_attempt(
            json.loads(canonical(context)), json.loads(canonical(attempt)),
        )
        if isinstance(receipt, bytes) and receipt:
            receipt_sha = archive.put(receipt)
            if (
                not fixture_receipt(receipt)
                and authority.verify_append(
                    json.loads(canonical(context)), json.loads(canonical(attempt)), receipt,
                ) is True
            ):
                settlement = receipt_sha
            archive.append("p0:append", dict(
                kind="p0_append_receipt", verified=settlement is not None,
                receipt_sha256=receipt_sha, blob_sha256s=[receipt_sha],
            ))
    except Exception:
        pass
    archive.append("p0:terminal", dict(
        kind="p0_terminal", append_verified=settlement is not None,
        attempt_sha256=digest(attempt), blob_sha256s=[],
    ))
    return manifest(archive)


def manifest(archive, *, expected_tip=None):
    """Public hashes/checks/usage fields; no raw streams, identifiers or paths."""
    _require_archive(archive)
    events = archive.events()
    tip = digest(events[-1]) if events else digest(archive.identity)
    if expected_tip is not None and expected_tip != tip:
        raise ValueError("P0.external_anchor_mismatch")
    kinds = {e["body"]["kind"]: e["body"] for e in events}
    attempt, terminal = kinds.get("p0_attempt"), kinds.get("p0_terminal")
    claim = kinds.get("p0_dispatch")
    checks = dict(
        dispatch_gate_verified=bool(kinds.get("p0_dispatch_gate", {}).get("allowed")),
        dispatch_recorded=claim is not None,
        terminal_recorded=terminal is not None,
        binary_verified=bool(attempt and attempt["binary_verified"]),
        execution_completed=bool(attempt and attempt["completed"]),
        provider_context_and_requests_verified=bool(attempt and attempt["request_count_known"]),
        authority_append_verified=bool(terminal and terminal["append_verified"]),
    )
    status = "VERSION_UNVERIFIED"
    if claim and not terminal:
        status = "INCOMPLETE_DISPATCH"
    elif not claim:
        status = "OFFLINE_PREPARED"
    return dict(
        schema="llm_direct.p0.manifest/v1", stage="P0", mode=archive.mode,
        status=status, checks=checks, archive_tip_sha256=tip,
        dispatch_gate_reason=kinds.get("p0_dispatch_gate", {}).get("reason", "not_authorized"),
        authority_receipt_status=(
            "已核验" if archive.mode == "p0_subscription_preflight"
            and checks["dispatch_gate_verified"] and checks["authority_append_verified"]
            else "回执不可用"
        ),
        argv_is_tested=False,
        launch_rejection=attempt.get("launch_rejection") if attempt else None,
        **{key: (attempt.get(key, default) if attempt else default) for key, default in dict(
            overageEnabled="unknown", errorCode="unknown",
            overageEnabled_present=False, errorCode_present=False, usage_events=[],
        ).items()},
        blob_sha256s=sorted({h for e in events for h in e["body"].get("blob_sha256s", [])}),
        N_config_delta=0, N_request_delta=attempt["N_request_delta"] if attempt else None,
        requires_extended_audit=bool(
            (claim and not terminal) or (attempt and attempt["requires_extended_audit"])
        ),
        real_dispatch_authorized_by_this_change=False,
        runtime_consumable=False, certifiable=False, G09_N_passed=False,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--expected-tip")
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--binary-root", type=Path)
    parser.add_argument("--config-dir", type=Path)
    parser.add_argument("--cli-version", default=DEFAULT_VERSION)
    parser.add_argument("--binary-sha256", default=DEFAULT_BINARY_SHA)
    parser.add_argument("--binding-approval-sha256", default=DEFAULT_APPROVAL_SHA)
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", args.run_id):
        parser.error("invalid run ID")
    try:
        root = archive_module.PREFLIGHT_ROOT / args.run_id
        if args.verify:
            archive = Archive(root, mode="p0_subscription_preflight", readonly=True)
        else:
            values = (args.binary, args.binary_root, args.cli_version,
                      args.binary_sha256, args.binding_approval_sha256)
            if any(v is None for v in values):
                parser.error("prepare requires all five binary binding parameters")
            binding = BinaryBinding(*values)
            archive = Archive(root, mode="p0_subscription_preflight")
            prepare(archive, binding, args.run_id, launcher=SubprocessLauncher(
                binding, config_dir=args.config_dir,
            ))
        print(json.dumps(manifest(archive, expected_tip=args.expected_tip), sort_keys=True))
        return 0
    except (OSError, ValueError) as exc:
        # A safe, fixed error category only. Never print a raw path or stream.
        print(json.dumps(dict(error_kind=type(exc).__name__, status="VERSION_UNVERIFIED")))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
