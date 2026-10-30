"""Frozen day63/126 routing only; no return estimation or certification."""

from decimal import Decimal, InvalidOperation


def decide(
    *,
    day,
    lower,
    upper,
    extended,
    configuration_sha256,
    original_configuration_sha256,
    data_valid=True,
    version_active=True,
    dsr=None,
):
    if day not in {63, 126} or type(extended) is not bool:
        raise ValueError("milestone.day_or_extension_invalid")
    base = dict(
        certifiable=False,
        dsr=dsr,
        DSR_role="DIAGNOSTIC_ONLY"
        if day == 63
        else "CERTIFICATION_INPUT_NOT_AUTOMATIC_CERTIFICATION",
    )
    if not version_active:
        return dict(base, action="STOP_VERSION")
    if not data_valid or configuration_sha256 != original_configuration_sha256:
        return dict(base, action="DATA_INVALID_HANDOFF_NO_CLOCK_RESET")
    try:
        if not isinstance(lower, str) or not isinstance(upper, str):
            raise ValueError("milestone.finite_interval_required")
        lo, hi = Decimal(lower), Decimal(upper)
        if not lo.is_finite() or not hi.is_finite() or lo > hi:
            raise ValueError("milestone.finite_interval_required")
    except InvalidOperation as exc:
        raise ValueError("milestone.finite_interval_required") from exc
    if hi <= 0:
        return dict(base, action="STOP_VERSION")
    if day == 126:
        if not extended:
            raise ValueError("milestone.day126_without_registered_extension")
        return dict(base, action="HANDOFF_CUMULATIVE126_AND_SECOND63_NO_EXTENSION")
    if lo <= 0 < hi:
        if extended:
            raise ValueError("milestone.extension_already_used")
        return dict(base, action="EXTEND_ONCE_TO126_UNVERIFIED")
    return dict(base, action="POSITIVE_DIAGNOSTIC_UNVERIFIED_HANDOFF")
