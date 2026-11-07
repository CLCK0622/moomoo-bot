"""EA.N1 exact monetary domain and bridge to the original candidate fee engine."""

import re

from .execution import OrderCosts
from .fees import finite
from .input_scope import reject_b2_inputs
from .execution_numbers import amount as amount, decimal_text as decimal_text


class ExactOrderCosts(OrderCosts):
    def quote_exact(
        self,
        orders,
        notionals,
        *,
        guard,
        execution_binding,
        release_context=None,
        expected_release_identity_bytes=None,
    ):
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

        formal = isinstance(guard, dict) and (
            guard.get("schema") == "EVO883.BRuntimeGuard/v1"
            or any(
                guard.get(k) is not None
                for k in (
                    "B_catalog_release_sha256",
                    "B_release_acceptance_sha256",
                    "accepted_catalog_sha256",
                    "release_context_binding",
                )
            )
            or "release_binding" in guard.get("request", {})
        )
        if not formal and (
            release_context is not None or expected_release_identity_bytes is not None
        ):
            raise ValueError("B.release_context_scope_mismatch")
        if formal:
            try:
                from .noncash_v3 import (
                    ReleaseContext,
                    check_release_context,
                    checked_guard,
                )
            except ImportError as exc:
                raise ValueError(
                    "B.release_context_implementation_unavailable"
                ) from exc
            if release_context is None:
                raise ValueError("B.release_context_required")
            if type(release_context) is not ReleaseContext:
                raise ValueError("B.release_context_type_mismatch")
            raw = check_release_context(
                release_context,
                policy=self.policy,
                request=guard["request"],
                expected_release_identity_bytes=expected_release_identity_bytes,
            )
            if type(raw) is not bytes:
                raise ValueError("B.release_context_encoding_invalid")
            if (
                expected_release_identity_bytes is not None
                and raw != expected_release_identity_bytes
            ):
                raise ValueError("B.release_context_persistent_identity_mismatch")
            checked_guard(
                guard,
                self.policy,
                release_context=release_context,
                expected_release_identity_bytes=raw,
            )
        assert_consumer_symbols(
            guard,
            "order",
            [s for s, q in orders.items() if q],
            self.policy,
            release_context=release_context,
            expected_release_identity_bytes=raw if formal else None,
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
