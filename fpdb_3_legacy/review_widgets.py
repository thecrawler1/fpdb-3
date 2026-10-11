"""Small review-workspace components for hierarchy, disclosure and clear states."""

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout, QWidget

from fpdb_3_legacy.design_system import current_palette, modernize_stylesheet
from fpdb_3_legacy.i18n import gettext as _


def game_label(category: str) -> str:
    names = {
        "holdem": "Hold'em", "6_holdem": "Short Deck Hold'em", "2_holdem": "Double Hold'em",
        "omahahi": "Omaha", "omahahilo": "Omaha Hi/Lo", "5_omahahi": "5 Card Omaha",
        "5_omaha8": "5 Card Omaha Hi/Lo", "6_omahahi": "6 Card Omaha", "6_omaha8": "6 Card Omaha Hi/Lo",
        "cour_hi": "Courchevel", "cour_hilo": "Courchevel Hi/Lo", "fusion": "Fusion", "irish": "Irish",
        "aof_holdem": "All-in or Fold Hold'em", "aof_omaha": "All-in or Fold Omaha",
        "studhi": "7 Card Stud", "studhilo": "7 Card Stud Hi/Lo", "razz": "Razz",
        "27_1draw": "2-7 Single Draw", "27_3draw": "2-7 Triple Draw", "a5_1draw": "A-5 Single Draw",
        "a5_3draw": "A-5 Triple Draw", "fivedraw": "5 Card Draw", "badugi": "Badugi",
        "badacey": "Badacey", "badeucey": "Badeucey", "drawmaha": "2-7 Drawmaha", "27_razz": "2-7 Razz",
    }
    return _(names.get(category, category.replace("_", " ").title()))


def review_stylesheet() -> str:
    c = current_palette()
    return modernize_stylesheet(f"""
        QLabel[reviewText='title'] {{font-size:20px; font-weight:600; color:{c['text']};}}
        QLabel[reviewText='heading'] {{font-size:13px; font-weight:600; color:{c['text']};}}
        QLabel[reviewText='caption'] {{font-size:10px; color:{c['muted_text']}; background:transparent;}}
        QWidget#reviewSegments {{background:{c['base']}; border:1px solid {c['border']}; border-radius:6px;}}
        QToolButton[reviewSegment='true'] {{background:transparent; border:0; border-radius:4px;
            padding:5px 9px; min-height:24px; min-width:30px; color:{c['muted_text']};}}
        QToolButton[reviewSegment='true']:hover {{background:{c['panel_alt']}; padding:5px 9px; border:0;}}
        QToolButton[reviewSegment='true']:checked {{background:{c['selection']}; color:{c['text']}; font-weight:600;}}
        QToolButton[reviewChip='true'] {{background:{c['panel']}; border:1px solid {c['border']};
            border-radius:12px; padding:3px 9px; min-height:18px; color:{c['text']};}}
        QToolButton[reviewChip='true']:hover {{background:{c['panel_alt']}; border-color:{c['accent']}; padding:3px 9px;}}
        QToolButton[reviewQuiet='true'] {{background:transparent; border:0; padding:3px 6px;
            min-height:20px; color:{c['muted_text']};}}
        QToolButton[reviewQuiet='true']:hover {{background:{c['panel']}; color:{c['text']}; border:0; padding:3px 6px;}}
        QPushButton[primaryAction='true'] {{background:{c['selection']}; border:1px solid {c['accent']}; color:{c['text']};}}
        QPushButton[primaryAction='true']:hover {{background:{c['selection_hover']}; border-color:{c['accent']}; color:{c['text']};}}
        QPushButton[primaryAction='true']:disabled {{background:{c['panel']}; border-color:{c['border']}; color:{c['disabled_text']};}}
        QWidget#reviewEmptyState, QWidget#reviewEmptyState QLabel {{background:transparent;}}
        QWidget#handSelectionBar {{border-top:1px solid {c['border']};}}
    """)


def text_label(text: str, role: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("reviewText", role)
    return label


def labeled_control(title: str, control) -> QWidget:
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(3)
    caption = text_label(title, "caption")
    caption.setBuddy(control)
    layout.addWidget(caption)
    layout.addWidget(control)
    return container


class SegmentedControl(QWidget):
    """Visible choices backed by the existing combo, keeping one source of state."""

    def __init__(self, combo, parent=None):
        super().__init__(parent)
        self.setObjectName("reviewSegments")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(review_stylesheet())
        combo.setParent(self)
        combo.hide()
        self.group = QButtonGroup(self)
        self.buttons = []
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)
        for index in range(combo.count()):
            button = QToolButton()
            button.setText(combo.itemText(index))
            button.setAccessibleName(combo.itemText(index))
            button.setProperty("reviewSegment", True)
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, row=index: combo.setCurrentIndex(row))
            self.group.addButton(button, index)
            self.buttons.append(button)
            layout.addWidget(button)
        combo.currentIndexChanged.connect(self._sync)
        self._sync(combo.currentIndex())

    def _sync(self, index):
        button = self.group.button(index)
        if button is not None:
            button.setChecked(True)


class FilterChips(QWidget):
    """Show removable filters outside a collapsed filter panel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(review_stylesheet())
        self.buttons = {}
        self.callbacks: dict[str, Callable[[], Any]] = {}
        self.layout_row = QHBoxLayout(self)
        self.layout_row.setContentsMargins(0, 0, 0, 0)
        self.layout_row.setSpacing(6)
        self.layout_row.addWidget(text_label(_("Active filters"), "caption"))
        self.clear_button = QToolButton()
        self.clear_button.setText(_("Clear filters"))
        self.clear_button.setProperty("reviewQuiet", True)
        self.clear_button.clicked.connect(lambda: self.callbacks.get('clear', lambda: None)())
        self.layout_row.addWidget(self.clear_button)
        self.layout_row.addStretch()
        self.hide()

    def set_entries(self, entries, clear):
        keys = {key for key, _label, _callback in entries}
        for key, button in self.buttons.items():
            button.setVisible(key in keys)
        for index, (key, label, callback) in enumerate(entries):
            if key not in self.buttons:
                button = QToolButton()
                button.setProperty("reviewChip", True)
                button.clicked.connect(lambda _checked=False, name=key: self.callbacks[name]())
                self.buttons[key] = button
            button = self.buttons[key]
            self.callbacks[key] = callback
            button.setText(label + "  ×")
            button.setToolTip(_("Remove filter: ") + label)
            button.setAccessibleName(_("Remove filter: ") + label)
            self.layout_row.insertWidget(index + 1, button)
            button.show()
        self.callbacks['clear'] = clear
        self.setVisible(bool(entries))


class EmptyState(QWidget):
    """An inline, actionable state centred in a table viewport."""

    def __init__(self, view):
        super().__init__(view.viewport())
        self.setObjectName("reviewEmptyState")
        self.setStyleSheet(review_stylesheet())
        self.callback: Callable[[], Any] | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.addStretch()
        self.title = text_label("", "heading")
        self.description = text_label("", "caption")
        for label in (self.title, self.description):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setWordWrap(True)
            layout.addWidget(label)
        actions = QHBoxLayout()
        actions.addStretch()
        self.action = QPushButton()
        self.action.setProperty("primaryAction", True)
        self.action.clicked.connect(lambda: self.callback() if self.callback else None)
        actions.addWidget(self.action)
        actions.addStretch()
        layout.addLayout(actions)
        layout.addStretch()
        view.viewport().installEventFilter(self)
        self.hide()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize:
            self.setGeometry(watched.rect())
        return False

    def show_message(self, title, description, action="", callback=None):
        self.title.setText(title)
        self.description.setText(description)
        self.action.setText(action)
        self.action.setVisible(bool(action and callback))
        self.callback = callback
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
        self.show()
        self.raise_()
