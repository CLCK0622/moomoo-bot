"""Local refusals stay independent of PR #10's draft strategy wiring."""

from .contract import report

PENDING = "prereg_pending_v0.2"


def _refuse(name, request):
    value = report(
        name, request, reasons=[PENDING], metrics={"allowed": False, "parameters": None}
    )
    value["missing_inputs"] = ["frozen_meta_strategy_and_hanlin_verification"]
    return value


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
