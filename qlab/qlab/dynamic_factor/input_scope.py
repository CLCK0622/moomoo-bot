"""Pure strategy dependency guard, shared with the isolated reference worker.

B2 identifiers and series cannot enter a strategy packet. This constrains pinned
trusted Python/data manifests; it cannot authenticate a falsely labelled market
source or sandbox hostile adapter/native code.
"""

ROLES = (
    "features",
    "qqq_labels",
    "calibration",
    "admission",
    "reference",
    "holdings_cash",
    "orders",
)


def reject_b2_inputs(value, role):
    if role not in ROLES:
        raise ValueError("scope.unknown_strategy_role")

    def walk(obj, depth):
        if depth > 64:
            raise ValueError("scope.input_too_deep")
        if isinstance(obj, str):
            tokens = "".join(c if c.isalnum() else " " for c in obj.upper()).split()
            if "VTI" in tokens or "B2" in tokens:
                raise ValueError("scope.B2_dependency_forbidden")
        elif isinstance(obj, dict):
            for k, v in obj.items():
                walk(k, depth + 1)
                walk(v, depth + 1)
        elif isinstance(obj, (tuple, list)):
            for v in obj:
                walk(v, depth + 1)

    walk(value, 0)
