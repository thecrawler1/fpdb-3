"""Compact, stable decision information in the replay command area."""

from html import escape

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

from fpdb_3_legacy.localized_formats import format_number
from fpdb_3_legacy.replayer_decision import HeroDecision


def _cell(title: str, value: str, detail: str) -> str:
    return (f'<span style="font-size:12px; color:#a6afbc">{escape(title)}</span><br>'
            f'<span style="font-size:21px; font-weight:600">{escape(value)}</span><br>'
            f'<span style="font-size:12px; color:#a6afbc">{escape(detail)}</span>')


def _pct(value) -> str:
    return f"{format_number(value, 1)}%" if value is not None else "—"


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
        self.labels = [QLabel(self) for _ in range(3)]
        for label in self.labels:
            label.setWordWrap(True)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
            label.setStyleSheet("background:transparent; border:none;")
            layout.addWidget(label, 1)
        self.metrics = HeroDecision()

    def display(self, metrics: HeroDecision, amount) -> None:
        self.metrics = metrics
        context, defence = _cell("HERO", "—", ""), _cell("POT ODDS / MDF", "—", "")
        sizing = f"{_pct(metrics.bet_pct)} pot" if metrics.bet_pct is not None else ""
        if metrics.mode == "call":
            context = _cell("CALL", amount(metrics.call_amount), sizing)
            defence = _cell("POT ODDS", _pct(metrics.pot_odds_pct), "Minimum equity to call")
        elif metrics.mode == "bet":
            context = _cell("RAISE · NEW INVESTMENT" if metrics.action == "raises" else "BET", amount(metrics.bet_amount), sizing)
            defence = _cell("MDF · OPPONENT", _pct(metrics.mdf_pct),
                            f"Min. FE {_pct(metrics.fold_equity_pct)}" if metrics.mdf_pct is not None else "Multiway / not applicable")
        values = metrics.spr
        spr, effective = "—", "—"
        if values:
            low, high = min(values), max(values)
            stacks = [stack for _, stack in metrics.effective]
            spr = format_number(low, 2) if low == high else f"{format_number(low, 2)}–{format_number(high, 2)}"
            effective = amount(min(stacks)) if min(stacks) == max(stacks) else f"{amount(min(stacks))}–{amount(max(stacks))}"
        spr_cell = _cell(f"SPR · {metrics.street.upper()}".rstrip(" ·"), spr,
                         f"Effective {effective}" + (" · multiway" if len(values) > 1 else ""))
        for label, text in zip(self.labels, (context, defence, spr_cell)):
            if label.text() != text:
                label.setText(text)
        self.labels[0].setToolTip("Sizing = new investment / pot before the action. Raises include the call component.")
        self.labels[1].setToolTip("Pot odds use only pots Hero can win. Pure HU MDF = P/(P+B); min. bluff FE = B/(P+B). Risk is capped to the opponent's stack.")
        opponents = "\n".join(f"{name}: {amount(stack)}" for name, stack in metrics.effective)
        self.labels[2].setToolTip("SPR is fixed at the start of the displayed street, including turn/river.\n"
                                  f"Street-start pot: {amount(metrics.street_pot)}\n{opponents}")
