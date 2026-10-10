"""Bets must never overwrite protected elements, even in cramped layouts."""

from decimal import Decimal

import pytest
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPixmap

from fpdb_3_legacy.GuiReplayer import build_replay_layout
from fpdb_3_legacy.replayer_chip_renderer import draw_chip_amount

pytestmark = pytest.mark.qt


def test_obstructed_local_offsets_find_a_free_area(qapp):
    canvas = QPixmap(900, 600)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    obstacles = (QRectF(100, 50, 500, 450),)
    bounds, stacks = draw_chip_amount(
        painter, Decimal("17.50"), QPointF(350, 250), "$17.50", Decimal(".01"),
        avoid=obstacles, available=QRectF(0, 0, 900, 600),
    )
    painter.end()
    assert not bounds.isNull()
    assert stacks
    assert not bounds.intersects(obstacles[0])
    assert canvas.rect().contains(bounds.toRect())


def test_cramped_area_keeps_exact_amount_without_decorative_stacks(qapp):
    canvas = QPixmap(100, 50)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    bounds, stacks = draw_chip_amount(
        painter, Decimal("17.50"), QPointF(50, 25), "$17.50", Decimal(".01"),
        available=QRectF(0, 0, 100, 50),
    )
    painter.end()
    assert not bounds.isNull()
    assert sum(stack.count * stack.denomination for stack in stacks) == Decimal("17.50")
    assert canvas.rect().contains(bounds.toRect())


@pytest.mark.parametrize("count", range(2, 11))
@pytest.mark.parametrize("size", [(1280, 720), (1600, 900), (1260, 1380)])
@pytest.mark.parametrize("big_blinds", [False, True])
def test_every_seat_bet_fits_oval_with_board_dealer_and_other_bets(qapp, count, size, big_blinds):
    names = ["Hero", *(f"Player{i}" for i in range(1, count))]
    layout = build_replay_layout(*size, names, "Hero", "holdem")
    oval = layout.table_rect.adjusted(14, 14, -14, -14)
    felt = QPainterPath()
    felt.addEllipse(oval)
    reserved = [layout.board_rect, layout.pot_rect.adjusted(-10, -6, 10, 6)]
    for seat in layout.seats.values():
        reserved.extend((seat.cards_rect.adjusted(-2, -20, 2, 4), seat.panel_rect.adjusted(0, 0, 0, 3)))
    dealer = layout.seats[names[-1]].dealer_pos
    reserved.append(QRectF(dealer.x() - 16, dealer.y() - 16, 32, 32))
    canvas = QPixmap(*size)
    with QPainter(canvas) as painter:
        for i, seat in enumerate(layout.seats.values()):
            amount = (Decimal(".12"), Decimal(".24"), Decimal("2.47"))[i % 3]
            text = f"{amount / Decimal('.01')} BB" if big_blinds else f"${amount:.2f}"
            bounds, stacks = draw_chip_amount(
                painter, amount, seat.bet_rect.center(), text, Decimal(".01"),
                max_width=200, avoid=tuple(reserved), available=QRectF(canvas.rect()), felt=oval,
            )
            assert not bounds.isNull(), (count, size, big_blinds, i)
            assert felt.contains(bounds), (count, size, big_blinds, i, bounds)
            assert all(not bounds.intersects(region) for region in reserved)
            assert sum(stack.count * stack.denomination for stack in stacks) == amount
            reserved.append(bounds)
