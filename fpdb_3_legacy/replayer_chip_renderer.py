"""Compact felt-side chip stacks and high-contrast monetary labels."""

from decimal import Decimal
from math import sqrt

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


def _inside_felt(bounds: QRectF, felt: QRectF | None) -> bool:
    if felt is None:
        return True
    rx, ry = felt.width() / 2, felt.height() / 2
    if rx <= 0 or ry <= 0:
        return False
    # Check the farthest corner, not merely the group's centre or the oval's
    # bounding box: either would allow chips and labels outside the felt.
    x = (abs(bounds.center().x() - felt.center().x()) + bounds.width() / 2) / rx
    y = (abs(bounds.center().y() - felt.center().y()) + bounds.height() / 2) / ry
    return x * x + y * y <= 1


def _felt_candidates(anchor: QPointF, width: float, height: float, felt: QRectF, xs: set[float], ys: set[float]) -> list[tuple[float, float]]:
    """Add positions along the curved boundary for the complete rectangle."""
    cx, cy = felt.center().x(), felt.center().y()
    rx, ry = felt.width() / 2, felt.height() / 2
    candidates: list[tuple[float, float]] = []
    if rx <= 0 or ry <= 0:
        return candidates
    for y in ys | {cy}:
        vertical = (abs(y - cy) + height / 2) / ry
        if vertical >= 1:
            continue
        dx = rx * sqrt(1 - vertical * vertical) - width / 2 - 1
        if dx >= 0:
            candidates.extend((x, y) for x in (cx - dx, cx + dx, max(cx - dx, min(anchor.x(), cx + dx))))
    for x in xs | {cx}:
        horizontal = (abs(x - cx) + width / 2) / rx
        if horizontal >= 1:
            continue
        dy = ry * sqrt(1 - horizontal * horizontal) - height / 2 - 1
        if dy >= 0:
            candidates.extend((x, y) for y in (cy - dy, cy + dy, max(cy - dy, min(anchor.y(), cy + dy))))
    return candidates


def _place_amount(anchor: QPointF, width: float, height: float, avoid: tuple[QRectF, ...], available: QRectF | None, felt: QRectF | None) -> QRectF:
    """Find a free rectangle; never fall back to an obstructed anchor."""
    obstacles = [region.adjusted(-4, -4, 4, 4) for region in avoid]
    offsets = sorted(
        ((x, y) for x in (0, -36, 36, -72, 72, -108, 108) for y in (0, -40, 40, -52, 52, -80, 80, -100, 100)),
        key=lambda offset: abs(offset[0]) + abs(offset[1]),
    )
    candidates = [(anchor.x() + x, anchor.y() + y) for x, y in offsets]
    # Every free rectangular cell has an edge at an obstacle or viewport
    # boundary. Search those edges if the nearby offsets are all occupied.
    xs, ys = {anchor.x()}, {anchor.y()}
    for region in obstacles:
        xs.update((region.left() - width / 2 - 1, region.right() + width / 2 + 1))
        ys.update((region.top() - height / 2 - 1, region.bottom() + height / 2 + 1))
    if available is not None:
        xs.update((available.left() + width / 2, available.right() - width / 2))
        ys.update((available.top() + height / 2, available.bottom() - height / 2))
    edge_candidates = [(x, y) for x in xs for y in ys]
    if felt is not None:
        edge_candidates.extend(_felt_candidates(anchor, width, height, felt, xs, ys))
    candidates.extend(edge_candidates)
    candidates.sort(key=lambda p: (p[0] - anchor.x()) ** 2 + (p[1] - anchor.y()) ** 2)
    for x, y in candidates:
        bounds = QRectF(x - width / 2, y - height / 2, width, height)
        if (available is None or available.contains(bounds)) and _inside_felt(bounds, felt) and all(not bounds.intersects(region) for region in obstacles):
            return bounds
    return QRectF()


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
    available: QRectF | None = None,
    felt: QRectF | None = None,
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
    bounds = _place_amount(anchor, width, label_height, avoid, available, felt)
    label_font = painter.font()
    if bounds.isNull() and not stacks:
        # Dense tables may have room for the exact value but not the regular
        # padding/type size. Keep every amount legible rather than dropping it.
        while bounds.isNull() and label_font.pointSizeF() > 9:
            label_font.setPointSizeF(max(9, label_font.pointSizeF() - 1))
            painter.setFont(label_font)
            label_width = painter.fontMetrics().horizontalAdvance(text) + 12
            label_height = painter.fontMetrics().height() + 6
            width = label_width
            bounds = _place_amount(anchor, width, label_height, avoid, available, felt)
    if bounds.isNull():
        painter.restore()
        if stacks:
            # Prefer the exact amount over decorative stacks in a crowded view.
            bounds, _ = draw_chip_amount(painter, amount, anchor, text, quantum, show_chips=False, avoid=avoid, available=available, felt=felt)
        return bounds, stacks
    anchor = bounds.center()
    left = bounds.left()
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
    painter.setFont(label_font)
    label = QRectF(left + chips_width + gap, anchor.y() - label_height / 2, label_width, label_height)
    painter.setPen(QPen(QColor("#43505c"), 1))
    painter.setBrush(QColor(12, 20, 27, 235))
    painter.drawRoundedRect(label, 5, 5)
    painter.setPen(QColor("#f5f7fa"))
    painter.drawText(label, Qt.AlignmentFlag.AlignCenter, text)
    painter.restore()
    return QRectF(left, label.top(), width, label_height), stacks
