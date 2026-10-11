"""Real imported cash data, parameterized worker queries and results navigation."""

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QComboBox

from fpdb_3_legacy.GuiResultsViewer import GuiResultsViewer
from fpdb_3_legacy.period_results import parse_result_rows

pytestmark = pytest.mark.qt


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
    report.refresh()
    old = report._workers[-1]
    report.refresh()
    new = report._workers[-1]
    rows = [(77, datetime.now(timezone.utc), 100, 50, 10, 1, 1, 0, 1, False, "holdem", "nl")]
    old.finished.emit(old.name, rows, [])
    assert not report.raw_hands
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
