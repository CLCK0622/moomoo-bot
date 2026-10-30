"""Pinned preregistration and injectable DSR interface; no inferred formula/V."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .contract import digest, is_sha, result, unavailable
from .arm_n import MISSING, label, readout, valid_arm


def prereg_check(prereg, expected_sha256, *, conventions=None):
    if conventions is not None:
        reasons = [
            "prereg_runtime_bindings_pending"
            if conventions.document.get("strategy_frozen")
            else "prereg_draft_not_frozen"
        ]
        if prereg is not None and prereg != conventions.document:
            reasons.append("prereg_payload_mismatch")
        if expected_sha256 is not None and expected_sha256 != conventions.raw_sha256:
            reasons.append("prereg_hash_mismatch")
        return conventions.bind(
            result(
                "prereg_check",
                {"prereg": prereg, **conventions.binding},
                reasons=reasons,
                metrics={"prereg_sha256": conventions.raw_sha256},
            )
        )
    reasons, missing = [], []
    if prereg is None:
        reasons.append("prereg_missing")
        missing.append("prereg")
    elif not isinstance(prereg, dict) or not isinstance(prereg.get("dsr", {}), dict):
        reasons.append("prereg_invalid")
    else:
        for key in (
            "version",
            "dsr",
            "fold_policy",
            "fee_params_sha256",
            "ledger_policy",
        ):
            if not prereg.get(key):
                missing.append(key)
        if missing:
            reasons.append("prereg_incomplete")
        if not is_sha(expected_sha256) or digest(prereg) != expected_sha256:
            reasons.append("prereg_hash_mismatch")
        dsr = prereg.get("dsr", {})
        if not all(
            dsr.get(k) for k in ("formula_id", "variance_method", "sharpe_scale")
        ):
            reasons.append("prereg_formula_or_variance_missing")
    return result(
        "prereg_check",
        {"prereg": prereg, "expected_sha256": expected_sha256},
        reasons=reasons,
        missing=missing,
        metrics={"prereg_sha256": None if prereg is None else digest(prereg)},
        assumptions=[
            "Mechanical adapter schema only; EVO-883 authors supply the statistical policy.",
            "Prereg SHA is canonical JSON SHA; retain the raw attachment SHA separately.",
        ],
    )


@dataclass(frozen=True)
class DSRPlugin:
    """Trusted, reviewed code only. evaluate(request, full_ledger, prereg) -> dict."""

    formula_id: str
    prereg_sha256: str
    source_sha256: str
    evaluate: Callable


def _diagnostic_dsr(
    request, ledger, *, prereg=None, prereg_sha256=None, plugin=None, conventions=None
):
    """All public paths refuse runtime DSR/V, including the legacy plugin seam."""
    snapshot = ledger.safe_snapshot()
    # Only future complete synthetic/readied snapshots need this clamp. Frozen
    # diagnostics keep exact fields and order, including historical lower bounds.
    if snapshot.get("n_complete") or snapshot["cumulative_n"] is not None:
        snapshot = dict(
            snapshot, cumulative_n=None, n_complete=False, certifiable=False
        )
    reasons = list(snapshot["reasons"])
    if conventions is not None:
        from .ledger import bound_genesis

        from .authority_ledger import AuthorityLedger

        if not isinstance(ledger, AuthorityLedger) and snapshot[
            "genesis"
        ] != bound_genesis(conventions):
            reasons.append("ledger.genesis_binding_mismatch")
            snapshot = dict(snapshot, cumulative_n=None, cumulative_n_lower_bound=None)

    if conventions is None:
        reasons += [
            "prereg_missing" if prereg is None else "dsr.runtime_bindings_pending"
        ]
    else:
        reasons += ["dsr.runtime_bindings_pending"]
    if conventions is not None and conventions.document["version"] in (
        "v1.0.1",
        "v2.0.0",
        "v3.0.0",
    ):
        from .reference_check import reference_manifest_check

        if not isinstance(request, dict):
            reasons.append("dsr.request_invalid")
        else:
            references = reference_manifest_check(request, conventions=conventions)
            reasons.extend(references["reasons"])
            if "sidecars" in request:
                from .reference_evidence import reference_runtime_check

                reasons.extend(
                    reference_runtime_check(request, conventions=conventions)["reasons"]
                )
    metrics = {
        "gate_N": None,
        "factor_arm_N_complete": False,
        "dsr": None,
        "trials_variance": None,
        "family_variance": None,
        "independent_variance": None,
        "sharpe": None,
        "sr0": None,
        "passed": False,
        "cumulative_n": snapshot["cumulative_n"],
        "cumulative_n_lower_bound": snapshot["cumulative_n_lower_bound"],
        "n_ledger_hash": snapshot["n_ledger_hash"],
        "recorded_N": snapshot.get("recorded_N"),
        "n_high_water": snapshot.get("n_high_water"),
        "authority_tip": snapshot.get("authority_tip"),
        "authority_sequence": snapshot.get("authority_sequence"),
    }
    report = result(
        "dsr_eval",
        {
            "request": request,
            "ledger": snapshot,
            "prereg": prereg,
            "prereg_sha256": prereg_sha256,
            **(conventions.binding if conventions else {}),
        },
        metrics=metrics,
        reasons=reasons,
        missing=[
            "complete_N_and_ledger_hash",
            "candidate_reference_manifest",
            "meta_reference_manifest",
            "predeclared_reference_registry",
        ],
        availability={
            k: unavailable(reasons[-1]) for k in ("dsr", "trials_variance", "sharpe")
        },
        assumptions=[
            "Runtime DSR and V are unavailable on every public path; plugins are never invoked.",
            "Only explicit pure formula/daily_sr unit arithmetic is available.",
        ],
    )
    report["runtime_consumable"] = False
    return conventions.bind(report) if conventions else report


def dsr_eval(
    request,
    ledger,
    *,
    prereg=None,
    prereg_sha256=None,
    plugin=None,
    conventions=None,
    arm_tag=MISSING,
):
    """D compatibility only for a completely omitted label; never infer an arm."""
    try:
        tag = label(request, arm_tag)
    except ValueError as exc:
        return _arm_refusal(request, str(exc))
    if tag is MISSING:  # D_COMPAT_ROUTE: no formal dispatch, regardless of readiness.
        return _diagnostic_dsr(
            request,
            ledger,
            prereg=prereg,
            prereg_sha256=prereg_sha256,
            plugin=plugin,
            conventions=conventions,
        )
    return dsr_eval_arm(
        request,
        ledger,
        prereg=prereg,
        prereg_sha256=prereg_sha256,
        plugin=plugin,
        conventions=conventions,
        arm_tag=tag,
    )


def _arm_refusal(request, reason, arm_tag=MISSING):
    return result(
        "dsr_eval",
        {"request": request},
        reasons=[reason],
        metrics={
            "gate_N": None,
            "factor_arm_N_complete": False,
            "n_complete": False,
            "dsr": None,
            "trials_variance": None,
            "sharpe": None,
            "passed": False,
            "cumulative_n": None,
            "cumulative_n_lower_bound": None,
            "arm_n": readout(None, arm_tag)["metrics"]["arm_n"],
            "N_rows": readout(None, arm_tag)["metrics"]["N_rows"],
        },
    )


def dsr_eval_arm(
    request,
    ledger,
    *,
    prereg=None,
    prereg_sha256=None,
    plugin=None,
    conventions=None,
    arm_tag=MISSING,
):
    """Formal route: label identity is required before any chain consumer."""
    try:
        tag = label(request, arm_tag)
    except ValueError as exc:
        return _arm_refusal(request, str(exc))
    if not valid_arm(tag):  # D_FORMAL_LABEL_GUARD
        return _arm_refusal(request, "arm_n.arm_tag_missing_or_invalid", tag)
    arm_report = ledger.arm_readout(tag)
    snapshot = arm_report["artifacts"]["ledger"]
    reasons = list(arm_report["reasons"]) + ["dsr.runtime_bindings_pending"]
    metrics = dict(
        arm_report["metrics"],
        gate_N=None,
        factor_arm_N_complete=False,
        dsr=None,
        trials_variance=None,
        sharpe=None,
        passed=False,
        recorded_N=snapshot.get("recorded_N"),
        n_high_water=snapshot.get("n_high_water"),
        authority_tip=snapshot.get("authority_tip"),
    )
    report = result(
        "dsr_eval",
        {
            "request": request,
            "ledger": snapshot,
            "prereg": prereg,
            "prereg_sha256": prereg_sha256,
        },
        reasons=reasons,
        metrics=metrics,
        missing=["complete_N_and_ledger_hash", "runtime_bindings"],
        assumptions=["Explicit arm identity never substitutes for history acceptance."],
    )
    return conventions.bind(report) if conventions else report


def arm_snapshot(ledger, self_report_n, policy=None, *, arm_tag=None):
    """Read-only v3 arm projection; a self-report is audit metadata, never gate N."""
    if policy is not None and not hasattr(policy, "document"):
        raise ValueError("dsr.policy_invalid")
    arm_report = (
        readout(None, arm_tag)
        if not valid_arm(arm_tag)
        else ledger.arm_readout(arm_tag)
    )
    arm = arm_report["metrics"]["arm_n"]
    return dict(
        gate_n=arm["cumulative_n"],
        n_complete=arm["n_complete"],
        cumulative_n=arm["cumulative_n"],
        n_ledger_hash=arm["n_ledger_hash"],
        book_or_request_high_water=self_report_n,
        N_rows=arm["rows"],
        arm_n=arm,
        reasons=arm_report["reasons"],
    )
