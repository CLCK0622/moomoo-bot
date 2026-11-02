"""EA.N1 exact monetary domain and bridge to the original candidate fee engine."""

from decimal import Decimal
from fractions import Fraction
import re

from .execution import OrderCosts
from .fees import finite
from .input_scope import reject_b2_inputs


DECIMAL = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]*[1-9])?\Z")


def amount(value):
    """Exact finite decimal input; no ambient Decimal arithmetic or epsilon."""
    if type(value) not in (str, int, float) or isinstance(value, bool):
        raise ValueError("projection.decimal_required")
    spelling = str(value)
    if type(value) is str and (not DECIMAL.fullmatch(spelling) or spelling == "-0"):
        raise ValueError("projection.canonical_decimal_required")
    try:
        return Fraction(Decimal(spelling))
    except (ValueError, ArithmeticError) as exc:
        raise ValueError("projection.finite_decimal_required") from exc


def decimal_text(value):
    """Render a finite decimal rational without a context-rounded division."""
    numerator, denominator = value.numerator, value.denominator
    two = five = 0
    while denominator % 2 == 0:
        denominator //= 2
        two += 1
    while denominator % 5 == 0:
        denominator //= 5
        five += 1
    if denominator != 1:
        raise ValueError("projection.nonterminating_amount")
    scale = max(two, five)
    numerator *= 2 ** (scale - two) * 5 ** (scale - five)
    digits = str(abs(numerator)).rjust(scale + 1, "0")
    out = (
        (digits[:-scale] + "." + digits[-scale:]).rstrip("0").rstrip(".")
        if scale
        else digits
    )
    return ("-" if numerator < 0 else "") + out


class ExactOrderCosts(OrderCosts):
    def quote_exact(self, orders, notionals, *, guard, execution_binding):
        """EA.N1 bridge to the unchanged per-order fee formula.

        D1 supplies exact, already netted notionals. Do not multiply binary
        float unit prices here. The existing quote API and formulas stay intact.
        A value the original numeric interface cannot carry exactly is unknown,
        never rounded into an accepted quote or a smaller order.
        """
        from decimal import Decimal
        from fractions import Fraction

        from .execution_closure import fee_context
        from .fee_model import order_cost

        reject_b2_inputs({"orders": orders, "notionals": notionals}, "orders")
        if set(orders) != set(notionals):
            raise ValueError("fee.exact_net_order_membership")
        from .noncash_v3 import assert_consumer_symbols

        assert_consumer_symbols(
            guard, "order", [s for s, q in orders.items() if q], self.policy
        )
        floor = float(
            re.search(
                r",([0-9.]+)\*filled_notional\)",
                self.policy.document["cost_mapping"]["floor_policy"]["x1"],
            )[1]
        )
        total = Fraction(0)
        for s in sorted(orders):
            q, value = orders[s], notionals[s]
            if (
                type(q) is not int
                or type(value) is not Decimal
                or not value.is_finite()
                or value < 0
                or (q == 0) != (value == 0)
            ):
                raise ValueError("fee.exact_net_order_invalid")
            if q == 0:
                continue
            number = int(value) if value == value.to_integral_value() else float(value)
            if not finite(number) or Decimal(str(number)) != value:
                raise ValueError("fee.exact_input_unavailable")
            with fee_context(execution_binding):
                output = order_cost(
                    self.params,
                    "buy" if q > 0 else "sell",
                    abs(q),
                    number,
                    floor,
                    "reference",
                )
            total += Fraction(Decimal(str(output["research_cost_usd"])))
        return total
