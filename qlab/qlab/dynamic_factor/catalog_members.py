"""Pure membership derivation reused by factor and isolated reference checks."""


def members(entries):
    blocked = sorted(
        e["symbol"]
        for e in entries
        if e["status"] == "UNRESOLVED"
        or e.get("guard_pending_review") is True
        or (e["status"] == "UNKNOWN" and e["credible_event_evidence"])
    )
    unknown = sorted(
        e["symbol"]
        for e in entries
        if e["status"] == "UNKNOWN"
        and not e["credible_event_evidence"]
        and not e.get("guard_pending_review", False)
    )
    return blocked, unknown
