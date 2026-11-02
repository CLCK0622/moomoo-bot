"""Execution-only B checks after scoped full-state validation.

This does not read or convert money. The original noncash_v3 module and its
module-SHA-bound legacy receipts remain untouched. Numeric-domain equivalence
to its original zero_exposure is tested separately, including refusal order.
"""


def verify_execution_exposure(state, guard, *, initial=False):
    universe = set(guard["request"]["catalog"]["universe"])
    children = set(guard["children"])
    inventory = state["inventory"]
    if (universe | children) - inventory.keys():
        raise ValueError("B.complete_inventory_zero_evidence_required")

    pending = state.get("pending_orders")
    if not isinstance(pending, list) or state["rights"] or state["receivables"]:
        raise ValueError("B.zero_exposure_unproven_or_old_rights")

    permitted = universe | {"QQQ"}
    forbidden = set(guard["B"]) | set(guard["unknown"]) | children
    for symbol, quantity in inventory.items():
        if quantity and (initial or symbol in forbidden or symbol not in permitted):
            raise ValueError("B.nonzero_initial_or_guarded_exposure")

    for order in pending:
        if not isinstance(order, dict) or order.keys() != {
            "symbol",
            "side",
            "quantity",
        }:
            raise ValueError("B.pending_state_unknown")
        symbol, side, quantity = order["symbol"], order["side"], order["quantity"]
        if (
            not isinstance(symbol, str)
            or side not in {"BUY", "SELL"}
            or type(quantity) is not int
            or quantity < 0
        ):
            raise ValueError("B.pending_state_unknown")
        if side == "BUY" and quantity:
            if initial or symbol in forbidden or symbol not in permitted:
                raise ValueError("B.guarded_pending_buy")
