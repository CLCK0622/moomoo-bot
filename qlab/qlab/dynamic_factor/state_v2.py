"""Conserve declared account state; isolation never authors a transaction."""

from copy import deepcopy

from .contract import digest, is_sha, result
from .conventions import load_conventions
from .fees import finite
from .input_scope import reject_b2_inputs

CORE = {
    "inventory",
    "cash",
    "age",
    "origin",
    "rights",
    "receivables",
    "unknown_components",
    "nav",
}
EVENT_FIELDS = {
    "existing_order_fill": {"inventory", "cash", "age", "origin", "nav"},
    "existing_fee": {"cash", "nav"},
    "existing_corporate_action": {
        "inventory",
        "cash",
        "origin",
        "rights",
        "receivables",
        "nav",
    },
    "existing_mark": {"nav"},
    "session_age": {"age"},
}


def necessary_state_known(state):
    def unknown(x):
        return (
            x is None
            or (isinstance(x, float) and not finite(x))
            or (isinstance(x, dict) and any(unknown(v) for v in x.values()))
            or (isinstance(x, list) and any(unknown(v) for v in x))
        )

    if (
        not isinstance(state, dict)
        or not CORE.issubset(state)
        or any(unknown(state[k]) for k in CORE)
        or state["unknown_components"]
        or not finite(state["nav"])
        or state["nav"] <= 0
        or not finite(state["cash"])
        or state["cash"] < 0
        or any(
            not isinstance(state[k], dict)
            for k in ("inventory", "age", "origin", "rights", "receivables")
        )
        or any(type(q) is not int or q < 0 for q in state["inventory"].values())
        or any(type(a) is not int or a < 0 for a in state["age"].values())
        or any(
            q and (s not in state["age"] or s not in state["origin"])
            for s, q in state["inventory"].items()
        )
    ):
        raise ValueError("state.R2_necessary_state_unknown")


def transition_reasons(before, after, receipts, policy):
    necessary_state_known(before)
    necessary_state_known(after)
    changed = {k for k in CORE if before[k] != after[k]}
    covered = set()
    for r in receipts:
        if (
            r.get("event_type") not in EVENT_FIELDS
            or not is_sha(r.get("source_sha256"))
            or r.get("before_state_sha256") != digest(before)
            or r.get("after_state_sha256") != digest(after)
            or r.get("common_profile_sha256") != policy.binding["common_profile_sha256"]
            or not isinstance(r.get("changed_fields"), list)
            or not r["changed_fields"]
            or not set(r["changed_fields"]).issubset(EVENT_FIELDS[r["event_type"]])
        ):
            raise ValueError("state.original_transition_receipt_required")
        covered.update(r["changed_fields"])
    if changed != covered:
        raise ValueError("state.isolation_may_not_erase_or_invent_state")
    if before.get("initialization_count") != after.get("initialization_count"):
        raise ValueError("state.capital_reinitialization_forbidden")


def state_transition_check(request, *, conventions=None):
    p = conventions or load_conventions()
    reasons = []
    before, after = request.get("before"), request.get("after")
    try:
        reject_b2_inputs(request, "holdings_cash")
        if (
            request.get("skip_fold")
            or request.get("valid_only")
            or request.get("restart_capital")
        ):
            raise ValueError("state.skip_or_capital_reset_forbidden")
        transition_reasons(before, after, request.get("transition_receipts", []), p)
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        reasons.append(
            str(exc)
            if isinstance(exc, ValueError)
            else "state.R2_necessary_state_unknown"
        )
    return p.bind(
        result(
            "state_transition_check",
            request,
            reasons=reasons,
            metrics={
                "last_known_state": deepcopy(before),
                "declared_next_state": deepcopy(after),
                "next_state": deepcopy(after) if not reasons else None,
                "R2_stop": bool(reasons),
                "new_exit_policy": False,
                "receipt_consistency_only": True,
                "execution_verified": False,
            },
        )
    )
