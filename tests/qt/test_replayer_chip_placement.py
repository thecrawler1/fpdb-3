"""Bets must never overwrite protected elements, even in cramped layouts."""

from decimal import Decimal

import pytest
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPixmap

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
