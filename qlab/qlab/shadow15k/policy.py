"""Frozen definition identity does not supply runtime N/V or forward permission."""

from .contract import report
from qlab.dynamic_factor.conventions import load_conventions

PENDING = "runtime_evidence_unavailable_v1"


def _refuse(name, request):
    value = report(
        name, request, reasons=[PENDING], metrics={"allowed": False, "parameters": None}
    )
    value["missing_inputs"] = [
        "complete_N_reference_runtime_evidence_and_forward_authorization"
    ]
    return load_conventions().bind(value)


def pool_admission_check(request):
    return _refuse("pool_admission_check", request)


def tilt_weights(request):
    return _refuse("tilt_weights", request)


def initial_build_turnover_check(request):
    return _refuse("initial_build_turnover_check", request)


def turnover_check(request):
    return _refuse("turnover_check", request)


def voluntary_trade_gate(request):
    return _refuse("voluntary_trade_gate", request)


def rebalance_plan(request):
    return _refuse("rebalance_plan", request)


def retirement_check(request):
    return _refuse("retirement_check", request)
