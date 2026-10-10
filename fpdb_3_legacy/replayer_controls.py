"""Vector transport buttons with immediate, bounded press feedback."""

from PySide6.QtCore import QEasingCurve, QPointF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QPushButton


def transport_icon(kind: str) -> QIcon:
    image = QPixmap(64, 64)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#f4f5f7"), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(QColor("#f4f5f7"))
    backwards = kind in {"previous", "start", "previous-hand"}
    if backwards:
        painter.translate(64, 0)
        painter.scale(-1, 1)
    if kind in {"previous", "next"}:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(15, 32, 47, 32)
        painter.drawPolyline(QPolygonF([QPointF(33, 18), QPointF(47, 32), QPointF(33, 46)]))
    elif kind in {"previous-hand", "next-hand"}:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for x in (15, 32):
            painter.drawPolyline(QPolygonF([QPointF(x, 16), QPointF(x + 17, 32), QPointF(x, 48)]))
    else:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(QPolygonF([QPointF(18, 13), QPointF(48, 32), QPointF(18, 51)]))
        if kind in {"start", "end"}:
            painter.drawRoundedRect(49, 13, 5, 38, 2, 2)
    painter.end()
    return QIcon(image)


class ReplayControlButton(QPushButton):
    """Native release-to-click semantics; only the icon animates, never the hit area."""

    def __init__(self, kind: str, label: str, parent=None):
        super().__init__(parent)
        self.setIcon(transport_icon(kind))
        self.setIconSize(QSize(30, 30))
        self.setAccessibleName(label)
        self.setToolTip(label)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("transport", True)
        self.setProperty("primary", kind in {"previous", "next"})
        self.setFixedSize(70 if kind in {"previous", "next"} else 44, 58 if kind in {"previous", "next"} else 44)
        self.press_progress = 0.0
        self._feedback = QVariantAnimation(self)
        self._feedback.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._feedback.valueChanged.connect(self._apply_feedback)
        self.pressed.connect(lambda: self._animate(1.0, 80))
        self.released.connect(lambda: self._animate(0.0, 130))

    def _animate(self, target: float, duration: int) -> None:
        self._feedback.stop()
        self._feedback.setStartValue(self.press_progress)
        self._feedback.setEndValue(target)
        self._feedback.setDuration(duration)
        self._feedback.start()

    def _apply_feedback(self, value) -> None:
        self.press_progress = float(value)
        size = round(30 - 4 * self.press_progress)
        self.setIconSize(QSize(size, size))
