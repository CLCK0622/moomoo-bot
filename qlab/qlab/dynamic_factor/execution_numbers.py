"""EA.N1 finite canonical decimal values and exact arithmetic boundaries."""

from decimal import Decimal
from fractions import Fraction
import re


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
