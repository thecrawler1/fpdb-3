"""Compact felt-side chip stacks and high-contrast monetary labels."""

from decimal import Decimal

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen

from fpdb_3_legacy.replayer_chips import ChipStack, chip_stacks
from fpdb_3_legacy.replayer_style import replay_font


def _draw_denomination(painter: QPainter, stack: ChipStack, top: QRectF, color: QColor) -> None:
    """Print canonical chip units, even when the total is displayed in BB."""
    denomination = format(stack.denomination, "f")
    if "." in denomination:
        denomination = denomination.rstrip("0").rstrip(".")
    font = QFont("DejaVu Sans", 7, QFont.Weight.Bold)
    font.setPixelSize(10)
    painter.setFont(font)
    while painter.fontMetrics().horizontalAdvance(denomination) > top.width() - 6 and font.pixelSize() > 6:
        font.setPixelSize(font.pixelSize() - 1)
        painter.setFont(font)
    painter.setPen(QColor("#17212a") if color.lightness() > 140 else QColor("#ffffff"))
    painter.drawText(top, Qt.AlignmentFlag.AlignCenter, denomination)


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
    owner: QPointF | None = None,
) -> tuple[QRectF, list[ChipStack]]:
    stacks = chip_stacks(amount, quantum) if show_chips else []
    painter.save()
    painter.setFont(replay_font("DejaVu Sans", 9, QFont.Weight.DemiBold))
    metrics = painter.fontMetrics()
    label_width = metrics.horizontalAdvance(text) + 16
    label_height = max(38 if stacks else 32, metrics.height() + 8)
    diameter, gap = 32, 8 if stacks else 0
    stride = min(30, max(12, (max_width - label_width - gap - diameter) / max(1, len(stacks) - 1)))
    chips_width = diameter + (len(stacks) - 1) * stride if stacks else 0
    width = chips_width + gap + label_width
    offsets = sorted(
        ((x, y) for x in (0, -36, 36, -72, 72, -108, 108) for y in (0, -40, 40, -52, 52, -80, 80, -100, 100)),
        key=lambda offset: abs(offset[0]) + abs(offset[1]),
    )
    for offset_x, offset_y in offsets:
        candidate = QPointF(anchor.x() + offset_x, anchor.y() + offset_y)
        bounds = QRectF(candidate.x() - width / 2, candidate.y() - label_height / 2, width, label_height)
        if all(not bounds.intersects(region.adjusted(-4, -4, 4, 4)) for region in avoid):
            anchor = candidate
            break
    left = anchor.x() - width / 2
    if owner is not None:
        bounds = QRectF(left, anchor.y() - label_height / 2, width, label_height)
        endpoint = QPointF(
            max(bounds.left(), min(owner.x(), bounds.right())),
            max(bounds.top(), min(owner.y(), bounds.bottom())),
        )
        painter.setPen(QPen(QColor(184, 201, 207, 150), 1.5, Qt.PenStyle.DotLine))
        painter.drawLine(owner, endpoint)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#b8c9cf"))
        painter.drawEllipse(owner, 2, 2)
    for column, stack in enumerate(stacks):
        center_x = left + diameter / 2 + column * stride
        color = QColor(stack.color)
        rim = QColor("#3f474f") if color.lightness() > 170 else QColor("#e4e7e9")
        for number in range(stack.count):
            top = QRectF(center_x - diameter / 2, anchor.y() - 4 - number * 3, diameter, 19)
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
            inset = top.adjusted(5, 3, -5, -3)
            painter.drawEllipse(inset)
        _draw_denomination(painter, stack, top, color)
    painter.setFont(replay_font("DejaVu Sans", 9, QFont.Weight.DemiBold))
    label = QRectF(left + chips_width + gap, anchor.y() - label_height / 2, label_width, label_height)
    painter.setPen(QPen(QColor("#43505c"), 1))
    painter.setBrush(QColor(12, 20, 27, 235))
    painter.drawRoundedRect(label, 5, 5)
    painter.setPen(QColor("#f5f7fa"))
    painter.drawText(label, Qt.AlignmentFlag.AlignCenter, text)
    painter.restore()
    return QRectF(left, label.top(), width, label_height), stacks
