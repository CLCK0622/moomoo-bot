"""C04/C06-only exact-money state validation; legacy readers stay numeric-only.

This is structural validation, not a risk/quantity/valuation algorithm. Raw
state amounts and identities are never replaced by floats or placeholders.
"""

from .state_v2 import CORE
from .fees import finite


def _known_money(value, *, positive=False):
    # A structural EA.N1 decimal check needs no additional reader/import path.
    # Arithmetic stays in the one exact monetary module. No float conversion,
    # placeholder amount or rounding is introduced into the retained state.
    if type(value) in (int, float):
        return finite(value) and (value > 0 if positive else value >= 0)
    if type(value) is not str:
        return False
    parts = value.split(".")
    if (
        len(parts) not in (1, 2)
        or not parts[0]
        or (len(parts[0]) > 1 and parts[0][0] == "0")
        or any(not part or any(c < "0" or c > "9" for c in part) for part in parts)
        or (len(parts) == 2 and parts[1][-1] == "0")
    ):
        return False
    return not positive or value != "0"


def necessary_execution_state_known(state):
    def unknown(x):
        return (
            x is None
            or (isinstance(x, float) and not finite(x))
            or (isinstance(x, dict) and any(unknown(v) for v in x.values()))
            or (isinstance(x, list) and any(unknown(v) for v in x))
        )

    try:
        money_known = _known_money(state["nav"], positive=True) and _known_money(
            state["cash"]
        )
    except (ValueError, TypeError, KeyError, ArithmeticError):
        money_known = False
    if (
        not isinstance(state, dict)
        or not CORE.issubset(state)
        or any(unknown(state[k]) for k in CORE)
        or state["unknown_components"]
        or not money_known
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
