"""Actual-value chip decomposition, independent of rendering and BB labels."""

from dataclasses import FrozenInstanceError
from decimal import Decimal, localcontext

import pytest

from fpdb_3_legacy.replayer_chips import ChipStack, chip_stacks


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        ("0.02", [("0.01", 2)]),
        ("0.08", [("0.05", 1), ("0.01", 3)]),
        ("0.25", [("0.25", 1)]),
        ("0.53", [("0.25", 2), ("0.01", 3)]),
        ("3.97", [("1", 3), ("0.25", 3), ("0.05", 4), ("0.01", 2)]),
    ],
)
def test_cash_bets_and_sidepot(amount, expected):
    stacks = chip_stacks(Decimal(amount))
    assert [(stack.denomination, stack.count) for stack in stacks] == [
        (Decimal(denomination), count) for denomination, count in expected
    ]


@pytest.mark.parametrize(
    ("amount", "quantum"),
    [
        ("123456789012345678901234567890.97", "0.01"),
        ("1E+100", "0.01"),
        ("0.00000012397", "0.01"),
        ("0.000123", "0.000001"),
        ("0.530000", "0.010000"),
        ("0.53", "0.05"),
        ("0.09", "0.03"),
        ("0.10", "0.03"),
        ("97531", "1"),
        ("0.125", "1"),
        ("0.01", "10"),
    ],
)
def test_exact_amounts_with_bounded_descending_stacks(amount, quantum):
    amount = Decimal(amount)
    with localcontext() as context:
        context.prec = 3
        stacks = chip_stacks(amount, Decimal(quantum))
    with localcontext() as context:
        context.prec = 200
        assert sum((stack.denomination * stack.count for stack in stacks), Decimal(0)) == amount
    assert all(isinstance(stack.count, int) and 1 <= stack.count <= 4 for stack in stacks)
    denominations = [stack.denomination for stack in stacks]
    assert denominations == sorted(set(denominations), reverse=True)
    assert all(denomination > 0 for denomination in denominations)


def test_large_amount_extends_the_ladder():
    stacks = chip_stacks(Decimal("1000000000000"))
    assert len(stacks) == 1
    assert stacks[0].denomination == Decimal("1000000000000")
    assert stacks[0].count == 1


def test_integer_tournament_units():
    stacks = chip_stacks(Decimal("397"), quantum=Decimal(1))
    assert [(stack.denomination, stack.count) for stack in stacks] == [
        (Decimal(100), 3),
        (Decimal(25), 3),
        (Decimal(5), 4),
        (Decimal(1), 2),
    ]


def test_palette_is_stable_for_shared_denominations():
    stacks = chip_stacks(Decimal("31.31"))
    assert len({stack.color for stack in stacks}) == 6
    assert all(stack.color.startswith("#") and len(stack.color) == 7 for stack in stacks)
    for stack in stacks:
        assert chip_stacks(stack.denomination)[0].color == stack.color


def test_chip_stack_is_frozen():
    stack = ChipStack(Decimal("0.25"), 2, "#527b59")
    with pytest.raises(FrozenInstanceError):
        stack.count = 3


@pytest.mark.parametrize("amount", ["0", "-0", "-0.01", "-100"])
def test_nonpositive_amounts(amount):
    assert chip_stacks(Decimal(amount)) == []


@pytest.mark.parametrize("amount", ["NaN", "sNaN", "Infinity", "-Infinity"])
def test_nonfinite_amounts_are_rejected(amount):
    with pytest.raises(ValueError, match="amount"):
        chip_stacks(Decimal(amount))


@pytest.mark.parametrize("quantum", ["0", "-0.01", "NaN", "sNaN", "Infinity", "-Infinity"])
@pytest.mark.parametrize("amount", ["0", "1"])
def test_invalid_quantum_is_rejected_even_for_zero(amount, quantum):
    with pytest.raises(ValueError, match="quantum"):
        chip_stacks(Decimal(amount), Decimal(quantum))


@pytest.mark.parametrize("value", [None, "0.01", 0.01, 1])
def test_non_decimal_inputs_are_rejected(value):
    with pytest.raises(TypeError, match="Decimal"):
        chip_stacks(value)
    with pytest.raises(TypeError, match="Decimal"):
        chip_stacks(Decimal(1), value)
