"""Controlled completion ordering for Results queries, views and graph requests."""

from datetime import datetime, timezone

import pytest
from PySide6.QtCore import QDate, QObject, Signal

import fpdb_3_legacy.GuiResultsViewer as module

pytestmark = pytest.mark.qt


class ControlledTask(QObject):
    completed = Signal(object)
    error = Signal(str)

    def __init__(self, task):
        super().__init__()
        self.task = task
        self.result = None
        self.done = False

    def start(self):
        pass

    def isFinished(self):
        return self.done

    def wait(self):
        return True

    def finish(self):
        self.result = self.task()
        self.done = True
        self.completed.emit(self.result)

    def fail(self, message):
        self.done = True
        self.error.emit(message)


class ControlledQuery(ControlledTask):
    finished = Signal(str, list, list)

    def __init__(self, db, name, query, params):
        super().__init__(lambda: None)
        self.name = name


def rows(count=1001, *, first_id=1):
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [(first_id + i, stamp, 100, 50, 10, 1, 1, 0, 1, False, "holdem", "nl")
            for i in range(count)]


@pytest.fixture
def viewer(monkeypatch, qtbot, fresh_db, legacy_config):
    monkeypatch.setattr(module, "TaskWorker", ControlledTask)
    monkeypatch.setattr(module, "DbWorker", ControlledQuery)
    widget = module.GuiResultsViewer(legacy_config, db=fresh_db, zone=timezone.utc, autoload=False)
    qtbot.addWidget(widget)
    widget._set_heroes([("Hero", 1)])
    yield widget
    widget.close()


def load_large(viewer):
    viewer._receive_rows(viewer._generation, rows())
    viewer._tasks[-1].finish()
    viewer._tasks[-1].finish()
    assert viewer._results_current
    assert viewer.graph.listDataItems()


def test_old_data_aggregation_preserves_pending_query_and_disabled_actions(viewer, tmp_path):
    load_large(viewer)
    viewer.refresh()
    query = viewer._workers[-1]
    status = viewer.status.text()
    viewer.group_combo.setCurrentIndex(viewer.group_combo.findData("week"))
    viewer._tasks[-1].finish()
    assert viewer._loading
    assert not viewer._results_current
    assert viewer.status.text() == status
    assert not viewer.hands_button.isEnabled()
    assert not viewer.export_button.isEnabled()
    assert not viewer.export_csv(str(tmp_path / "old.csv"))
    emitted = []
    viewer.hands_requested.connect(emitted.append)
    viewer.open_hands()
    assert not emitted
    query.finished.emit(query.name, rows(2, first_id=5000), [])
    assert viewer._data_generation == viewer._generation
    assert viewer._results_current
    assert viewer.export_button.isEnabled()
    assert viewer.raw_hands[0].hand_id == 5000


def test_old_data_aggregation_preserves_invalid_date_status(viewer):
    load_large(viewer)
    viewer.interval_combo.setCurrentIndex(viewer.interval_combo.findData("custom"))
    viewer.from_date.setDate(QDate(2026, 2, 2))
    viewer.to_date.setDate(QDate(2026, 2, 1))
    viewer.refresh()
    status = viewer.status.text()
    assert "Start date" in status
    viewer.group_combo.setCurrentIndex(viewer.group_combo.findData("month"))
    viewer._tasks[-1].finish()
    assert viewer.status.text() == status
    assert not viewer._results_current
    assert not viewer.export_button.isEnabled()
    assert not viewer.hands_button.isEnabled()


def test_empty_setup_is_valid_and_later_hero_discovery_stays_async(viewer, monkeypatch):
    viewer.hero_combo.blockSignals(True)
    viewer.hero_combo.clear()
    viewer.hero_combo.blockSignals(False)
    discoveries = []

    def prepare(config, querylist, db):
        discoveries.append(True)
        return db, [] if len(discoveries) == 1 else [("Imported Hero", 42)]

    monkeypatch.setattr(module, "prepare_results_database", prepare)
    monkeypatch.setattr(module, "discover_heroes", lambda *_: pytest.fail("Synchronous hero discovery"))
    viewer._setup_complete = False
    viewer.refresh()
    assert not discoveries
    viewer._tasks[-1].finish()
    assert discoveries == [True]
    assert viewer._setup_complete and not viewer._loading
    assert not viewer._has_load_error
    assert "No configured Hero" in viewer.status.text()
    assert not viewer._workers
    viewer.refresh()
    assert discoveries == [True]
    setup = viewer._tasks[-1]
    viewer.refresh()
    assert viewer._tasks[-1] is setup and viewer._loading
    viewer._tasks[-1].finish()
    assert discoveries == [True, True]
    assert viewer.hero_combo.currentData() == 42
    assert len(viewer._workers) == 1


def test_graph_clears_stale_plot_and_deduplicates_pending_request(viewer):
    load_large(viewer)
    viewer.units_combo.setCurrentIndex(1)
    pending = viewer._tasks[-1]
    count = len(viewer._tasks)
    assert not viewer.graph.listDataItems()
    assert viewer.graph.getAxis("left").labelText == "BB"
    viewer._render_graph()
    viewer._render_graph()
    assert len(viewer._tasks) == count
    assert viewer._tasks[-1] is pending
    pending.finish()
    assert viewer.graph.listDataItems()[0].getData()[1][-1] == 10010
    assert viewer._pending_curve is None


def test_returning_to_inflight_units_reuses_original_curve_worker(viewer):
    load_large(viewer)
    viewer._curve_cache.clear()
    viewer.units_combo.setCurrentIndex(1)
    bb = viewer._tasks[-1]
    viewer.units_combo.setCurrentIndex(0)
    dollars = viewer._tasks[-1]
    count = len(viewer._tasks)
    viewer.units_combo.setCurrentIndex(1)
    assert len(viewer._tasks) == count
    dollars.fail("superseded dollar curve")
    assert "superseded" not in viewer.status.text()
    bb.finish()
    assert viewer.graph.getAxis("left").labelText == "BB"
    assert viewer.graph.listDataItems()[0].getData()[1][-1] == 10010


@pytest.mark.parametrize("outcome", ["success", "failure"])
def test_receiving_new_rows_invalidates_pending_graph_before_preparation(viewer, outcome):
    load_large(viewer)
    viewer.units_combo.setCurrentIndex(1)
    obsolete = viewer._tasks[-1]
    viewer._receive_rows(viewer._generation, rows(first_id=5000))
    preparation = viewer._tasks[-1]
    status = viewer.status.text()
    if outcome == "success":
        obsolete.finish()
    else:
        obsolete.fail("obsolete curve failure")
    assert viewer.status.text() == status
    assert not viewer.graph.listDataItems()
    preparation.finish()
    viewer._tasks[-1].finish()
    assert viewer.raw_hands[0].hand_id == 5000
    assert viewer.graph.listDataItems()


def test_graph_failure_from_previous_query_does_not_replace_current_status(viewer):
    load_large(viewer)
    viewer.units_combo.setCurrentIndex(1)
    obsolete = viewer._tasks[-1]
    viewer.refresh()
    status = viewer.status.text()
    obsolete.fail("obsolete query graph failure")
    assert viewer.status.text() == status
    assert viewer._loading and not viewer._results_current


def test_superseded_view_failure_does_not_poison_new_view(viewer):
    load_large(viewer)
    viewer.group_combo.setCurrentIndex(viewer.group_combo.findData("week"))
    obsolete = viewer._tasks[-1]
    viewer.group_combo.setCurrentIndex(viewer.group_combo.findData("month"))
    current = viewer._tasks[-1]
    current.finish()
    obsolete.fail("obsolete grouping failure")
    assert viewer._results_current
    assert not viewer._has_load_error
    assert "obsolete" not in viewer.status.text()
