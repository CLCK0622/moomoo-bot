"""Read-only arm/configuration projection over ONE verified event chain.

Legacy records without explicit arm/configuration/outcome reconciliation refuse
formal readout. Never infer tags, rewrite historical counts, or create authority.
"""

from __future__ import annotations

import json

from .contract import digest, is_sha, result, sha256

ARMS = {"EVO883_FACTOR", "EVO896_LLMCLI"}
SCHEMA = "arm_n.event/v1"
CONFIG_FIELDS = {"prompt_version", "model_snapshot", "parameters", "ruleset"}


def valid_arm(arm_tag):
    return isinstance(arm_tag, str) and arm_tag in ARMS


def configuration_id(config):
    if (
        not isinstance(config, dict)
        or set(config) != CONFIG_FIELDS
        or any(
            not isinstance(config[k], str) or not config[k]
            for k in ("prompt_version", "model_snapshot", "ruleset")
        )
        or not isinstance(config["parameters"], dict)
    ):
        raise ValueError("arm_n.configuration_invalid")
    # Unlike the legacy digest helper, reject nonfinite identity components.
    return sha256(
        json.dumps(
            config,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    )


def project(snapshot, arm_tag):
    reasons = []
    configs, evaluated, requests = {}, set(), {}
    known = True
    rows = snapshot.get("events")
    if not valid_arm(arm_tag):
        reasons.append("arm_n.arm_tag_missing_or_invalid")
    if not isinstance(rows, list):
        reasons.append("arm_n.verified_events_unavailable")
    try:
        for event in rows if isinstance(rows, list) else []:
            # AttemptLedger stores immutable payloads in its existing record seam;
            # AuthorityLedger can carry the exact same tagged event directly.
            if not isinstance(event, dict):
                raise ValueError("arm_n.event_invalid")
            e = event.get("payload") if event.get("event") == "record" else event
            if not isinstance(e, dict) or not valid_arm(e.get("arm_tag")):
                raise ValueError("arm_n.event_arm_tag_missing_or_invalid")
            if e.get("schema") != SCHEMA:
                raise ValueError("arm_n.legacy_configuration_mapping_required")
            key = (e["arm_tag"], e.get("configuration_id"))
            kind = e.get("kind")
            if kind == "configuration_reserved":
                if key[1] != configuration_id(e.get("configuration")) or key in configs:
                    raise ValueError("arm_n.configuration_identity_conflict")
                configs[key] = e["configuration"]
            elif kind in {"generation_request", "market_outcome_evaluated"}:
                if key not in configs:
                    raise ValueError("arm_n.configuration_not_prereserved")
                if not is_sha(e.get("evidence_sha256")):
                    raise ValueError("arm_n.evidence_required")
                if kind == "market_outcome_evaluated":
                    if not e.get("evaluation_id"):
                        raise ValueError("arm_n.outcome_identity_required")
                    evaluated.add(key)
                else:
                    rid = e.get("actual_request_id")
                    if (
                        not isinstance(rid, str)
                        or not rid
                        or rid in requests
                        or type(e.get("request_count_known")) is not bool
                    ):
                        raise ValueError("arm_n.request_identity_conflict_or_unknown")
                    requests[rid] = e
                    if e["arm_tag"] == arm_tag and not e["request_count_known"]:
                        known = False
            else:
                raise ValueError("arm_n.event_kind_or_reconciliation_missing")
    except (ValueError, TypeError, KeyError) as exc:
        reasons.append(str(exc))
    observed_config = sum(k[0] == arm_tag for k in evaluated) if not reasons else None
    observed_requests = (
        sum(e["arm_tag"] == arm_tag for e in requests.values()) if not reasons else None
    )
    if not known:
        reasons.append("arm_n.internal_request_count_unknown")
    # Current authority snapshots explicitly remain incomplete. Even a perfectly
    # tagged fixture cannot certify history by asserting a zero historical prior.
    complete = False
    return dict(
        schema="arm_n.projection/v1",
        arm_tag=arm_tag,
        observed_N_config=observed_config,
        observed_N_generation_requests=observed_requests if known else None,
        request_count_known=known and not reasons,
        rows=[
            dict(
                role="PRIMARY_GATE",
                basis="N_config_own_arm",
                observed_N=observed_config,
                complete_N=None,
            ),
            dict(
                role="SENSITIVITY",
                basis="N_generation_requests_own_arm",
                observed_N=observed_requests if known else None,
                complete_N=None,
            ),
        ],
        n_complete=complete,
        cumulative_n=None,
        cumulative_n_lower_bound=None,
        n_ledger_hash=snapshot.get("n_ledger_hash"),
        projection_sha256=digest(
            {
                "arm_tag": arm_tag,
                "source_chain": snapshot.get("n_ledger_hash"),
                "configs": observed_config,
                "requests": observed_requests,
                "reasons": reasons,
            }
        ),
        global_history=dict(
            legacy_count_readout=snapshot.get("cumulative_n_lower_bound"),
            recorded_N=snapshot.get("recorded_N"),
            n_high_water=snapshot.get("n_high_water"),
            authority_tip=snapshot.get("authority_tip"),
            authority_sequence=snapshot.get("authority_sequence"),
        ),
        reasons=reasons + ["arm_n.complete_history_acceptance_missing"],
        certifiable=False,
    )


def event(kind, arm_tag, config, **fields):
    """Pure event constructor; does NOT write the authoritative chain."""
    if not valid_arm(arm_tag):
        raise ValueError("arm_n.arm_tag_missing_or_invalid")
    cid = configuration_id(config)
    value = dict(
        schema=SCHEMA, kind=kind, arm_tag=arm_tag, configuration_id=cid, **fields
    )
    if kind == "configuration_reserved":
        value["configuration"] = config
    return value


def readout(ledger, arm_tag=None):
    """One verified read, no writes; global audit counts never enter the arm gate."""
    snapshot = ledger.safe_snapshot()
    arm = project(snapshot, arm_tag)
    return result(
        "arm_n_readout",
        {"arm_tag": arm_tag, "ledger": snapshot},
        metrics={
            "arm_n": arm,
            "N_rows": arm["rows"],
            "n_complete": arm["n_complete"],
            "cumulative_n": arm["cumulative_n"],
            "cumulative_n_lower_bound": arm["cumulative_n_lower_bound"],
            "n_ledger_hash": snapshot["n_ledger_hash"],
        },
        reasons=list(snapshot["reasons"]) + arm["reasons"],
        missing=["arm_configuration_history_acceptance"],
        artifacts={"ledger": snapshot},
        assumptions=[
            "Observed fixture counts do not certify complete history or runtime DSR/V.",
            "Legacy audit readout is retained separately; tags are never inferred.",
        ],
    )
