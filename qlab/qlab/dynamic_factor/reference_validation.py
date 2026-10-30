"""Pure validation shared by the host and isolated reference worker. No IO."""

from datetime import datetime, timezone


def utc_instant(value):
    if not isinstance(value, str):
        raise ValueError("reference.timezone_timestamp_required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("reference.timezone_timestamp_required")
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("reference.timezone_timestamp_required") from exc


def validate_timing(scope, guard):
    """Guard <= scope < the same performance instant, in the same mode."""
    if scope.get("mode") not in {"history", "forward"} or scope["mode"] != guard.get(
        "mode"
    ):
        raise ValueError("reference.scope_guard_mode_mismatch")
    sealed = utc_instant(scope["sealed_at"])
    performance = utc_instant(scope["first_performance_at"])
    if (
        utc_instant(guard["first_performance_at"]) != performance
        or not utc_instant(guard["sealed_at"]) <= sealed < performance
    ):
        raise ValueError("reference.scope_view_or_preperformance_mismatch")
