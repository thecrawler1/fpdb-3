"""Shared analysis-tool styling: neutral surfaces, mint accent, 125% typography."""

import colorsys
import re
from pathlib import Path

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QLabel, QTableView, QWidget

TEXT_SCALE = 1.25
CARD_SCALE = 1.25
ACCENT = "#78d9a0"  # Same green as the replayer slider's sub-page.
STYLE_MARKER = "/* FPDB_TEXT_125 */"
HTML_MARKER = "<!-- FPDB_TEXT_125 -->"


def _purple(red: int, green: int, blue: int) -> bool:
    hue, saturation, _ = colorsys.rgb_to_hsv(red / 255, green / 255, blue / 255)
    return 250 <= hue * 360 <= 320 and saturation > .2


def modernize_stylesheet(stylesheet: str) -> str:
    """Scale explicit font sizes once, including local styles and rich text."""
    if not stylesheet:
        return stylesheet
    if STYLE_MARKER not in stylesheet and HTML_MARKER not in stylesheet:
        stylesheet = re.sub(
            r"(font-size\s*:\s*)(\d+(?:\.\d+)?)(px|pt)",
            lambda m: f"{m[1]}{float(m[2]) * TEXT_SCALE:g}{m[3]}", stylesheet,
        ) + "\n" + STYLE_MARKER

    def recolor(match):
        value = match[0]
        color = QColor(value)
        return ACCENT if value.lower() == "#8bc34a" or (color.isValid() and _purple(color.red(), color.green(), color.blue())) else value

    stylesheet = re.sub(r"#[0-9a-fA-F]{6}\b", recolor, stylesheet)

    def recolor_rgba(match):
        red, green, blue = (int(match[i]) for i in (1, 2, 3))
        return f"rgba(120, 217, 160, {match[4]})" if _purple(red, green, blue) or (red, green, blue) == (139, 195, 74) else match[0]

    return re.sub(r"rgba\(\s*(\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\s*\)", recolor_rgba, stylesheet)


def modernize_rich_text(text: str) -> str:
    return modernize_stylesheet(text).replace("\n" + STYLE_MARKER, HTML_MARKER).replace(STYLE_MARKER, HTML_MARKER)


def design_palette(dark: bool) -> dict[str, str]:
    window, base, panel, alternate = ("#101216", "#14181d", "#1b2128", "#222a32") if dark else (
        "#f3f6f4", "#ffffff", "#eaf0ec", "#e1e9e4")
    text, muted, border = ("#eef1f5", "#a6afbc", "#303640") if dark else ("#17261e", "#53685c", "#c7d4cc")
    selection = "#243d32" if dark else "#c9edda"
    return dict(window=window, base=base, sidebar=window, sidebar_panel=panel, surface=base,
                surface_panel=base, app_header=window, panel=panel, panel_alt=alternate,
                input=panel, input_hover=alternate, button=panel, button_hover=alternate,
                text=text, window_text=text, muted_text=muted, border=border, grid=border,
                accent=ACCENT, accent_soft=selection, accent_hover="#98e5b7", selection=selection,
                selection_soft=selection, highlighted_text=text, table_header=panel, table_header_hover=alternate,
                table_header_text=muted, tooltip=panel, tooltip_border=border, graph_purple="#70bca6")


def application_stylesheet(colors: dict[str, str]) -> str:
    """Consistent chrome/components applied after the compatibility theme."""
    assets = (Path(__file__).resolve().parent.parent / "gfx/ui").as_posix()
    return f"""
    QWidget {{ font-family: 'DejaVu Sans'; font-size: 15px; color: {colors['text']}; background-color: {colors['window']}; }}
    QMainWindow, QDialog {{ background: {colors['window']}; }}
    QMenuBar, QMenu, QStatusBar {{ background: {colors['window']}; color: {colors['text']}; }}
    QMenu::item:selected, QMenuBar::item:selected {{ background: {colors['selection']}; }}
    QPushButton#titleBarButton {{ border: 0; background: transparent; color: {colors['muted_text']}; padding: 0; min-height: 20px; }}
    QPushButton#titleBarButton:hover {{ background: {colors['panel_alt']}; color: {colors['text']}; }}
    QTabWidget::pane {{ border: 0; background: {colors['window']}; border-radius: 0; }}
    QTabBar::tab {{ padding: 10px 18px; background: transparent; color: {colors['muted_text']}; font-weight: 600; }}
    QTabBar::tab:selected, QTabBar::tab:selected:active, QTabBar::tab:selected:!active {{ color: {ACCENT}; border-bottom: 2px solid {ACCENT}; }}
    QFrame#statsSurface, QFrame#handsSurface, QFrame#graphSurface {{ border: 0; background: {colors['window']}; }}
    QHeaderView::section {{ background: {colors['table_header']}; color: {colors['muted_text']};
        font-size: 13.75px; padding: 9px 12px; border: 0; border-bottom: 1px solid {colors['border']}; }}
    QHeaderView::section:hover {{ background: {colors['panel_alt']}; color: {colors['text']}; }}
    QTableView, QTreeView, QTableWidget, QTreeWidget {{ background: {colors['base']};
        alternate-background-color: {colors['panel']}; border: 1px solid {colors['border']};
        gridline-color: transparent; selection-background-color: {colors['selection']}; selection-color: {colors['text']}; }}
    QTableView::item, QTableWidget::item, QTreeView::item {{ padding: 7px 10px; border: 0; }}
    QTableView::item:selected, QTableWidget::item:selected, QTreeView::item:selected {{ background: {colors['selection']}; color: {colors['text']}; }}
    QTableView::item:hover, QTableWidget::item:hover, QTreeView::item:hover {{ background: {colors['panel_alt']}; }}
    QPushButton, QToolButton {{ background: {colors['button']}; color: {colors['text']};
        border: 1px solid {colors['border']}; border-radius: 5px; padding: 6px 12px; min-height: 28px; }}
    QPushButton:hover, QToolButton:hover {{ background: {colors['button_hover']}; border-color: {ACCENT}; }}
    QPushButton:pressed, QToolButton:checked {{ background: {colors['selection']}; border-color: {ACCENT}; }}
    QPushButton:checked, QPushButton:checked:hover {{ background: {colors['selection']}; border-color: {ACCENT}; color: {colors['text']}; }}
    QPushButton[primaryAction='true'] {{ background: {colors['selection']}; border-color: {ACCENT}; }}
    QPushButton:disabled {{ color: {colors['muted_text']}; border-color: {colors['border']}; }}
    QLineEdit, QComboBox, QDateEdit, QSpinBox, QDoubleSpinBox {{ background: {colors['input']};
        color: {colors['text']}; border: 1px solid {colors['border']}; padding: 5px 9px; border-radius: 5px; min-height: 28px; }}
    QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QSpinBox:focus {{ border-color: {ACCENT}; }}
    QComboBox::down-arrow {{ image: url('{assets}/chevron-down.svg'); width: 12px; height: 12px; }}
    QGroupBox {{ border: 1px solid {colors['border']}; background: {colors['panel']}; border-radius: 6px; }}
    QGroupBox::title {{ color: {colors['muted_text']}; font-weight: 600; }}
    QCheckBox::indicator {{ width: 18px; height: 18px; background: {colors['input']}; border: 1px solid {colors['border']}; border-radius: 3px; image: none; }}
    QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; image: url('{assets}/check.svg'); }}
    QMenu::indicator {{ width: 18px; height: 18px; border:1px solid {colors['border']}; border-radius:3px; background:{colors['input']}; image:none; }}
    QMenu::indicator:checked {{ background:{ACCENT}; border-color:{ACCENT}; image:url('{assets}/check.svg'); }}
    QRadioButton::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
    QProgressBar::chunk, QSlider::sub-page:horizontal {{ background: {ACCENT}; }}
    QProgressBar {{ background: {colors['panel']}; border: 1px solid {colors['border']}; border-radius: 4px; text-align: center; }}
    QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{ background: {colors['border']}; }}
    QScrollBar::handle:hover {{ background: {ACCENT}; }}
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
                      (QPalette.ColorRole.Highlight, "selection"), (QPalette.ColorRole.HighlightedText, "text")):
        palette.setColor(role, QColor(colors[key]))
    app.setPalette(palette)
    if not hasattr(app, "_fpdb_design_filter"):
        app._fpdb_design_filter = DesignPolish(app)
        app.installEventFilter(app._fpdb_design_filter)
    for widget in app.allWidgets():
        app._fpdb_design_filter.polish_widget(widget)
