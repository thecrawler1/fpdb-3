"""Global design consistency, exact nominal scaling and progressive disclosure."""

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QStandardItem, QStandardItemModel, QTextDocument
from PySide6.QtWidgets import QComboBox, QLabel, QMainWindow, QTableView, QTabWidget, QWidget

from fpdb_3_legacy.color_science import contrast_ratio
from fpdb_3_legacy.design_system import (
    ACCENT,
    DesignPolish,
    design_palette,
    modernize_rich_text,
    modernize_stylesheet,
)
from fpdb_3_legacy.replayer_style import replay_font
from fpdb_3_legacy.table_columns import install_column_controls

pytestmark = pytest.mark.qt


def test_text_scaling_is_125_percent_and_never_accumulates(qapp):
    style = "QWidget {font-size:12px; color:#b64fd8;} QLabel {font-size:10pt;}"
    scaled = modernize_stylesheet(style)
    assert "font-size:15px" in scaled and "font-size:12.5pt" in scaled
    assert ACCENT in scaled and "#b64fd8" not in scaled
    assert modernize_stylesheet(scaled) == scaled
    assert replay_font("DejaVu Sans", 10).pointSizeF() == 18.75  # Previous 15pt + 25%.


def test_rich_text_scales_without_exposing_internal_markers_or_extra_text(qapp):
    text = modernize_rich_text('<span style="font-size:12px">Pot odds</span><br><b>25%</b>')
    assert modernize_rich_text(text) == text
    document = QTextDocument()
    document.setHtml(text)
    assert document.toPlainText() == "Pot odds\n25%"


def test_local_styles_follow_global_policy_once(qapp, qtbot):
    label = QLabel("Example")
    qtbot.addWidget(label)
    label.setStyleSheet("font-size:16px; color:#a78bfa;")
    polish = DesignPolish(qapp)
    polish.polish_widget(label)
    assert "font-size:20px" in label.styleSheet()
    assert ACCENT in label.styleSheet()
    first = label.styleSheet()
    polish.polish_widget(label)
    assert label.styleSheet() == first


def test_legacy_surfaces_and_selected_combo_items_use_semantic_colours(qapp):
    from fpdb_3_legacy.design_system import application_stylesheet

    colors = design_palette(True)
    style = modernize_stylesheet("QFrame {background:#ffffff;} QLabel {color:#edf2f7;} "
                                "QComboBox::item:selected {background:#bef67a; color:#000000;}")
    assert f"background:{colors['panel']}" in style
    assert f"background:{colors['selection']}" in style
    assert f"color:{colors['text']}" in style
    assert modernize_stylesheet(style) == style
    assert "QComboBox::item:selected" in application_stylesheet(colors)
    assert "#cb48ed" in modernize_stylesheet("QLabel {color:#cb48ed;}")  # Unknown domain colour.


def test_local_semantic_styles_follow_light_dark_switch_without_rescaling(qapp):
    previous = qapp.property("fpdb_color_mode")
    dark, light = design_palette(True), design_palette(False)
    try:
        qapp.setProperty("fpdb_color_mode", "dark")
        style = modernize_stylesheet(f"QLabel {{background:{dark['panel']}; color:{dark['text']}; font-size:12px;}}")
        qapp.setProperty("fpdb_color_mode", "light")
        changed = modernize_stylesheet(style)
        assert light['panel'] in changed and light['text'] in changed
        assert "font-size:15px" in changed
        qapp.setProperty("fpdb_color_mode", "dark")
        assert modernize_stylesheet(changed) == style
    finally:
        qapp.setProperty("fpdb_color_mode", previous)


def test_palette_is_neutral_with_stepper_green_and_readable_selection():
    colors = design_palette(True)
    assert colors["window"] == "#13181d" and colors["accent"] == ACCENT
    assert colors["selection"] != colors["accent"]
    light = design_palette(False)
    assert contrast_ratio(light['accent'], light['base']) >= 4.5


def _view(qtbot):
    view = QTableView()
    qtbot.addWidget(view)
    model = QStandardItemModel(0, 4, view)
    model.setHorizontalHeaderLabels(["Date", "Hand", "Flags", "HandId"])
    model.appendRow([QStandardItem("2026-10-10"), QStandardItem("AA"), QStandardItem("AI"), QStandardItem("123")])
    view.setModel(model)
    return view, model


def test_column_choices_persist_and_hidden_ids_remain_available(qtbot, tmp_path):
    settings = QSettings(str(tmp_path / "columns.ini"), QSettings.Format.IniFormat)
    view, model = _view(qtbot)
    controller = install_column_controls(view, "hands", essential=("Date", "Hand"), settings=settings)
    assert not view.isColumnHidden(0) and not view.isColumnHidden(1)
    assert view.isColumnHidden(2) and view.isColumnHidden(3)
    assert model.index(0, 3).data() == "123"
    controller.set_visible(3, True)
    controller.set_visible(0, False)
    settings.sync()
    second, _ = _view(qtbot)
    install_column_controls(second, "hands", essential=("Date", "Hand"), settings=settings)
    assert second.isColumnHidden(0) and not second.isColumnHidden(3)
    controller.reset()
    assert not view.isColumnHidden(0) and view.isColumnHidden(3)
    controller.show_all()
    assert all(not view.isColumnHidden(i) for i in range(4))


def test_generic_tables_hide_diagnostics_and_keep_one_visible_column(qtbot, tmp_path):
    settings = QSettings(str(tmp_path / "generic.ini"), QSettings.Format.IniFormat)
    view, _ = _view(qtbot)
    controller = install_column_controls(view, "generic", settings=settings)
    assert view.isColumnHidden(2) and view.isColumnHidden(3)
    controller.set_visible(0, False)
    controller.set_visible(1, False)
    assert not view.isColumnHidden(1)
    controller.set_density(50)
    assert view.verticalHeader().defaultSectionSize() == 50


def test_task_navigation_reuses_open_tabs_and_discloses_analysis(qtbot):
    from fpdb_3_legacy.app_navigation import ApplicationNavigation

    owner = QMainWindow()
    qtbot.addWidget(owner)
    owner.nb = QTabWidget(owner)
    owner.nb.addTab(QWidget(), "Results")
    owner.nb_tab_names = ["Results"]
    calls = []
    owner.display_tab = calls.append
    owner.tab_hand_viewer = lambda _: calls.append("open hands")
    nav = ApplicationNavigation(owner)
    assert not nav.advanced_toggle.isChecked()
    nav.navigate("tab_results", "Results")
    nav.navigate("tab_hand_viewer", "Hand Viewer")
    assert calls == ["Results", "open hands"]
    owner.nb.addTab(QWidget(), "Ring Player Stats")
    owner.nb.setCurrentIndex(1)
    assert nav.advanced_toggle.isChecked()


def test_theme_reapplication_does_not_increase_font_or_duplicate_scaled_css(qapp):
    from fpdb_3_legacy.ThemeManager import ThemeManager

    manager = ThemeManager()
    assert manager.set_qt_material_theme("dark_lightgreen.xml", save=False, apply_to_ui=True)
    font = qapp.font().pointSizeF()
    assert manager.apply_legacy_polish()
    assert qapp.font().pointSizeF() == font
    assert manager.get_legacy_palette()["accent"] == ACCENT


def test_combo_popup_fits_long_options_and_recomputes_after_model_changes(qapp, qtbot):
    from fpdb_3_legacy.ThemeManager import ThemeManager

    ThemeManager().set_qt_material_theme("dark_lightgreen.xml", save=False, apply_to_ui=True)
    combo = QComboBox()
    qtbot.addWidget(combo)
    combo.setFixedWidth(120)
    combo.addItems(["All limits", "NL · BB $0.05 / $0.10 — PokerStars"])
    combo.show()
    combo.showPopup()
    qapp.processEvents()
    view = combo.view()
    assert view.viewport().width() >= view.sizeHintForColumn(combo.modelColumn())
    assert view.viewport().width() >= view.fontMetrics().horizontalAdvance(combo.itemText(1)) + 64
    first_width = view.window().width()
    combo.hidePopup()
    combo.addItem("NL · BB $0.05 / $0.10 — PokerStars · six-max cash tables")
    combo.showPopup()
    qapp.processEvents()
    assert view.viewport().width() >= view.sizeHintForColumn(combo.modelColumn())
    assert view.viewport().width() >= view.fontMetrics().horizontalAdvance(combo.itemText(2)) + 64
    assert view.window().width() > first_width
    assert combo.width() == 120
    combo.hidePopup()


def test_hand_viewer_defaults_to_review_columns_with_optional_details(qtbot, legacy_config, fresh_db, tmp_path):
    from fpdb_3_legacy.GuiHandViewer import GuiHandViewer

    view = GuiHandViewer(legacy_config, fresh_db.sql, None)
    qtbot.addWidget(view)
    view.columnControls.settings = QSettings(str(tmp_path / "hand-columns.ini"), QSettings.Format.IniFormat)
    view.columnControls.reset()
    visible = {key for key, column in view.colnum.items() if not view.view.isColumnHidden(column)}
    assert visible == {"Date", "Stakes", "Pos", "Street0", "Street1-4", "Net", "Total Pot"}
    assert view.model.columnCount() == 19 and view.colnum["HandId"] == 14
    assert not view.filtersButton.isChecked()
    assert view.flagFilters.isHidden()
    view.columnControls.show_all()
    assert not view.view.isColumnHidden(view.colnum["HandId"])
    view.columnControls.reset()
    view.close_owned_database()
    view.close()
