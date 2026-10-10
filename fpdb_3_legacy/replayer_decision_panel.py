"""Two fixed headings and values for the player currently facing a decision."""

from html import escape

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

from fpdb_3_legacy.localized_formats import format_number
from fpdb_3_legacy.replayer_decision import HeroDecision


def _cell(title: str, value: str) -> str:
    return (f'<span style="font-size:12px; color:#a6afbc">{escape(title)}</span><br>'
            f'<span style="font-size:21px; font-weight:600">{escape(value)}</span>')


def _pct(value) -> str:
    return f"{_number(value, 1)}%" if value is not None else "—"


def _number(value, decimals: int) -> str:
    return format_number(value, decimals).rstrip("0").rstrip(".,")


class DecisionPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("decisionPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(76)
        self.setStyleSheet("QWidget#decisionPanel {background:#171e24; border:none; border-radius:0px;}")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(22, 5, 22, 5)
        layout.setSpacing(16)
        self.labels = [QLabel(self) for _ in range(2)]
        for label in self.labels:
            label.setWordWrap(True)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
            label.setStyleSheet("background:transparent; border:none;")
            layout.addWidget(label, 1)
        self.metrics = HeroDecision()
        self.actor: str | None = None

    def display(self, metrics: HeroDecision, actor: str | None = None) -> None:
        self.metrics = metrics
        self.actor = actor
        values = metrics.spr
        spr = "—"
        if values:
            low, high = min(values), max(values)
            first, last = _number(low, 2), _number(high, 2)
            spr = first if first == last else f"{first}–{last}"
        for label, text in zip(self.labels, (_cell("POT ODDS", _pct(metrics.pot_odds_pct)), _cell("SPR", spr))):
            if label.text() != text:
                label.setText(text)
