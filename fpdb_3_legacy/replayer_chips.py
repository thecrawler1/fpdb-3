"""Exact, display-independent chip stacks for cash and tournament replays."""

from dataclasses import dataclass
from decimal import Decimal
from math import gcd
from typing import cast


@dataclass(frozen=True)
class ChipStack:
    """A stack of identically valued chips, in the hand's original units."""

    denomination: Decimal
    count: int
    color: str


# White, red, green, charcoal, purple and gold; repeated for larger values.
_COLORS = ("#dedbd2", "#a94f4f", "#527b59", "#343434", "#79618c", "#b29a58")


def _coefficient(value: Decimal) -> int:
    coefficient = 0
    for digit in value.as_tuple().digits:
        coefficient = coefficient * 10 + digit
    return coefficient


def chip_stacks(amount: Decimal, quantum: Decimal = Decimal("0.01")) -> list[ChipStack]:
    """Decompose an amount into descending stacks, each containing 1–4 chips.

    Denominations follow 1, 5, 25, 100, 500, 2500, ... times the quantum.
    When needed, subdivide the quantum to represent the amount exactly (even
    for non-power-of-ten quanta). Tournament callers can use quantum=Decimal(1).
    Values never depend on BB label settings or the active Decimal precision.

    Nonpositive amounts return an empty list. Non-Decimal inputs raise
    TypeError; nonfinite amounts and nonfinite/nonpositive quanta raise ValueError.
    """
    if not isinstance(amount, Decimal) or not isinstance(quantum, Decimal):
        raise TypeError("amount and quantum must be Decimal values")
    if not quantum.is_finite() or quantum <= 0:
        raise ValueError("quantum must be finite and positive")
    if not amount.is_finite():
        raise ValueError("amount must be finite")
    if amount <= 0:
        return []

    # Work in integer units to avoid rounding by the caller's Decimal context.
    amount_exponent = cast(int, amount.as_tuple().exponent)
    quantum_exponent = cast(int, quantum.as_tuple().exponent)
    exponent = min(amount_exponent, quantum_exponent)
    remaining = _coefficient(amount) * 10 ** (amount_exponent - exponent)
    quantum_units = _coefficient(quantum) * 10 ** (quantum_exponent - exponent)
    unit = gcd(remaining, quantum_units)
    remaining //= unit

    denominations = [1]
    while denominations[-1] <= remaining:
        multiplier = 4 if len(denominations) % 3 == 0 else 5
        denominations.append(denominations[-1] * multiplier)

    stacks = []
    for index in range(len(denominations) - 2, -1, -1):
        count, remaining = divmod(remaining, denominations[index])
        if count:
            digits = Decimal(denominations[index] * unit).as_tuple().digits
            denomination = Decimal((0, digits, exponent))
            stacks.append(ChipStack(denomination, count, _COLORS[index % len(_COLORS)]))
    return stacks
