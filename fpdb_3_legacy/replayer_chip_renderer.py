"""Compact felt-side chip stacks and high-contrast monetary labels."""

from decimal import Decimal

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen

from fpdb_3_legacy.replayer_chips import ChipStack, chip_stacks
from fpdb_3_legacy.replayer_style import replay_font


def draw_chip_amount(
    painter: QPainter,
    amount: Decimal,
    anchor: QPointF,
    text: str,
    quantum: Decimal,
    *,
    show_chips: bool = True,
    max_width: float = 240,
    avoid: tuple[QRectF, ...] = (),
) -> tuple[QRectF, list[ChipStack]]:
    stacks = chip_stacks(amount, quantum) if show_chips else []
    painter.save()
    painter.setFont(replay_font("DejaVu Sans", 9, QFont.Weight.DemiBold))
    metrics = painter.fontMetrics()
    label_width = metrics.horizontalAdvance(text) + 16
    label_height = max(32, metrics.height() + 8)
    diameter, gap = 22, 8 if stacks else 0
    stride = min(20, max(5, (max_width - label_width - gap - diameter) / max(1, len(stacks) - 1)))
    chips_width = diameter + (len(stacks) - 1) * stride if stacks else 0
    width = chips_width + gap + label_width
    offsets = sorted(
        ((x, y) for x in (0, -36, 36, -72, 72) for y in (0, -40, 40, -52, 52)),
        key=lambda offset: abs(offset[0]) + abs(offset[1]),
    )
    for offset_x, offset_y in offsets:
        candidate = QPointF(anchor.x() + offset_x, anchor.y() + offset_y)
        bounds = QRectF(candidate.x() - width / 2, candidate.y() - label_height / 2, width, label_height)
        if all(not bounds.intersects(region.adjusted(-4, -4, 4, 4)) for region in avoid):
            anchor = candidate
            break
    left = anchor.x() - width / 2
    for column, stack in enumerate(stacks):
        center_x = left + diameter / 2 + column * stride
        color = QColor(stack.color)
        rim = QColor("#3f474f") if color.lightness() > 170 else QColor("#e4e7e9")
        for number in range(stack.count):
            top = QRectF(center_x - diameter / 2, anchor.y() + 2 - number * 3, diameter, 10)
            painter.setPen(QPen(color.darker(170), 1))
            painter.setBrush(color.darker(140))
            painter.drawEllipse(top.translated(0, 3))
            painter.setBrush(color)
            painter.drawEllipse(top)
            painter.setPen(QPen(rim, 1.6))
            for angle in (20, 110, 200, 290):
                painter.drawArc(top.adjusted(1, 1, -1, -1), angle * 16, 30 * 16)
            painter.setPen(QPen(color.darker(150), 1))
            painter.setBrush(color.lighter(115))
            painter.drawEllipse(top.adjusted(5, 2, -5, -2))
    label = QRectF(left + chips_width + gap, anchor.y() - label_height / 2, label_width, label_height)
    painter.setPen(QPen(QColor("#43505c"), 1))
    painter.setBrush(QColor(12, 20, 27, 235))
    painter.drawRoundedRect(label, 5, 5)
    painter.setPen(QColor("#f5f7fa"))
    painter.drawText(label, Qt.AlignmentFlag.AlignCenter, text)
    painter.restore()
    return QRectF(left, label.top(), width, label_height), stacks
