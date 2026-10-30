"""Pinned preregistration and injectable DSR interface; no inferred formula/V."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .contract import code_sha, digest, is_sha, result, unavailable
from .fees import finite


def prereg_check(prereg, expected_sha256, *, conventions=None):
    if conventions is not None:
        reasons = ["prereg_draft_not_frozen"]
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


def dsr_eval(
    request, ledger, *, prereg=None, prereg_sha256=None, plugin=None, conventions=None
):
    if conventions is not None:
        if conventions.document["version"] == "v0.2":
            from .pipeline import evaluate
        else:
            from .dsr_v0 import evaluate
        return evaluate(request, ledger, conventions)
    snapshot = ledger.safe_snapshot()
    inputs = {
        "request": request,
        "ledger": snapshot,
        "prereg": prereg,
        "prereg_sha256": prereg_sha256,
    }
    reasons = list(snapshot["reasons"])
    if not isinstance(request, dict):
        reasons.append("dsr.request_invalid")
    check = prereg_check(prereg, prereg_sha256)
    reasons.extend(check["reasons"])
    metrics = {
        "dsr": None,
        "trials_variance": None,
        "sharpe": None,
        "cumulative_n": snapshot["cumulative_n"],
        "n_ledger_hash": snapshot["n_ledger_hash"],
    }
    plugin_sources = {}
    if prereg is not None and not check["reasons"] and isinstance(request, dict):
        if request.get("sharpe_scale") != prereg["dsr"]["sharpe_scale"]:
            reasons.append("dsr.scale_mismatch")
        if plugin is None:
            reasons.append("formula_plugin_unset")
        else:
            try:
                actual = code_sha(plugin.evaluate)
                plugin_sources["adapter/dsr_formula"] = actual
                inputs["plugin_source_sha256"] = actual
                if (
                    plugin.prereg_sha256 != prereg_sha256
                    or plugin.source_sha256 != actual
                    or plugin.formula_id != prereg["dsr"]["formula_id"]
                ):
                    reasons.append("formula_plugin_identity_mismatch")
            except (OSError, TypeError, ValueError):
                reasons.append("formula_plugin_source_unavailable")
    if not reasons:
        try:
            evaluated = plugin.evaluate(request, snapshot, prereg)
            if not (
                finite(evaluated["dsr"])
                and 0 <= evaluated["dsr"] <= 1
                and finite(evaluated["trials_variance"])
                and evaluated["trials_variance"] >= 0
                and finite(evaluated["sharpe"])
                and type(evaluated["passed"]) is bool
            ):
                raise ValueError("invalid formula result")
            metrics.update(
                {k: evaluated[k] for k in ("dsr", "trials_variance", "sharpe")}
            )
            metrics["passed"] = evaluated["passed"]
        except Exception:
            reasons.append("formula_plugin_failed_or_unavailable")
    reason = "prereg_missing" if prereg is None else (reasons[0] if reasons else None)
    return result(
        "dsr_eval",
        inputs,
        reasons=reasons,
        metrics=metrics,
        missing=check["missing_inputs"],
        certifiable=not reasons,
        extra_sources=plugin_sources,
        availability={
            k: unavailable(reason) if reason else {"available": True, "reason": None}
            for k in ("dsr", "trials_variance", "sharpe")
        },
        assumptions=[
            "No built-in DSR or V estimator; the pinned EVO-883 plugin owns both.",
            "Plugin receives all attempts, including failed, NaN, repeated and interrupted attempts.",
            "A statistical gate result does not authorize deployment or trading.",
        ],
    )
