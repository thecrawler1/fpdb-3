"""Shared analysis-tool styling: neutral surfaces, mint accent, 125% typography."""

import re
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QAbstractItemView, QApplication, QComboBox, QLabel, QTableView, QWidget
from shiboken6 import isValid

from fpdb_3_legacy.color_tokens import ACCENT as ACCENT
from fpdb_3_legacy.color_tokens import semantic_palette

TEXT_SCALE = 1.25
CARD_SCALE = 1.25
STYLE_MARKER = "/* FPDB_TEXT_125 */"
HTML_MARKER = "<!-- FPDB_TEXT_125 -->"


def modernize_stylesheet(stylesheet: str) -> str:
    """Scale explicit font sizes once, including local styles and rich text."""
    if not stylesheet:
        return stylesheet
    if STYLE_MARKER not in stylesheet and HTML_MARKER not in stylesheet:
        stylesheet = re.sub(
            r"(font-size\s*:\s*)(\d+(?:\.\d+)?)(px|pt)",
            lambda m: f"{m[1]}{float(m[2]) * TEXT_SCALE:g}{m[3]}", stylesheet,
        ) + "\n" + STYLE_MARKER

    colors = current_palette()
    aliases = legacy_color_aliases(colors)
    # White backgrounds embedded in legacy dialogs are much brighter than the
    # surrounding dark workspace. Treat background and foreground separately.
    stylesheet = re.sub(
        r"(background(?:-color)?\s*:\s*)(#ffffff\b|#fff\b|white\b)",
        lambda match: match[1] + colors["panel"], stylesheet, flags=re.IGNORECASE,
    )
    stylesheet = re.sub(r"(background(?:-color)?\s*:\s*)(#000000\b|#000\b|black\b)",
                        lambda match: match[1] + colors["window"], stylesheet, flags=re.IGNORECASE)
    stylesheet = re.sub(r"(?<![-\w])(color\s*:\s*)(white|black|#fff|#000)\b",
                        lambda match: match[1] + colors["text"], stylesheet, flags=re.IGNORECASE)

    def recolor(match):
        value = match[0]
        if value.lower() in colors.values():
            return value
        if value.lower() in aliases:
            return aliases[value.lower()]
        return value

    stylesheet = re.sub(r"#[0-9a-fA-F]{6}\b", recolor, stylesheet)

    def recolor_rgba(match):
        red, green, blue = (int(match[i]) for i in (1, 2, 3))
        old = f"#{red:02x}{green:02x}{blue:02x}"
        if old in aliases:
            mapped = QColor(aliases[old])
            return f"rgba({mapped.red()}, {mapped.green()}, {mapped.blue()}, {match[4]})"
        return match[0]

    return re.sub(r"rgba\(\s*(\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\s*\)", recolor_rgba, stylesheet)


def modernize_rich_text(text: str) -> str:
    return modernize_stylesheet(text).replace("\n" + STYLE_MARKER, HTML_MARKER).replace(STYLE_MARKER, HTML_MARKER)


def design_palette(dark: bool) -> dict[str, str]:
    return semantic_palette(dark)


def current_palette() -> dict[str, str]:
    app = QApplication.instance()
    mode = app.property("fpdb_color_mode") if app else None
    return design_palette(mode != "light")


def legacy_color_aliases(colors: dict[str, str]) -> dict[str, str]:
    """Migrate known old UI colours by role, preserving unknown/domain colours."""
    groups = {
        "window": "#101216 #0f172a #111827 #121212 #181818 #1a202c #2d3748 #30363c",
        "base": "#14181d #1b2026 #1e293b #222b32 #20262b #22262e #11161c",
        "panel": "#1b2128 #242b32 #252a32 #2b2b2b #333333 #212121 #232629",
        "panel_alt": "#222a32 #334155 #404040 #444444",
        "text": "#ffffff #edf2f7 #eef1f5 #eef3f7 #f8fafc #e6edf3 #e0e0e0 #cccccc #c4cdd4 #f5f7fa #000000",
        "muted_text": "#a6afbc #a0aec0 #94a3b8 #9aa5ad #aeb8c2 #9da9b5 #9e9e9e #a0a0a0 #888888",
        "border": "#303640 #4a5568 #475569 #4f5b62",
        "accent": "#8bc34a #78d9a0 #98e5b7 #319795 #4fd1c5 #03dac6 #b64fd8 #a78bfa #6200ee #bb86fc #8b5cf6 #d45aff #d65aff #9c27b0",
        "selection": "#243d32 #c9edda #bef67a",
        "success": "#22c55e #48bb78 #68d391 #3fb56b #4caf50 #2e7d32 #15803d #14843b #00ff00 #00c853 #98c379",
        "danger": "#ef4444 #f56565 #fc8181 #d66b6b #ff3333 #f44336 #d32f2f #c62828 #ff0000 #e06c75",
        "info": "#3182ce #14a8ff #61afef #2196f3 #38bdf8 #006db4 #3f51b5",
        "warning": "#f59e3d #ffb000 #ffb74d #ffd34d #ffe769 #ff9800 #dd6b20 #a15c00 #e5c07b",
    }
    aliases = {old: colors[role] for role, values in groups.items() for old in values.split()}
    for previous in (design_palette(True), design_palette(False)):
        for role, value in previous.items():
            if role != "on_accent":
                # Shared source values (e.g. light text and spades) must keep
                # their primary UI role when migrating a stylesheet.
                aliases.setdefault(value, colors[role])
    return aliases


def application_stylesheet(colors: dict[str, str]) -> str:
    """Consistent chrome/components applied after the compatibility theme."""
    assets = (Path(__file__).resolve().parent.parent / "gfx/ui").as_posix()
    check = "check.svg" if colors['on_accent'] == colors['window'] else "check-light.svg"
    chevron = "chevron-down.svg" if colors['on_accent'] == colors['window'] else "chevron-down-light.svg"
    return f"""
    QWidget {{ font-family: 'DejaVu Sans'; font-size: 15px; color: {colors['text']}; background-color: {colors['window']}; }}
    QMainWindow, QDialog {{ background: {colors['window']}; }}
    QMenuBar, QMenu, QStatusBar {{ background: {colors['window']}; color: {colors['text']}; }}
    QMenu::item:selected, QMenuBar::item:selected {{ background: {colors['selection']}; }}
    QComboBox::item {{ color: {colors['text']}; background: {colors['panel']}; }}
    QComboBox::item:selected {{ background: {colors['selection']}; color: {colors['text']}; }}
    QPushButton#titleBarButton {{ border: 0; background: transparent; color: {colors['muted_text']}; padding: 0; min-height: 20px; }}
    QPushButton#titleBarButton:hover {{ background: {colors['panel_alt']}; color: {colors['text']}; }}
    QTabWidget::pane {{ border: 0; background: {colors['window']}; border-radius: 0; }}
    QTabBar::tab {{ padding: 10px 18px; background: transparent; color: {colors['muted_text']}; font-weight: 600; }}
    QTabBar::tab:selected, QTabBar::tab:selected:active, QTabBar::tab:selected:!active {{ color: {colors['accent']}; border-bottom: 2px solid {colors['accent']}; }}
    QFrame#statsSurface, QFrame#handsSurface, QFrame#graphSurface {{ border: 0; background: {colors['window']}; }}
    QHeaderView::section {{ background: {colors['table_header']}; color: {colors['muted_text']};
        font-size: 13.75px; padding: 9px 12px; border: 0; border-bottom: 1px solid {colors['border']}; }}
    QHeaderView::section:hover {{ background: {colors['panel_alt']}; color: {colors['text']}; }}
    QTableView, QTreeView, QTableWidget, QTreeWidget, QListView {{ background: {colors['base']};
        alternate-background-color: {colors['panel']}; border: 1px solid {colors['border']};
        gridline-color: transparent; selection-background-color: {colors['selection']}; selection-color: {colors['text']}; }}
    QTableView::item, QTableWidget::item, QTreeView::item {{ padding: 7px 10px; border: 0; }}
    QTableView::item:selected, QTableView::item:selected:active, QTableView::item:selected:!active,
    QTableView::item:selected:hover, QTableView::item:selected:focus,
    QTableWidget::item:selected, QTreeView::item:selected, QTreeView::item:selected:focus,
    QTreeView::item:selected:active, QTreeView::item:selected:!active, QTreeView::item:selected:hover,
    QListView::item:selected, QListView::item:selected:focus, QListView::item:selected:hover {{ background: {colors['selection']}; color: {colors['text']}; }}
    QTableView::item:hover, QTableWidget::item:hover, QTreeView::item:hover {{ background: {colors['panel_alt']}; }}
    QPushButton, QToolButton {{ background: {colors['button']}; color: {colors['text']};
        border: 1px solid {colors['border']}; border-radius: 5px; padding: 6px 12px; min-height: 28px; }}
    QPushButton:hover, QToolButton:hover {{ background: {colors['button_hover']}; border:1px solid {colors['accent']}; border-image:none; padding:6px 12px; }}
    QToolButton, QToolButton:hover:!pressed, QToolButton:focus, QToolButton:checked {{ border-image:none; outline:none; margin:0;
        border:1px solid {colors['border']}; border-radius:5px; padding:6px 12px; color:{colors['text']}; }}
    QToolButton:hover:!pressed {{ background:{colors['button_hover']}; border-color:{colors['accent']}; }}
    QToolButton:focus, QPushButton:focus {{ border-color:{colors['accent']}; }}
    QToolButton::menu-indicator {{ image:url('{assets}/{chevron}'); width:10px; height:10px; subcontrol-position:right center; subcontrol-origin:padding; }}
    QPushButton:pressed, QToolButton:checked {{ background: {colors['selection']}; border-color: {colors['accent']}; }}
    QPushButton:checked, QPushButton:checked:hover {{ background: {colors['selection']}; border-color: {colors['accent']}; color: {colors['text']}; }}
    QPushButton[primaryAction='true'] {{ background: {colors['selection']}; border-color: {colors['accent']}; }}
    QPushButton:disabled {{ color: {colors['disabled_text']}; border-color: {colors['border']}; }}
    QLineEdit, QComboBox, QDateEdit, QSpinBox, QDoubleSpinBox {{ background: {colors['input']};
        color: {colors['text']}; border: 1px solid {colors['control_border']}; padding: 5px 9px; border-radius: 5px; min-height: 28px; }}
    QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QSpinBox:focus {{ border-color: {colors['accent']}; }}
    QComboBox {{ padding-right: 30px; }}
    QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: top right;
        width: 24px; border: 0; background: transparent; }}
    QComboBox::down-arrow {{ image: url('{assets}/{chevron}'); width: 12px; height: 12px; }}
    QComboBox QAbstractItemView {{ background: {colors['panel']}; color: {colors['text']};
        border: 1px solid {colors['border']}; outline: 0;
        selection-background-color: {colors['selection']}; selection-color: {colors['text']}; }}
    QComboBox QAbstractItemView::item {{ padding: 8px 12px; min-height: 28px; }}
    QComboBox QAbstractItemView::item:selected {{ background: {colors['selection']}; color: {colors['text']}; }}
    QGroupBox {{ border: 1px solid {colors['border']}; background: {colors['panel']}; border-radius: 6px; }}
    QGroupBox::title {{ color: {colors['muted_text']}; font-weight: 600; }}
    QCheckBox::indicator {{ width: 18px; height: 18px; background: {colors['input']}; border: 1px solid {colors['control_border']}; border-radius: 3px; image: none; }}
    QCheckBox::indicator:checked {{ background: {colors['accent']}; border-color: {colors['accent']}; image: url('{assets}/{check}'); }}
    QMenu::indicator {{ width: 18px; height: 18px; border:1px solid {colors['control_border']}; border-radius:3px; background:{colors['input']}; image:none; }}
    QMenu::indicator:checked {{ background:{colors['accent']}; border-color:{colors['accent']}; image:url('{assets}/{check}'); }}
    QRadioButton::indicator {{ width:18px; height:18px; background:{colors['input']}; border:1px solid {colors['control_border']}; border-radius:9px; image:none; }}
    QRadioButton::indicator:checked {{ background: {colors['accent']}; border-color: {colors['accent']}; }}
    QProgressBar::chunk, QSlider::sub-page:horizontal {{ background: {colors['accent']}; }}
    QProgressBar {{ background: {colors['panel']}; border: 1px solid {colors['border']}; border-radius: 4px; text-align: center; }}
    QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{ background: {colors['control_border']}; }}
    QScrollBar::handle:hover {{ background: {colors['accent']}; }}
    {STYLE_MARKER}
    """


def _calendar_child(widget) -> bool:
    parent = widget
    while parent is not None:
        if parent.__class__.__name__ == "QCalendarWidget":
            return True
        parent = parent.parent()
    return False


class DesignPolish(QObject):
    """Keep legacy per-widget styles and newly opened views on the same system."""

    def __init__(self, app):
        super().__init__(app)
        self.busy = False

    def eventFilter(self, watched, event):
        if self.busy or not isinstance(watched, QWidget):
            return False
        kind = event.type()
        if kind not in (QEvent.Type.Polish, QEvent.Type.Show, QEvent.Type.StyleChange, QEvent.Type.Paint):
            return False
        self.busy = True
        try:
            if kind != QEvent.Type.Paint:
                self.polish_widget(watched)
            if kind == QEvent.Type.Show and isinstance(watched, QAbstractItemView):
                self.fit_combo_popup(watched)
                # QComboBox applies its final popup geometry after the view's Show.
                QTimer.singleShot(0, lambda view=watched: self.fit_combo_popup(view) if isValid(view) else None)
            if isinstance(watched, QLabel) and "font-size" in watched.text() and "<" in watched.text():
                text = modernize_rich_text(watched.text())
                if text != watched.text():
                    watched.setText(text)
            if kind == QEvent.Type.Paint:
                self.polish_plot(watched)
        except (RuntimeError, AttributeError, TypeError):
            # Qt can deliver final style events while a view/model is being
            # destroyed; do not resurrect it or mutate a deleted C++ wrapper.
            pass
        finally:
            self.busy = False
        return False

    def polish_widget(self, widget) -> None:
        style = widget.styleSheet()
        updated = modernize_stylesheet(style)
        if style != updated:
            widget.setStyleSheet(updated)
        if isinstance(widget, QTableView) and not _calendar_child(widget):
            widget.setShowGrid(False)
            widget.setAlternatingRowColors(True)
            from fpdb_3_legacy.table_columns import install_column_controls

            install_column_controls(widget)

    @staticmethod
    def fit_combo_popup(view) -> None:
        """Size dropdowns from their styled items, even when the field is narrow."""
        combo = view.parentWidget()
        while combo is not None and not isinstance(combo, QComboBox):
            combo = combo.parentWidget()
        if combo is None or combo.view() is not view:
            return
        column = combo.modelColumn()
        model = combo.model()
        metrics = view.fontMetrics()
        content_width = max(view.sizeHintForColumn(column), max(
            (metrics.horizontalAdvance(str(model.index(row, column, combo.rootModelIndex()).data() or ""))
             for row in range(model.rowCount(combo.rootModelIndex()))), default=0,
        ))
        # The native menu delegate also reserves a checkmark gutter (in addition
        # to stylesheet padding), which sizeHintForColumn can omit entirely.
        width = max(combo.width(), content_width + 64 + view.verticalScrollBar().sizeHint().width())
        popup = view.window()
        screen = combo.screen().availableGeometry()
        width = min(width, screen.width())
        view.setTextElideMode(Qt.TextElideMode.ElideNone)
        view.setMinimumWidth(max(0, width - 2 * popup.contentsMargins().left()))
        popup.resize(width, popup.height())
        popup.move(max(screen.left(), min(popup.x(), screen.right() - width + 1)), popup.y())

    @staticmethod
    def polish_plot(widget) -> None:
        parent = widget
        while parent is not None and not callable(getattr(parent, "getPlotItem", None)):
            parent = parent.parent()
        if parent is None:
            return
        item = parent.getPlotItem()
        title = item.titleLabel.text
        if isinstance(title, str) and "font-size" in title and HTML_MARKER not in title:
            item.titleLabel.setText(modernize_rich_text(title))
        for name in ("left", "bottom", "right", "top"):
            axis = item.getAxis(name)
            styles = dict(axis.labelStyle)
            size = styles.get("font-size")
            previous = getattr(axis, "_fpdb_scaled_size", None)
            if size and size != previous:
                match = re.fullmatch(r"([\d.]+)(px|pt)", size)
                if match:
                    styles["font-size"] = f"{float(match[1]) * TEXT_SCALE:g}{match[2]}"
                    axis._fpdb_scaled_size = styles["font-size"]
                    axis.setLabel(axis.labelText, units=axis.labelUnits, **styles)


def install_design(app: QApplication, colors: dict[str, str]) -> None:
    app.setProperty("fpdb_color_mode", "dark" if QColor(colors['window']).lightnessF() < .5 else "light")
    baseline = app.property("fpdb_base_font")
    if baseline is None:
        baseline = app.font().toString()
        app.setProperty("fpdb_base_font", baseline)
    font = QFont()
    font.fromString(baseline)
    font.setFamily("DejaVu Sans")
    if font.pointSizeF() > 0:
        font.setPointSizeF(font.pointSizeF() * TEXT_SCALE)
    else:
        font.setPixelSize(round(font.pixelSize() * TEXT_SCALE))
    app.setFont(font)
    palette = app.palette()
    for role, key in ((QPalette.ColorRole.Window, "window"), (QPalette.ColorRole.Base, "base"),
                       (QPalette.ColorRole.Text, "text"), (QPalette.ColorRole.WindowText, "text"),
                       (QPalette.ColorRole.Button, "button"), (QPalette.ColorRole.ButtonText, "text"),
                       (QPalette.ColorRole.AlternateBase, "panel"), (QPalette.ColorRole.PlaceholderText, "muted_text"),
                       (QPalette.ColorRole.ToolTipBase, "tooltip"), (QPalette.ColorRole.ToolTipText, "text"),
                       (QPalette.ColorRole.Link, "accent"), (QPalette.ColorRole.LinkVisited, "info"),
                       (QPalette.ColorRole.BrightText, "danger"),
                       (QPalette.ColorRole.Highlight, "selection"), (QPalette.ColorRole.HighlightedText, "text")):
        palette.setColor(role, QColor(colors[key]))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(colors['disabled_text']))
    app.setPalette(palette)
    if not hasattr(app, "_fpdb_design_filter"):
        app._fpdb_design_filter = DesignPolish(app)
        app.installEventFilter(app._fpdb_design_filter)
    for widget in app.allWidgets():
        app._fpdb_design_filter.polish_widget(widget)
