"""Task-first application navigation inspired by analysis workspaces."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QLabel, QPushButton, QToolButton, QVBoxLayout, QWidget

from fpdb_3_legacy.design_system import ACCENT, modernize_stylesheet
from fpdb_3_legacy.i18n import gettext as _
from fpdb_3_legacy.ThemeManager import ThemeManager


def _icon(kind: str, active=False) -> QIcon:
    image = QPixmap(22, 22)
    image.fill(Qt.GlobalColor.transparent)
    with QPainter(image) as painter:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(ACCENT if active else "#a6afbc"), 1.6))
        if kind == "results":
            painter.drawLine(3, 18, 19, 18)
            for x, height in ((5, 7), (10, 12), (15, 15)):
                painter.drawRect(x, 18 - height, 3, height)
        elif kind == "hands":
            painter.drawRoundedRect(3, 3, 10, 15, 2, 2)
            painter.drawRoundedRect(9, 5, 10, 15, 2, 2)
        elif kind == "import":
            painter.drawLine(11, 2, 11, 14)
            painter.drawLine(6, 9, 11, 14)
            painter.drawLine(11, 14, 16, 9)
            painter.drawLine(3, 14, 3, 19)
            painter.drawLine(3, 19, 19, 19)
            painter.drawLine(19, 19, 19, 14)
        else:
            painter.drawRoundedRect(3, 3, 16, 16, 2, 2)
            painter.drawLine(3, 8, 19, 8)
            painter.drawLine(8, 8, 8, 19)
    return QIcon(image)


class ApplicationNavigation(QWidget):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.setObjectName("applicationNavigation")
        self.setFixedWidth(200)
        self.buttons = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 16, 10, 14)
        layout.setSpacing(6)
        brand = QLabel("FPDB")
        brand.setStyleSheet("font-size:18px; font-weight:700; padding:4px 10px 18px;")
        layout.addWidget(brand)
        for label, handler, tab, icon in (("Results", "tab_results", "Results", "results"),
                                         ("Hands", "tab_hand_viewer", "Hand Viewer", "hands"),
                                         ("Import", "tab_bulk_import", "Bulk Import", "import"),
                                         ("HUD / Live", "tab_auto_import", "HUD", "grid")):
            layout.addWidget(self._button(label, handler, tab, icon))
        advanced = QToolButton()
        self.advanced_toggle = advanced
        self.analysis_tabs = set()
        advanced.setText(_("Analysis"))
        advanced.setCheckable(True)
        advanced.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        advanced.setArrowType(Qt.ArrowType.RightArrow)
        layout.addWidget(advanced)
        self.advanced_panel = QWidget()
        extras = QVBoxLayout(self.advanced_panel)
        extras.setContentsMargins(0, 0, 0, 0)
        for label, handler, tab in (("Statistics", "tab_ring_player_stats", "Ring Player Stats"),
                                    ("Graphs", "tabGraphViewer", "Graphs"),
                                    ("Sessions", "tab_session_stats", "Session Stats"),
                                    ("Opponents", "tab_opponents_report", "Opponents Report"),
                                    ("Studies", "tab_study_explorer", "Study Explorer"),
                                    ("Research", "tab_research_browser", "Research Browser"),
                                    ("Tournaments", "tab_tourney_player_stats", "Tourney Stats")):
            extras.addWidget(self._button(label, handler, tab, "grid"))
            self.analysis_tabs.add(tab)
        self.advanced_panel.hide()
        advanced.toggled.connect(self.advanced_panel.setVisible)
        advanced.toggled.connect(lambda checked: advanced.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow))
        layout.addWidget(self.advanced_panel)
        layout.addStretch()
        foot = QLabel(_("Results → Hands → Replay"))
        foot.setWordWrap(True)
        foot.setStyleSheet("font-size:10px; color:#a6afbc; padding:8px;")
        layout.addWidget(foot)
        owner.nb.currentChanged.connect(self._selection_changed)
        self.refresh_theme()
        self._selection_changed(owner.nb.currentIndex())

    def _button(self, label, handler, tab, icon):
        button = QPushButton(_(label))
        button.setCheckable(True)
        button.setIcon(_icon(icon))
        button.setToolTip(_(tab))
        button.clicked.connect(lambda _checked: self.navigate(handler, tab))
        self.buttons[tab] = (button, icon)
        return button

    def navigate(self, handler: str, tab: str) -> None:
        if tab in self.owner.nb_tab_names:
            self.owner.display_tab(tab)
        else:
            getattr(self.owner, handler)(None)
        self._selection_changed(self.owner.nb.currentIndex())

    def _selection_changed(self, index) -> None:
        active = self.owner.nb.tabText(index) if index >= 0 else ""
        if active in self.analysis_tabs:
            self.advanced_toggle.setChecked(True)
        for tab, (button, icon) in self.buttons.items():
            button.setChecked(tab == active)
            button.setIcon(_icon(icon, tab == active))

    def refresh_theme(self, *_args) -> None:
        colors = ThemeManager().get_legacy_palette()
        self.setStyleSheet(modernize_stylesheet(f"""
            QWidget#applicationNavigation {{background:{colors['window']}; border-right:1px solid {colors['border']};}}
            QPushButton {{background:transparent; border:0; border-radius:5px; text-align:left;
                padding:10px; color:{colors['muted_text']}; min-height:20px; font-size:12px;}}
            QPushButton:hover {{background:{colors['panel']}; color:{colors['text']};}}
            QPushButton:checked {{background:{colors['selection']}; color:{ACCENT};}}
        """))
