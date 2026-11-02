"""Execution-only B checks after scoped full-state validation.

This does not read or convert money. The original noncash_v3 module and its
module-SHA-bound legacy receipts remain untouched. Its B segment is preserved
structurally. The distinct state validators and finite differential coverage
are tested separately, including host containers and refusal order.
"""


def verify_execution_exposure(state, guard, *, initial=False):
    if not (
        set(guard["request"]["catalog"]["universe"]) | set(guard["children"])
    ).issubset(state["inventory"]):
        raise ValueError("B.complete_inventory_zero_evidence_required")
    if (
        "pending_orders" not in state
        or not isinstance(state["pending_orders"], list)
        or state["rights"]
        or state["receivables"]
    ):
        raise ValueError("B.zero_exposure_unproven_or_old_rights")
    blocked = set(guard["B"]) | set(guard["unknown"]) | set(guard["children"])
    # An undeclared child cannot acquire an exemption by being absent from
    # the current directory. The frozen domain plus QQQ is the outer boundary.
    blocked.update(
        set(state["inventory"]) - set(guard["request"]["catalog"]["universe"]) - {"QQQ"}
    )
    if any(q and (initial or s in blocked) for s, q in state["inventory"].items()):
        raise ValueError("B.nonzero_initial_or_guarded_exposure")
    for order in state["pending_orders"]:
        if (
            not isinstance(order, dict)
            or set(order) != {"symbol", "side", "quantity"}
            or not isinstance(order["symbol"], str)
            or order["side"] not in {"BUY", "SELL"}
            or type(order["quantity"]) is not int
            or order["quantity"] < 0
        ):
            raise ValueError("B.pending_state_unknown")
        if (
            order["side"] == "BUY"
            and order["quantity"]
            and (
                initial
                or order["symbol"] in blocked
                or order["symbol"]
                not in set(guard["request"]["catalog"]["universe"]) | {"QQQ"}
            )
        ):
            raise ValueError("B.guarded_pending_buy")
