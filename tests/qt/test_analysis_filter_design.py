"""Real filter geometry and date semantics, not just stylesheet snapshots."""

import pytest
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QLabel, QPushButton, QScrollArea

from fpdb_3_legacy.Filters import Filters
from fpdb_3_legacy.ThemeManager import ThemeManager

pytestmark = pytest.mark.qt


@pytest.fixture
def filters(qtbot, fresh_db, legacy_config):
    for site in legacy_config.supported_sites.values():
        site.enabled = False
    legacy_config.supported_sites['PokerStars'].enabled = True
    legacy_config.supported_sites['PokerStars'].screen_name = "Hero"
    widget = Filters(fresh_db, {"Heroes": True, "Sites": True, "Games": True, "Currencies": True,
                               "Limits": True, "Seats": True, "Groups": True, "GroupsAll": True,
                               "Dates": True, "Button1": True})
    qtbot.addWidget(widget)
    return widget


@pytest.fixture
def presentation_theme(qapp):
    style, palette, font = qapp.styleSheet(), qapp.palette(), qapp.font()
    previous_filter = getattr(qapp, "_fpdb_design_filter", None)
    properties = {key: qapp.property(key) for key in ("fpdb_color_mode", "fpdb_base_font", "fpdb_material_source", "fpdb_qt_material_theme")}
    ThemeManager().set_qt_material_theme("dark_lightgreen.xml", save=False, apply_to_ui=True)
    yield
    if previous_filter is None and hasattr(qapp, "_fpdb_design_filter"):
        qapp.removeEventFilter(qapp._fpdb_design_filter)
        del qapp._fpdb_design_filter
    qapp.setStyleSheet(style)
    qapp.setPalette(palette)
    qapp.setFont(font)
    for key, value in properties.items():
        qapp.setProperty(key, value)


def test_sections_do_not_expand_into_large_empty_cards(filters, qtbot, presentation_theme):
    area = QScrollArea()
    qtbot.addWidget(area)
    area.setWidgetResizable(True)
    area.setWidget(filters)
    area.resize(340, 1200)
    area.show()
    qtbot.wait(20)
    sections = [child for child in filters.children() if getattr(child, "objectName", lambda: "")() == "filterSection"]
    assert sections
    assert max(section.height() for section in sections) < 260
    titles = [label.text() for label in filters.findChildren(QLabel) if label.objectName() == "filterTitle"]
    assert titles and all(not title.endswith(":") for title in titles)
    assert all(title[0].isalpha() for title in titles)
    assert area.horizontalScrollBar().maximum() == 0
    area.takeWidget()


def test_date_presets_preserve_all_history_and_custom_dates_are_unambiguous(filters):
    original = filters.getDates()
    assert filters.date_preset.currentData() == "all" and filters.custom_dates.isHidden()
    filters.date_preset.setCurrentIndex(filters.date_preset.findData("today"))
    assert filters.start_date.date() == filters.end_date.date() == QDate.currentDate()
    filters.date_preset.setCurrentIndex(filters.date_preset.findData("all"))
    assert filters.getDates() == original
    filters.date_preset.setCurrentIndex(filters.date_preset.findData("custom"))
    assert not filters.custom_dates.isHidden()
    assert filters.start_date.date().year() == QDate.currentDate().year()
    filters.end_date.setDate(QDate(2100, 1, 1))
    assert "2100" in filters.end_date.text()
    assert filters.start_date.calendarPopup() and filters.end_date.calendarPopup()
    assert not any(button.text() in ("Cal", "Reset") for button in filters.findChildren(QPushButton))


def test_programmatic_dates_keep_the_filter_selection_visible(filters):
    filters.start_date.setDate(QDate(2025, 4, 3))
    filters.end_date.setDate(QDate(2025, 4, 8))
    assert filters.date_preset.currentData() == "custom"
    assert not filters.custom_dates.isHidden()
    assert filters.start_date.displayFormat() == "dd MMM yyyy"
    assert filters.layout().alignment() & Qt.AlignmentFlag.AlignTop
