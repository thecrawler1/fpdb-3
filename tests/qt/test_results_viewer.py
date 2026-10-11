"""Real imported cash data, parameterized worker queries and results navigation."""

import ast
import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QDate, QObject, QSettings, Qt, Signal
from PySide6.QtWidgets import QComboBox

from fpdb_3_legacy.GuiResultsViewer import GuiResultsViewer
from fpdb_3_legacy.period_results import parse_result_rows

pytestmark = pytest.mark.qt


class ControlledWorker(QObject):
    finished = Signal(str, list, list)
    error = Signal(str)

    def __init__(self, db, name, sql, params):
        super().__init__()
        self.name, self.sql, self.params = name, sql, params

    def start(self):
        pass

    def isFinished(self):
        return False

    def wait(self):
        return True


@pytest.fixture
def controlled_results(monkeypatch, report):
    import fpdb_3_legacy.GuiResultsViewer as module

    monkeypatch.setattr(module, "DbWorker", ControlledWorker)
    return report


@pytest.fixture
def hand_review(report, qtbot, tmp_path):
    from fpdb_3_legacy.GuiHandViewer import GuiHandViewer

    viewer = GuiHandViewer(report.conf, report.db.sql, None)
    viewer.columnControls.settings = QSettings(str(tmp_path / "review.ini"), QSettings.Format.IniFormat)
    qtbot.addWidget(viewer)
    viewer.page_size = 1
    viewer.reload_hands([hand.hand_id for hand in report.raw_hands])
    yield viewer
    viewer.close_owned_database()


@pytest.fixture
def report(qtbot, importer, fresh_db, legacy_config, tmp_path):
    for site in legacy_config.supported_sites.values():
        site.enabled = False
    legacy_config.supported_sites["PokerStars"].enabled = True
    legacy_config.supported_sites["PokerStars"].screen_name = "Hero"
    fixture = Path(__file__).parents[1] / "fixtures/hands/pokerstars/review/nl_3bet_6max.txt"
    original = fixture.read_text()
    source = tmp_path / "results.txt"
    source.write_text("\n".join(original.replace("2810000001", str(2810000001 + i)) for i in range(3)))
    importer.addImportFile(str(source), "PokerStars")
    assert importer.runImport()[0] == 3
    cursor = fresh_db.get_cursor()
    cursor.execute("SELECT id FROM Hands ORDER BY id")
    ids = [row[0] for row in cursor.fetchall()]
    first = datetime.now(timezone.utc).replace(day=1, hour=12, minute=0, second=0, microsecond=0)
    for i, hand_id in enumerate(ids):
        stamp = first + timedelta(days=i // 2, seconds=i)
        cursor.execute("UPDATE Hands SET startTime=? WHERE id=?", (stamp.strftime("%Y-%m-%d %H:%M:%S"), hand_id))
    cursor.close()
    fresh_db.commit()
    widget = GuiResultsViewer(legacy_config, db=fresh_db, zone=timezone.utc, autoload=False)
    qtbot.addWidget(widget)
    widget.resize(1280, 900)
    widget.show()
    widget.refresh()
    qtbot.waitUntil(lambda: len(widget.raw_hands) == 3, timeout=10000)
    yield widget
    widget.close()


def test_imported_daily_results_match_total_and_four_curves(report):
    assert report.model.columnCount() == 8
    assert report.model.rowCount() == 2
    assert len(report.total.hands) == 3
    assert report.total.profit == -2400 and report.total.ev == -2400
    assert report.total.vpip == report.total.pfr == 100
    assert report.total.bb_per_100 == -800
    report.select_total()
    curves = report.graph.listDataItems()
    assert len(curves) == 4
    assert curves[0].getData()[1][-1] == -24
    assert curves[1].getData()[1][-1] + curves[2].getData()[1][-1] == -24
    assert curves[3].getData()[1][-1] == -24
    assert all(combo.findText("USD") == -1 for combo in report.findChildren(QComboBox))


def test_reset_graph_restores_data_after_zoom_and_pan(report, qtbot):
    report.select_total()
    view = report.graph.getViewBox()
    view.setRange(xRange=(100, 110), yRange=(100, 110), padding=0)
    qtbot.mouseClick(report.reset_graph_button, Qt.MouseButton.LeftButton)
    x_range, y_range = view.viewRange()
    assert x_range[0] <= 0 and x_range[1] >= 2
    assert y_range[0] <= -24 and y_range[1] >= -8


def test_hand_viewer_sorts_entire_population_before_pagination(report, qtbot):
    from PySide6.QtWidgets import QHeaderView

    from fpdb_3_legacy.GuiHandViewer import GuiHandViewer

    ids = sorted(hand.hand_id for hand in report.raw_hands)
    cursor = report.db.get_cursor()
    for handid, profit, pot in zip(ids, (100, -900, 500), (900, 3000, 200)):
        cursor.execute("UPDATE HandsPlayers SET totalProfit=? WHERE handId=?", (profit, handid))
        cursor.execute("UPDATE Hands SET finalPot=? WHERE id=?", (pot, handid))
    report.db.commit()
    viewer = GuiHandViewer(report.conf, report.db.sql, None)
    qtbot.addWidget(viewer)
    viewer.page_size = 1
    viewer.reload_hands(ids)
    viewer.view.sortByColumn(viewer.colnum["Net"], Qt.SortOrder.DescendingOrder)
    assert viewer.all_handids == [ids[2], ids[0], ids[1]]
    assert int(viewer.filterModel.index(0, viewer.colnum["HandId"]).data()) == ids[2]
    viewer.next_page()
    assert int(viewer.filterModel.index(0, viewer.colnum["HandId"]).data()) == ids[0]
    viewer.view.sortByColumn(viewer.colnum["Total Pot"], Qt.SortOrder.DescendingOrder)
    assert viewer.page == 0
    assert viewer.all_handids == [ids[1], ids[0], ids[2]]
    viewer.view.sortByColumn(viewer.colnum["Date"], Qt.SortOrder.AscendingOrder)
    assert viewer.all_handids == ids
    for column in ("Street0", "Street1-4", "Players"):
        viewer.view.sortByColumn(viewer.colnum[column], Qt.SortOrder.DescendingOrder)
        assert set(viewer.all_handids) == set(ids)
    viewer.show()
    viewer.hide()
    viewer.show()
    assert viewer.view.horizontalHeader().sectionResizeMode(0) == QHeaderView.ResizeMode.Interactive
    assert viewer.render_cards("Ah Ks").size().width() == 65
    assert viewer.render_boards([["Ah", "Ks", "2d"], ["Ac", "Kd", "2s"]]).height() == 76
    viewer.close_owned_database()


def test_calendar_modes_reuse_same_population_and_total_row(report):
    original_workers = len(report._workers)
    for grouping in ("week", "month", "year", "day"):
        report.group_combo.setCurrentIndex(report.group_combo.findData(grouping))
        assert sum(len(period.hands) for period in report.periods) == 3
        assert report.total.profit == -2400
    assert len(report._workers) == original_workers
    report.select_total()
    report.units_combo.setCurrentIndex(1)
    assert report.graph.listDataItems()[0].getData()[1][-1] == -24
    report.line_checks[1].setChecked(False)
    assert not report.graph.listDataItems()[1].isVisible()


def test_live_theme_switch_repaints_cards_without_losing_page_or_selection(report, qtbot):
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QColor

    from fpdb_3_legacy.color_tokens import semantic_palette
    from fpdb_3_legacy.GuiHandViewer import GuiHandViewer
    from fpdb_3_legacy.ThemeManager import ThemeManager

    viewer = GuiHandViewer(report.conf, report.db.sql, None)
    qtbot.addWidget(viewer)
    viewer.page_size = 1
    viewer.reload_hands([hand.hand_id for hand in report.raw_hands])
    viewer.next_page()
    viewer.view.setCurrentIndex(viewer.filterModel.index(0, 0))
    selected = viewer.filterModel.index(0, viewer.colnum['HandId']).data()
    manager = ThemeManager()
    try:
        for theme, dark in (("light_lightgreen.xml", False), ("dark_lightgreen.xml", True)):
            assert manager.set_qt_material_theme(theme, save=False, apply_to_ui=True)
            assert viewer.page == 1
            assert viewer.view.currentIndex().siblingAtColumn(viewer.colnum['HandId']).data() == selected
            icon = viewer.model.item(0, viewer.colnum['Street0']).data(Qt.ItemDataRole.DecorationRole)
            image = icon.pixmap(QSize(700, 160)).toImage()
            assert image.pixelColor(5, 31).name() == semantic_palette(dark)['card']
            title_colour = report.graph.getPlotItem().titleLabel.opts['color']
            assert QColor(title_colour).name() == semantic_palette(dark)['muted_text']
    finally:
        manager.set_qt_material_theme("dark_lightgreen.xml", save=False, apply_to_ui=True)
        viewer.close_owned_database()


def test_numeric_sorting_period_selection_and_exact_hand_ids(report, qtbot):
    report.table.sortByColumn(1, Qt.SortOrder.DescendingOrder)
    report.table.setCurrentIndex(report.proxy.index(0, 0))
    chosen = report.selected_result()
    assert len(chosen.hands) == 2
    assert report.graph.listDataItems()[0].getData()[1][-1] == -16
    with qtbot.waitSignal(report.hands_requested) as signal:
        report.open_hands()
    assert signal.args[0] == [h.hand_id for h in reversed(chosen.hands)]
    report.select_total()
    with qtbot.waitSignal(report.hands_requested) as signal:
        report.open_hands()
    assert set(signal.args[0]) == {h.hand_id for h in report.total.hands}


def test_refresh_preserves_selected_day_after_async_replacement(report, qtbot):
    report.table.setCurrentIndex(report.proxy.index(report.proxy.rowCount() - 1, 0))
    selected = report.selection
    report.refresh()
    qtbot.waitUntil(lambda: len(report.raw_hands) == 3, timeout=10000)
    assert report.selection == selected
    assert len(report.selected_result().hands) == 2


def test_clicking_the_same_day_after_total_returns_to_that_days_graph(report, qtbot):
    index = report.table.currentIndex()
    chosen = report.selection
    report.select_total()
    assert len(report.selected_result().hands) == 3
    qtbot.mouseClick(report.table.viewport(), Qt.MouseButton.LeftButton, pos=report.table.visualRect(index).center())
    assert report.selection == chosen
    assert len(report.selected_result().hands) == 1


def test_mixed_stake_graph_and_zero_ev_line_are_preserved(report):
    stamp = report.raw_hands[0].timestamp
    report.raw_hands = parse_result_rows([
        (91, stamp, 100, 0, 10, 1, 1, 1, 1, True, "holdem", "nl"),
        (92, stamp, 100, 0, 20, 1, 1, 0, 1, False, "holdem", "nl"),
    ])
    report._populate_filters()
    report._rebuild_table()
    report.select_total()
    assert report.graph.listDataItems()[0].getData()[1][-1] == 2
    assert report.graph.listDataItems()[3].getData()[1][-1] == 0
    report.units_combo.setCurrentIndex(1)
    assert report.graph.listDataItems()[0].getData()[1][-1] == 15
    assert report.total.bb_per_100 == 750
    report.limit_combo.setCurrentIndex(1)
    assert len(report.total.hands) == 1
    assert report.total.bb_per_100 == 1000


def test_refresh_ignores_obsolete_workers_and_closing_keeps_borrowed_db(report, monkeypatch):
    import fpdb_3_legacy.GuiResultsViewer as module

    class Worker(QObject):
        finished = Signal(str, list, list)
        error = Signal(str)

        def __init__(self, db, name, sql, params):
            super().__init__()
            self.name, self.sql, self.params = name, sql, params

        def start(self):
            pass

        def isFinished(self):
            return False

        def wait(self):
            return True

    monkeypatch.setattr(module, "DbWorker", Worker)
    original = report.raw_hands
    report.refresh()
    old = report._workers[-1]
    report.refresh()
    new = report._workers[-1]
    rows = [(77, datetime.now(timezone.utc), 100, 50, 10, 1, 1, 0, 1, False, "holdem", "nl")]
    old.finished.emit(old.name, rows, [])
    assert report.raw_hands == original
    new.finished.emit(new.name, rows, [])
    assert len(report.raw_hands) == 1
    old.error.emit("obsolete failure")
    assert "obsolete" not in report.status.text()
    assert "hp.playerId = ?" in new.sql and len(new.params) == 3
    report.close()
    cursor = report.db.get_cursor()
    cursor.execute("SELECT COUNT(*) FROM Hands")
    assert cursor.fetchone()[0] == 3
    cursor.close()


def test_custom_date_edits_are_debounced_and_invalid_ranges_do_not_query(controlled_results, qtbot):
    report = controlled_results
    report.interval_combo.setCurrentIndex(report.interval_combo.findData("custom"))
    before = len(report._workers)
    day = report.raw_hands[0].timestamp.date()
    report.from_date.setDate(QDate(day.year, day.month, day.day))
    report.to_date.setDate(QDate(day.year, day.month, day.day + 1))
    qtbot.waitUntil(lambda: len(report._workers) == before + 1, timeout=2000)
    worker = report._workers[-1]
    assert worker.params[1].startswith(day.isoformat())
    assert worker.params[2].startswith((day + timedelta(days=2)).isoformat())
    before = len(report._workers)
    original = report.raw_hands
    report.from_date.setDate(report.to_date.date().addDays(1))
    qtbot.wait(400)
    assert len(report._workers) == before
    assert report.raw_hands == original
    assert "Start date" in report.status.text()
    assert not report.export_button.isEnabled()


def test_failed_refresh_preserves_results_and_error_until_success(controlled_results):
    report = controlled_results
    original, original_count = report.raw_hands, report.model.rowCount()
    report.refresh()
    assert report.raw_hands == original and report.model.rowCount() == original_count
    assert not report.hands_button.isEnabled() and not report.export_button.isEnabled()
    report._workers[-1].error.emit("connection unavailable")
    assert report.raw_hands == original
    report.group_combo.setCurrentIndex(report.group_combo.findData("week"))
    assert "connection unavailable" in report.status.text()
    report.refresh()
    worker = report._workers[-1]
    worker.finished.emit(worker.name, [(77, datetime.now(timezone.utc), 100, 50, 10, 1, 1, 0, 1, False, "holdem", "nl")], [])
    assert report._results_current
    assert report.raw_hands[0].hand_id == 77
    assert "unavailable" not in report.status.text()
    assert report.export_button.isEnabled()


def test_csv_exports_all_filtered_periods_in_table_order_with_exact_total(report, tmp_path):
    report.table.sortByColumn(1, Qt.SortOrder.DescendingOrder)
    path = tmp_path / "résultats.csv"
    assert report.export_csv(str(path))
    with path.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    assert len(rows) == 3
    assert rows[0]['Hands'] == "2" and rows[1]['Hands'] == "1"
    assert rows[-1]['Period'] == "Total"
    assert sum(Decimal(row['Profit (USD)']) for row in rows[:-1]) == Decimal(rows[-1]['Profit (USD)']) == -24
    assert Decimal(rows[-1]['EV (USD)']) == -24
    assert rows[-1]['Hands with valid BB'] == "3"
    assert rows[-1]['Start'] == rows[-1]['End'] == ""
    assert not report.export_csv(str(tmp_path / "missing" / "results.csv"))
    assert "Could not export" in report.status.text()


def test_total_columns_follow_reordered_results_columns(report):
    header = report.table.horizontalHeader()
    header.moveSection(header.visualIndex(4), 0)
    assert report.total_table.horizontalHeader().logicalIndex(0) == 4
    assert report.total_table.columnWidth(4) == report.table.columnWidth(4)


def test_hand_id_search_covers_unseen_pages_and_clear_restores_population(hand_review, qtbot):
    viewer = hand_review
    original = set(viewer.all_handids)
    viewer.handSearch.setText("#2810000001")
    qtbot.waitUntil(lambda: len(viewer.all_handids) == 1, timeout=2000)
    assert int(viewer.filterModel.index(0, viewer.colnum['SiteHandNo']).data()) == 2810000001
    viewer.handSearch.setText("999999999999")
    qtbot.waitUntil(lambda: not viewer.all_handids, timeout=2000)
    assert viewer.model.rowCount() == 0 and not viewer.pageSpin.isEnabled()
    viewer.handSearch.clear()
    qtbot.waitUntil(lambda: set(viewer.all_handids) == original, timeout=2000)
    assert viewer.model.rowCount() == 1


def test_direct_page_navigation_and_page_size_preserve_current_data(hand_review):
    viewer = hand_review
    viewer.pageSpin.setValue(3)
    assert viewer.page == 2
    assert int(viewer.filterModel.index(0, viewer.colnum['HandId']).data()) == viewer.all_handids[2]
    viewer.pageSizeCombo.setCurrentIndex(viewer.pageSizeCombo.findData(25))
    assert viewer.page_size == 25 and viewer.page == 0
    assert viewer.model.rowCount() == 3
    assert viewer.columnControls.settings.value("cash-hands/page-size", type=int) == 25


def test_hand_cache_is_bounded_and_recent_pages_are_reused(hand_review, monkeypatch):
    viewer = hand_review
    sample = next(iter(viewer.hands.values()))
    imported = []

    def import_hand(handid):
        imported.append(handid)
        return sample

    monkeypatch.setattr(viewer, "importhand", import_hand)
    viewer.page_size = 50
    viewer.reload_hands(range(1000, 1350))
    for _ in range(6):
        viewer.next_page()
    assert len(viewer.hands) == 300 and len(viewer.all_handids) == 350
    before = len(imported)
    viewer.prev_page()
    assert len(imported) == before
    viewer.pageSpin.setValue(1)
    assert len(imported) == before + 50 and len(viewer.hands) == 300


def test_cancelled_page_loading_keeps_previous_rows_page_and_selection(hand_review, monkeypatch):
    import fpdb_3_legacy.GuiHandViewer as module

    class CanceledProgress:
        def __init__(self, *_args):
            pass

        def wasCanceled(self):
            return True

        def __getattr__(self, _name):
            return lambda *_args: None

    viewer = hand_review
    selected = viewer._selected_hand_id()
    before = list(viewer.hands)
    monkeypatch.setattr(module, "QProgressDialog", CanceledProgress)
    viewer.next_page()
    assert viewer.page == 0
    assert viewer._selected_hand_id() == selected
    assert list(viewer.hands) == before
    assert viewer.model.rowCount() == 1 and not viewer._page_loading
    assert "canceled" in viewer.handStatusLabel.text()
    assert viewer.loadButton.isEnabled() and viewer.nextPageButton.isEnabled()
    previous_order = list(viewer.all_handids)
    previous_sort = viewer._sort_column, viewer._sort_order
    viewer.view.sortByColumn(viewer.colnum['HandId'], Qt.SortOrder.AscendingOrder)
    assert viewer.all_handids == previous_order
    assert (viewer._sort_column, viewer._sort_order) == previous_sort
    assert viewer.view.horizontalHeader().sortIndicatorSection() == previous_sort[0]


def test_bad_hand_is_reported_without_aborting_other_rows(hand_review, monkeypatch):
    viewer = hand_review
    original = viewer.importhand
    broken = viewer.all_handids[1]

    def import_hand(handid):
        if handid == broken:
            raise ValueError("damaged hand")
        return original(handid)

    monkeypatch.setattr(viewer, "importhand", import_hand)
    viewer.page_size = 3
    viewer.render_page()
    assert viewer.model.rowCount() == 2
    assert "1 hands could not be loaded" in viewer.handStatusLabel.text()
    assert viewer.replayButton.isEnabled()


def test_monetary_roles_never_parse_localized_display_strings(hand_review, monkeypatch):
    import fpdb_3_legacy.GuiHandViewer as module
    from fpdb_3_legacy.localized_formats import format_currency

    viewer = hand_review
    handid = viewer.all_handids[0]
    hand = viewer.hands[handid]
    monkeypatch.setattr(module, "format_number", lambda _value: "1.234,50")
    items = viewer._hand_row_items(handid, hand)
    net = hand.net_collected[hand.hero]
    item = items[viewer.colnum['Net']]
    assert item.data(Qt.ItemDataRole.UserRole) == float(net)
    assert item.text() == format_currency(net, hand.gametype['currency'])
    assert item.foreground().color().name() == module.current_palette()['danger']
    assert items[viewer.colnum['Total Pot']].data(Qt.ItemDataRole.UserRole) == float(hand.totalpot)


def test_visible_grouping_and_unit_segments_share_the_existing_state(report):
    report.group_segments.buttons[1].click()
    assert report.group_combo.currentData() == "week" and len(report.periods) == 1
    assert report.total.profit == -2400
    report.group_combo.setCurrentIndex(report.group_combo.findData("month"))
    assert report.group_segments.buttons[2].isChecked()
    report.units_segments.buttons[1].click()
    assert report.units_combo.currentData() is True
    assert report.graph.getAxis("left").labelText == "BB"
    assert not report.graph.getAxis("left").autoSIPrefix


def test_small_currency_values_are_not_displayed_as_milli_dollars(report):
    axis = report.graph.getAxis("left")
    axis.setRange(-.5, .5)
    assert axis.autoSIPrefixScale == 1
    assert float(axis.tickStrings([.2], axis.autoSIPrefixScale * axis.scale, .1)[0]) == .2


def test_collapsed_filters_remain_visible_and_clear_only_once(report, monkeypatch):
    report.game_combo.setCurrentIndex(1)
    assert report.game_combo.currentText() == "Hold'em"
    report.limit_combo.setCurrentIndex(1)
    assert not report.more_filters.isChecked()
    assert not report.active_filters.isHidden()
    assert "(2)" in report.more_filters.text()
    rebuilt = []
    original = report._rebuild_table

    def rebuild():
        rebuilt.append(True)
        original()

    monkeypatch.setattr(report, "_rebuild_table", rebuild)
    report.active_filters.clear_button.click()
    assert report.game_combo.currentData() is report.limit_combo.currentData() is None
    assert report.active_filters.isHidden()
    assert rebuilt == [True]


def test_inline_empty_filters_offer_a_working_recovery_action(report):
    report.game_combo.addItem("Absent game", "absent")
    report.game_combo.setCurrentIndex(report.game_combo.count() - 1)
    assert not report.empty_state.isHidden()
    assert report.graph_panel.isHidden()
    assert report.total_table.isHidden()
    report.empty_state.action.click()
    assert report.total.profit == -2400 and report.model.rowCount() == 2
    assert report.empty_state.isHidden() and not report.graph_panel.isHidden()


def test_all_periods_has_an_explicit_button_and_period_changes_fit_the_chart(report, qtbot):
    report.all_periods_button.click()
    assert report.selection == "total" and report.all_periods_button.isChecked()
    assert "All periods" in report.selection_label.text()
    assert report.graph.listDataItems()[0].getData()[1][-1] == -24
    report.graph.getViewBox().setRange(xRange=(100, 110), yRange=(100, 110), padding=0)
    index = report.proxy.index(0, 0)
    qtbot.mouseClick(report.table.viewport(), Qt.MouseButton.LeftButton, pos=report.table.visualRect(index).center())
    assert not report.all_periods_button.isChecked()
    assert report.graph.getViewBox().viewRange()[0][1] < 10


def test_empty_database_import_action_emits_navigation_request(qtbot, fresh_db, legacy_config):
    widget = GuiResultsViewer(legacy_config, db=fresh_db, autoload=False)
    qtbot.addWidget(widget)
    assert not widget.empty_state.isHidden()
    assert "Import" in widget.empty_state.title.text()
    with qtbot.waitSignal(widget.import_requested):
        widget.empty_state.action.click()
    widget.close()


def test_hand_footer_tracks_selection_and_empty_search_can_be_cleared(hand_review, qtbot):
    viewer = hand_review
    viewer.next_page()
    site_id = viewer.filterModel.index(0, viewer.colnum['SiteHandNo']).data()
    assert str(site_id) in viewer.selectedHandLabel.text()
    assert "Net" in viewer.selectedHandDetails.text()
    assert viewer.replayButton.parentWidget() is viewer.selectionBar
    viewer.handSearch.setText("999999999999")
    qtbot.waitUntil(lambda: not viewer.all_handids, timeout=2000)
    assert not viewer.empty_state.isHidden()
    viewer.empty_state.action.click()
    qtbot.waitUntil(lambda: len(viewer.all_handids) == 3, timeout=2000)
    assert viewer.empty_state.isHidden()


def test_hand_feature_names_and_chips_are_understandable_and_removable(hand_review, monkeypatch):
    viewer = hand_review
    loads = []
    monkeypatch.setattr(viewer, "loadHands", lambda _checked: loads.append(True))
    viewer.filtersButton.setChecked(True)
    assert viewer.flagFilters.parentWidget() is viewer.filterPanel
    assert viewer.flagAllIn.text() == "All-in"
    viewer.flagAllIn.setChecked(True)
    viewer.flagShowdown.setChecked(True)
    chip = viewer.active_hand_filters.buttons['features']
    assert "All-in" in chip.text() and "Showdown" in chip.text()
    before = len(loads)
    chip.click()
    assert not viewer.flagAllIn.isChecked() and not viewer.flagShowdown.isChecked()
    assert len(loads) == before + 1


def test_results_hand_link_reuses_existing_viewer_and_opens_one_if_needed():
    path = Path(__file__).parents[2] / "fpdb_3_legacy/fpdb.pyw"
    tree = ast.parse(path.read_text())
    method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "_open_result_hands")

    class Viewer:
        def reload_hands(self, ids):
            self.ids = ids

    namespace = {"GuiHandViewer": SimpleNamespace(GuiHandViewer=Viewer)}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), "exec"), namespace)
    existing = Viewer()
    calls = []
    owner = SimpleNamespace(threads=[existing], display_tab=calls.append,
                            tab_hand_viewer=lambda _: pytest.fail("Existing viewer must be reused"))
    namespace["_open_result_hands"](owner, [3, 2])
    assert existing.ids == [3, 2] and calls == ["Hand Viewer"]
    owner.threads.clear()
    owner.tab_hand_viewer = lambda _: owner.threads.append(Viewer())
    namespace["_open_result_hands"](owner, [1])
    assert owner.threads[0].ids == [1]
